from __future__ import annotations

import copy
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any

from PySide6.QtCore import QObject, Signal

from browser_manager import BrowserManager
from constants import YOUTUBE_HOME
from live_detector import LiveDetector, StreamInfo, extract_video_id, normalize_youtube_url
from watch_history import WatchHistory, format_duration


LOGGER = logging.getLogger(__name__)
SAMPLE_INTERVAL_SECONDS = 5.0
SAVE_INTERVAL_SECONDS = 30.0
MAX_SAMPLE_WALL_SECONDS = 10.5
MAX_CREDIT_SECONDS = 10.0


class WatcherService(QObject):
    log_message = Signal(str)
    status_changed = Signal(str)
    stream_changed = Signal(object)
    running_changed = Signal(bool)
    error_occurred = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.detector = LiveDetector()
        self.browser_manager = BrowserManager()
        self.watch_history = WatchHistory()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._sampling_thread: threading.Thread | None = None
        self._operation_lock = threading.Lock()
        self._stream_lock = threading.RLock()
        self._current_stream: StreamInfo | None = None
        self._sample_states: dict[str, dict[str, Any]] = {}
        self._session_totals: dict[str, float] = {}

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _log(self, message: str) -> None:
        timestamped = f"[{datetime.now():%H:%M:%S}] {message}"
        LOGGER.info(message)
        self.log_message.emit(timestamped)

    def _status(self, status: str) -> None:
        self.status_changed.emit(status)

    def start(self, config: dict[str, Any]) -> None:
        if self.is_running:
            self._log("监控已经在运行")
            return
        self._stop_event.clear()
        snapshot = copy.deepcopy(config)
        with self._stream_lock:
            self._current_stream = None
            self._sample_states = {}
            self._session_totals = {}
        self._thread = threading.Thread(target=self._run, args=(snapshot,), name="watcher", daemon=True)
        self._sampling_thread = threading.Thread(
            target=self._sampling_loop,
            args=(snapshot,),
            name="watch-time-sampler",
            daemon=True,
        )
        self._thread.start()
        self._sampling_thread.start()

    def stop(self, close_browsers: bool = True) -> None:
        self._stop_event.set()
        sampling_thread = self._sampling_thread
        if sampling_thread and sampling_thread.is_alive() and sampling_thread is not threading.current_thread():
            sampling_thread.join(timeout=6)
        self._deactivate_stream("停止观看")
        self.watch_history.save(force=True)
        if close_browsers:
            self.browser_manager.close_all()
        self._status("未启动")
        self._log("已停止")

    def check_once(self, config: dict[str, Any]) -> None:
        if self.is_running:
            self._log("监控运行中，将按当前周期自动检查")
            return
        snapshot = copy.deepcopy(config)
        threading.Thread(target=self._check_once_worker, args=(snapshot,), daemon=True).start()

    def open_login(self, config: dict[str, Any], profile: str) -> None:
        snapshot = copy.deepcopy(config)

        def work() -> None:
            try:
                self._log(f"正在为 Profile“{profile}”打开 YouTube 登录窗口")
                self.browser_manager.launch(profile, YOUTUBE_HOME, snapshot)
                self._log("请在真实浏览器窗口中手动登录；软件不会读取或填写密码")
            except Exception as exc:
                self._fail(f"打开浏览器失败：{exc}")

        threading.Thread(target=work, daemon=True).start()

    def _check_once_worker(self, config: dict[str, Any]) -> None:
        if not self._operation_lock.acquire(blocking=False):
            self._log("已有检查正在进行")
            return
        try:
            if config.get("mode") == "manual":
                url = normalize_youtube_url(str(config.get("manual_url", "")))
                self.stream_changed.emit(StreamInfo("手动指定地址", "", url).to_dict())
                self._status("发现直播")
                self._log(f"手动 URL 有效：{url}")
                return
            self._status("正在检查直播")
            self._log("正在检查已启用的守望先锋 YouTube 频道")
            stream = self.detector.detect_any(list(config.get("channels", [])))
            if stream:
                self.stream_changed.emit(stream.to_dict())
                self._status("发现直播")
                self._log(f"发现直播：{stream.title}")
            elif self.detector.had_errors:
                self._status("发生错误")
                self._log("自动检测未完成：" + "；".join(self.detector.last_errors))
            else:
                self.stream_changed.emit({})
                self._status("未发现直播")
                self._log("当前没有检测到直播")
        except Exception as exc:
            self._fail(f"检查直播失败：{exc}")
        finally:
            self._operation_lock.release()

    def _enabled_channels(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        return [item for item in config.get("channels", []) if item.get("enabled", True)]

    def history_snapshot(self) -> dict[str, Any]:
        return self.watch_history.snapshot()

    def clear_history(self) -> None:
        self.watch_history.clear()

    def _activate_stream(self, stream: StreamInfo) -> None:
        with self._stream_lock:
            old_id = self._current_stream.video_id if self._current_stream else ""
            if old_id and old_id != stream.video_id:
                self._log_session_totals_locked("切换直播")
                self._sample_states = {}
                self._session_totals = {}
            self._current_stream = stream

    def _deactivate_stream(self, reason: str) -> None:
        with self._stream_lock:
            if self._current_stream:
                self._log_session_totals_locked(reason)
            self._current_stream = None
            self._sample_states = {}
            self._session_totals = {}
        self.watch_history.save()

    def _log_session_totals_locked(self, reason: str) -> None:
        for profile, seconds in self._session_totals.items():
            if seconds > 0:
                self._log(f"{reason}，Profile“{profile}”本次有效观看 {format_duration(seconds)}")

    @staticmethod
    def calculate_valid_delta(wall_delta: float, video_delta: float) -> float:
        if wall_delta <= 0 or wall_delta > MAX_SAMPLE_WALL_SECONDS:
            return 0.0
        if video_delta <= 0 or video_delta < wall_delta * 0.3:
            return 0.0
        return min(wall_delta, video_delta, MAX_CREDIT_SECONDS)

    def _pause_profile_timer(self, profile: str, sample_state: dict[str, Any], reason: str) -> None:
        was_counting = bool(sample_state.get("counting"))
        if was_counting:
            if reason == "paused":
                self._log(f"Profile“{profile}”的视频已暂停，已尝试恢复播放，暂停观看计时")
            else:
                self._log(f"Profile“{profile}”暂停观看计时（{reason}）")
        sample_state["counting"] = False
        if was_counting:
            self.watch_history.save()

    def _sampling_loop(self, config: dict[str, Any]) -> None:
        profiles = list(config.get("profiles") or ["主账号"])
        last_save = time.monotonic()
        try:
            while not self._stop_event.is_set():
                with self._stream_lock:
                    stream = copy.copy(self._current_stream)
                if not stream or not stream.video_id:
                    with self._stream_lock:
                        self._sample_states = {}
                    if self._stop_event.wait(SAMPLE_INTERVAL_SECONDS):
                        break
                    continue

                for profile in profiles:
                    if self._stop_event.is_set():
                        break
                    monotonic_now = time.monotonic()
                    local_now = datetime.now().astimezone()
                    state = self.browser_manager.sample_video_state(profile, stream.video_id)
                    with self._stream_lock:
                        if not self._current_stream or self._current_stream.video_id != stream.video_id:
                            break
                        sample_state = self._sample_states.setdefault(profile, {
                            "current_time": None,
                            "monotonic": None,
                            "local_time": None,
                            "counting": False,
                            "ever_counted": False,
                        })
                        previous_current = sample_state.get("current_time")
                        previous_monotonic = sample_state.get("monotonic")

                        if state is None:
                            self._pause_profile_timer(profile, sample_state, "直播页面或 DevTools 连接不可用")
                            sample_state["current_time"] = None
                            sample_state["monotonic"] = None
                            sample_state["local_time"] = None
                            continue

                        current_time = state.get("currentTime")
                        sample_state["current_time"] = current_time if isinstance(current_time, (int, float)) else None
                        sample_state["monotonic"] = monotonic_now
                        sample_state["local_time"] = local_now

                        if not state.get("exists"):
                            self._pause_profile_timer(profile, sample_state, "video 元素不存在")
                            continue
                        if state.get("paused"):
                            self._pause_profile_timer(profile, sample_state, "paused")
                            continue
                        if state.get("ended"):
                            self._pause_profile_timer(profile, sample_state, "视频已结束")
                            continue
                        if int(state.get("readyState") or 0) < 2:
                            self._pause_profile_timer(profile, sample_state, "视频仍在缓冲")
                            continue
                        if not isinstance(current_time, (int, float)):
                            self._pause_profile_timer(profile, sample_state, "无法读取播放进度")
                            continue
                        if not isinstance(previous_current, (int, float)) or not isinstance(previous_monotonic, (int, float)):
                            sample_state["counting"] = False
                            continue

                        wall_delta = monotonic_now - previous_monotonic
                        video_delta = float(current_time) - float(previous_current)
                        valid_delta = self.calculate_valid_delta(wall_delta, video_delta)
                        if valid_delta <= 0:
                            reason = "采样间隔异常" if wall_delta > MAX_SAMPLE_WALL_SECONDS else "播放进度未正常前进"
                            self._pause_profile_timer(profile, sample_state, reason)
                            continue

                        if not sample_state.get("counting"):
                            if sample_state.get("ever_counted"):
                                self._log(f"Profile“{profile}”已恢复播放，继续累计观看时长")
                            else:
                                self._log(f"Profile“{profile}”开始累计观看时长")
                            sample_state["counting"] = True
                            sample_state["ever_counted"] = True

                        title = str(state.get("title") or stream.title)
                        channel = str(state.get("channel") or stream.channel)
                        interval_start = local_now - timedelta(seconds=wall_delta)
                        self.watch_history.add_interval(
                            profile,
                            stream.video_id,
                            title,
                            channel,
                            stream.url,
                            valid_delta,
                            interval_start,
                            local_now,
                        )
                        self._session_totals[profile] = self._session_totals.get(profile, 0.0) + valid_delta

                if time.monotonic() - last_save >= SAVE_INTERVAL_SECONDS:
                    self.watch_history.save()
                    last_save = time.monotonic()
                if self._stop_event.wait(SAMPLE_INTERVAL_SECONDS):
                    break
        finally:
            self.watch_history.save(force=True)

    def _open_for_profiles(self, config: dict[str, Any], url: str) -> None:
        profiles = list(config.get("profiles") or ["主账号"])
        for profile in profiles:
            _, launched = self.browser_manager.ensure_running(profile, url, config)
            action = "启动浏览器" if launched else "复用浏览器"
            self._log(f"Profile“{profile}”：{action}并打开直播")

    def _maintain_profiles(self, config: dict[str, Any], url: str) -> None:
        for profile in list(config.get("profiles") or ["主账号"]):
            session, launched = self.browser_manager.ensure_running(profile, url, config)
            if launched:
                self._log(f"Profile“{profile}”的浏览器已意外关闭，正在自动重新打开")
                continue
            state = session.maintain_youtube_playback()
            if state == "resumed":
                self._log(f"Profile“{profile}”的视频已暂停，已尝试恢复播放")
            elif state == "missing":
                session.open_url(url)
                self._log(f"Profile“{profile}”的直播页面不存在，已重新打开")
            elif state == "login":
                self._status("登录失效")
                self._log(f"Profile“{profile}”停留在 Google 登录页面，请在有窗口模式下重新登录")
            elif state == "ended":
                self._log(f"Profile“{profile}”页面中的视频已结束")

    def _run(self, config: dict[str, Any]) -> None:
        self.running_changed.emit(True)
        current: StreamInfo | None = None
        consecutive_offline = 0
        interval = max(180, int(config.get("check_interval", 300)))
        try:
            if config.get("mode") == "manual":
                url = normalize_youtube_url(str(config.get("manual_url", "")))
                current = StreamInfo(
                    "手动指定地址",
                    "",
                    url,
                    video_id=extract_video_id(url),
                    source="手动 URL",
                )
                self.stream_changed.emit(current.to_dict())
                self._activate_stream(current)
                self._status("正在观看")
                self._open_for_profiles(config, current.url)
                while not self._stop_event.wait(interval):
                    self._maintain_profiles(config, current.url)
                return

            channels = self._enabled_channels(config)
            if not channels:
                raise ValueError("请至少启用一个自动检测频道")

            while not self._stop_event.is_set():
                self._status("正在检查直播")
                self._log("正在检查直播")
                detected = self.detector.detect_any(channels)
                if detected:
                    consecutive_offline = 0
                    changed = not current or current.url != detected.url
                    current = detected
                    self.stream_changed.emit(current.to_dict())
                    self._activate_stream(current)
                    if changed:
                        self._status("发现直播")
                        self._log(f"发现直播：{current.title}")
                        self._open_for_profiles(config, current.url)
                    self._status("正在观看")
                    self._maintain_profiles(config, current.url)
                elif self.detector.had_errors:
                    self._log("本轮检测遇到网络或 YouTube 解析错误，将保留当前观看并稍后重试")
                    if not current:
                        self._status("发生错误")
                elif current:
                    consecutive_offline += 1
                    if consecutive_offline >= 2:
                        self._status("直播已结束")
                        self._log("直播连续两次检测为离线，返回等待状态")
                        self._deactivate_stream("直播结束")
                        current = None
                        consecutive_offline = 0
                    else:
                        self._log("直播本轮显示离线，将在下轮复核后再判断结束")
                else:
                    self.stream_changed.emit({})
                    self._status("未发现直播")
                    self._log("当前没有直播，继续等待")

                if self._stop_event.wait(interval):
                    break
        except Exception as exc:
            self._fail(str(exc))
        finally:
            self._stop_event.set()
            self._deactivate_stream("停止观看")
            self.watch_history.save(force=True)
            self.running_changed.emit(False)
            if not self._stop_event.is_set():
                self._status("发生错误")

    def _fail(self, message: str) -> None:
        LOGGER.exception(message) if LOGGER.isEnabledFor(logging.DEBUG) else LOGGER.error(message)
        self._status("发生错误")
        self._log(message)
        self.error_occurred.emit(message)
