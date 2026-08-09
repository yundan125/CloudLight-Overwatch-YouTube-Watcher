from __future__ import annotations

import copy
import logging
import threading
from datetime import datetime
from typing import Any

from PySide6.QtCore import QObject, Signal

from browser_manager import BrowserManager
from constants import YOUTUBE_HOME
from live_detector import LiveDetector, StreamInfo, normalize_youtube_url


LOGGER = logging.getLogger(__name__)


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
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._operation_lock = threading.Lock()

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
        self._thread = threading.Thread(target=self._run, args=(snapshot,), name="watcher", daemon=True)
        self._thread.start()

    def stop(self, close_browsers: bool = True) -> None:
        self._stop_event.set()
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
                current = StreamInfo("手动指定地址", "", url, source="手动 URL")
                self.stream_changed.emit(current.to_dict())
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
            self.running_changed.emit(False)
            if not self._stop_event.is_set():
                self._status("发生错误")

    def _fail(self, message: str) -> None:
        LOGGER.exception(message) if LOGGER.isEnabledFor(logging.DEBUG) else LOGGER.error(message)
        self._status("发生错误")
        self._log(message)
        self.error_occurred.emit(message)
