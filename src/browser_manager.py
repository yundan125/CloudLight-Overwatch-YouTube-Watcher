from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
import websocket

from config import profile_path
from live_detector import extract_video_id


LOGGER = logging.getLogger(__name__)


class BrowserNotFoundError(FileNotFoundError):
    pass


def _registry_app_path(executable: str) -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg

        key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{executable}"
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    value, _ = winreg.QueryValueEx(key, None)
                    if Path(value).is_file():
                        return str(Path(value))
            except OSError:
                continue
    except (ImportError, OSError):
        pass
    return ""


def browser_candidates(browser: str) -> list[Path]:
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    if browser == "brave":
        relative = Path("BraveSoftware/Brave-Browser/Application/brave.exe")
        executable = "brave.exe"
    else:
        relative = Path("Google/Chrome/Application/chrome.exe")
        executable = "chrome.exe"
    candidates = [program_files / relative, program_files_x86 / relative]
    if str(local_app_data):
        candidates.append(local_app_data / relative)
    registry = _registry_app_path(executable)
    if registry:
        candidates.append(Path(registry))
    found = shutil.which(executable)
    if found:
        candidates.append(Path(found))
    return candidates


def detect_browser(browser: str, configured_path: str = "") -> Path:
    if configured_path:
        path = Path(configured_path).expanduser()
        if path.is_file() and path.suffix.lower() == ".exe":
            return path.resolve()
        raise BrowserNotFoundError(f"配置的浏览器文件不存在：{path}")
    for path in browser_candidates(browser):
        if path.is_file():
            return path.resolve()
    display = "Brave" if browser == "brave" else "Google Chrome"
    raise BrowserNotFoundError(f"未检测到 {display}，请在界面中手动选择浏览器 exe")


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class BrowserSession:
    profile: str
    process: subprocess.Popen[Any]
    debug_port: int
    binary: Path
    profile_dir: Path
    headless: bool
    mute: bool
    last_url: str

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.debug_port}"

    def devtools_available(self) -> bool:
        try:
            response = requests.get(f"{self.base_url}/json/version", timeout=1.5)
            return response.ok
        except requests.RequestException:
            return False

    def is_running(self) -> bool:
        return self.process.poll() is None or self.devtools_available()

    def targets(self) -> list[dict[str, Any]]:
        try:
            response = requests.get(f"{self.base_url}/json", timeout=2)
            response.raise_for_status()
            result = response.json()
            return result if isinstance(result, list) else []
        except (requests.RequestException, ValueError):
            return []

    def open_url(self, url: str) -> bool:
        self.last_url = url
        try:
            endpoint = f"{self.base_url}/json/new?{quote(url, safe='')}"
            response = requests.put(endpoint, timeout=3)
            return response.ok
        except requests.RequestException:
            return False

    def _evaluate(self, target: dict[str, Any], expression: str) -> dict[str, Any] | None:
        websocket_url = target.get("webSocketDebuggerUrl")
        if not websocket_url:
            return None
        connection = None
        try:
            connection = websocket.create_connection(
                websocket_url,
                timeout=3,
                origin=f"http://127.0.0.1:{self.debug_port}",
            )
            connection.send(json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": expression, "returnByValue": True},
            }))
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                payload = json.loads(connection.recv())
                if payload.get("id") == 1:
                    return payload
        except Exception as exc:
            LOGGER.debug("DevTools 页面检查失败：%s", exc)
        finally:
            if connection:
                connection.close()
        return None

    def maintain_youtube_playback(self) -> str:
        """Return running, resumed, ended, login, missing, or unavailable."""
        targets = [item for item in self.targets() if item.get("type") == "page"]
        watch_targets = [item for item in targets if "youtube.com/watch" in str(item.get("url", ""))]
        if not watch_targets:
            if any("accounts.google.com" in str(item.get("url", "")) for item in targets):
                return "login"
            return "missing" if targets else "unavailable"
        mute_js = "true" if self.mute else "false"
        expression = f"""
            (() => {{
              const v = document.querySelector('video');
              if (!v) return {{state:'loading'}};
              v.muted = {mute_js};
              if (v.ended) return {{state:'ended'}};
              if (v.paused && v.readyState >= 2) {{
                v.play().catch(() => {{}});
                return {{state:'resumed'}};
              }}
              return {{state:'running', paused:v.paused, readyState:v.readyState}};
            }})()
        """
        result = self._evaluate(watch_targets[-1], expression)
        try:
            return str(result["result"]["result"]["value"]["state"])
        except (KeyError, TypeError):
            return "unavailable"

    def sample_video_state(self, expected_video_id: str) -> dict[str, Any] | None:
        """Sample the expected watch page and opportunistically resume a pause."""
        if not expected_video_id:
            return None
        targets = [item for item in self.targets() if item.get("type") == "page"]
        watch_target = next(
            (item for item in reversed(targets) if extract_video_id(str(item.get("url", ""))) == expected_video_id),
            None,
        )
        if not watch_target:
            return None
        mute_js = "true" if self.mute else "false"
        expression = f"""
            (() => {{
              const v = document.querySelector('video');
              if (!v) return {{
                exists: false,
                pageUrl: location.href,
                title: document.title.replace(/\\s*-\\s*YouTube$/, '')
              }};
              const state = {{
                exists: true,
                paused: v.paused,
                ended: v.ended,
                currentTime: Number.isFinite(v.currentTime) ? v.currentTime : null,
                readyState: v.readyState,
                playbackRate: v.playbackRate,
                pageUrl: location.href,
                title: document.title.replace(/\\s*-\\s*YouTube$/, ''),
                channel: document.querySelector('#owner #channel-name a, ytd-video-owner-renderer #channel-name a')?.textContent?.trim() || '',
                resumeAttempted: false
              }};
              v.muted = {mute_js};
              if (state.paused && !state.ended && state.readyState >= 2) {{
                state.resumeAttempted = true;
                v.play().catch(() => {{}});
              }}
              return state;
            }})()
        """
        result = self._evaluate(watch_target, expression)
        try:
            value = result["result"]["result"]["value"]
            if not isinstance(value, dict):
                return None
            if extract_video_id(str(value.get("pageUrl", ""))) != expected_video_id:
                return None
            return value
        except (KeyError, TypeError):
            return None

    def close(self) -> None:
        try:
            requests.get(f"{self.base_url}/json/version", timeout=0.5)
        except requests.RequestException:
            pass
        if self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                LOGGER.debug("浏览器主进程未在停止时退出：PID %s", self.process.pid)


class BrowserManager:
    def __init__(self) -> None:
        self.sessions: dict[str, BrowserSession] = {}
        self._lock = threading.RLock()

    def launch(self, profile: str, url: str, config: dict[str, Any]) -> BrowserSession:
        with self._lock:
            existing = self.sessions.get(profile)
            if existing and existing.is_running():
                if not existing.open_url(url):
                    subprocess.Popen([
                        str(existing.binary),
                        f"--user-data-dir={existing.profile_dir}",
                        url,
                    ])
                return existing

            binary = detect_browser(str(config.get("browser", "chrome")), str(config.get("browser_path", "")))
            data_dir = profile_path(profile)
            data_dir.mkdir(parents=True, exist_ok=True)
            debug_port = _free_local_port()
            headless = bool(config.get("headless", False))
            mute = bool(config.get("mute", True))
            arguments = [
                str(binary),
                f"--user-data-dir={data_dir}",
                f"--remote-debugging-port={debug_port}",
                "--remote-debugging-address=127.0.0.1",
                "--remote-allow-origins=*",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-features=Translate,HardwareMediaKeyHandling",
                "--autoplay-policy=no-user-gesture-required",
            ]
            if mute:
                arguments.append("--mute-audio")
            if headless:
                arguments.extend(["--headless=new", "--window-size=1280,800"])
            arguments.append(url)
            process = subprocess.Popen(arguments)
            session = BrowserSession(
                profile=profile,
                process=process,
                debug_port=debug_port,
                binary=binary,
                profile_dir=data_dir,
                headless=headless,
                mute=mute,
                last_url=url,
            )
            self.sessions[profile] = session
            for _ in range(25):
                if session.devtools_available() or process.poll() is not None:
                    break
                time.sleep(0.2)
            return session

    def ensure_running(self, profile: str, url: str, config: dict[str, Any]) -> tuple[BrowserSession, bool]:
        with self._lock:
            session = self.sessions.get(profile)
            if session and session.is_running():
                return session, False
        return self.launch(profile, url, config), True

    def sample_video_state(self, profile: str, expected_video_id: str) -> dict[str, Any] | None:
        with self._lock:
            session = self.sessions.get(profile)
        if not session or not session.is_running():
            return None
        return session.sample_video_state(expected_video_id)

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self.sessions.values())
            self.sessions.clear()
        for session in sessions:
            session.close()
