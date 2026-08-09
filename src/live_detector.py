from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import requests
import yt_dlp


LOGGER = logging.getLogger(__name__)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36"
)


@dataclass(slots=True)
class StreamInfo:
    title: str
    channel: str
    url: str
    video_id: str = ""
    start_time: str = ""
    source: str = "yt-dlp"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class _QuietYdlLogger:
    def debug(self, message: str) -> None:
        return

    def warning(self, message: str) -> None:
        LOGGER.debug("yt-dlp: %s", message)

    def error(self, message: str) -> None:
        LOGGER.debug("yt-dlp: %s", message)


def normalize_youtube_url(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("请输入 YouTube 直播地址")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL 必须以 http:// 或 https:// 开头")
    host = (parsed.hostname or "").lower()
    allowed = host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")
    if not allowed:
        raise ValueError("只支持 youtube.com 或 youtu.be 地址")
    return value


def _channel_live_url(channel: dict[str, Any]) -> str:
    configured = str(channel.get("url", "")).strip()
    if configured:
        parsed = urlparse(configured)
        path = parsed.path.rstrip("/")
        if path.endswith("/live") or "/watch" in path:
            return configured
        return configured.rstrip("/") + "/live"
    channel_id = str(channel.get("id", "")).strip()
    if not channel_id:
        raise ValueError("频道缺少 ID 或 URL")
    return f"https://www.youtube.com/channel/{channel_id}/live"


def _format_timestamp(info: dict[str, Any]) -> str:
    timestamp = info.get("release_timestamp") or info.get("timestamp")
    if timestamp:
        try:
            return datetime.fromtimestamp(float(timestamp)).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, OverflowError, TypeError, ValueError):
            pass
    upload_date = str(info.get("upload_date") or "")
    if len(upload_date) == 8 and upload_date.isdigit():
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
    return ""


def _from_ydl(channel: dict[str, Any], timeout: int) -> StreamInfo | None:
    live_url = _channel_live_url(channel)
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "ignore_no_formats_error": True,
        "socket_timeout": timeout,
        "retries": 1,
        "extractor_retries": 1,
        "cachedir": False,
        "logger": _QuietYdlLogger(),
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(live_url, download=False)
    if not info:
        return None
    if info.get("_type") == "playlist":
        entries = [entry for entry in (info.get("entries") or []) if entry]
        info = entries[0] if entries else {}
    is_live = bool(info.get("is_live")) or info.get("live_status") == "is_live"
    if not is_live:
        return None
    video_id = str(info.get("id") or "")
    url = str(info.get("webpage_url") or (f"https://www.youtube.com/watch?v={video_id}" if video_id else live_url))
    return StreamInfo(
        title=str(info.get("title") or "正在直播"),
        channel=str(info.get("channel") or info.get("uploader") or channel.get("name") or ""),
        url=url,
        video_id=video_id,
        start_time=_format_timestamp(info),
        source="yt-dlp",
    )


def _decode_json_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except (ValueError, json.JSONDecodeError):
        return html.unescape(value)


def _from_public_page(channel: dict[str, Any], timeout: int) -> StreamInfo | None:
    """Small fallback for a future yt-dlp extractor break.

    It deliberately requires YouTube's explicit ``isLiveNow`` flag. Merely being
    redirected from /live to an old broadcast is not treated as a live stream.
    """
    live_url = _channel_live_url(channel)
    response = requests.get(
        live_url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"},
        timeout=timeout,
    )
    response.raise_for_status()
    page = response.text
    marker_positions = [match.start() for match in re.finditer(r'"isLiveNow"\s*:\s*true', page)]
    for position in marker_positions:
        window = page[max(0, position - 20_000):position + 5_000]
        ids = list(re.finditer(r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"', window))
        if not ids:
            continue
        video_id = ids[-1].group(1)
        title_matches = list(re.finditer(r'"title"\s*:\s*\{"runs":\[\{"text":"(.*?)"', window))
        title = _decode_json_string(title_matches[-1].group(1)) if title_matches else "正在直播"
        return StreamInfo(
            title=title,
            channel=str(channel.get("name") or channel.get("id") or ""),
            url=f"https://www.youtube.com/watch?v={video_id}",
            video_id=video_id,
            source="YouTube 公开页面",
        )
    return None


class LiveDetector:
    def __init__(self, timeout: int = 15) -> None:
        self.timeout = timeout
        self.last_errors: list[str] = []

    @property
    def had_errors(self) -> bool:
        return bool(self.last_errors)

    def detect_channel(self, channel: dict[str, Any]) -> StreamInfo | None:
        errors: list[str] = []
        try:
            return _from_ydl(channel, self.timeout)
        except Exception as exc:  # yt-dlp raises many extractor/network-specific exception types
            errors.append(f"yt-dlp: {exc}")
            LOGGER.warning("频道 %s 的 yt-dlp 检测失败：%s", channel.get("name", ""), exc)
        try:
            fallback = _from_public_page(channel, self.timeout)
            if fallback:
                return fallback
        except Exception as exc:
            errors.append(f"公开页面: {exc}")
            LOGGER.warning("频道 %s 的公开页面检测失败：%s", channel.get("name", ""), exc)
        self.last_errors.extend(errors)
        return None

    def detect_any(self, channels: list[dict[str, Any]]) -> StreamInfo | None:
        self.last_errors = []
        for channel in channels:
            if not channel.get("enabled", True):
                continue
            result = self.detect_channel(channel)
            if result:
                return result
        return None

    def inspect_video(self, url: str) -> StreamInfo | None:
        """Inspect a known watch URL and return it only while it is live."""
        normalize_youtube_url(url)
        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "ignore_no_formats_error": True,
            "socket_timeout": self.timeout,
            "retries": 1,
            "cachedir": False,
            "logger": _QuietYdlLogger(),
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info or not (info.get("is_live") or info.get("live_status") == "is_live"):
            return None
        video_id = str(info.get("id") or "")
        return StreamInfo(
            title=str(info.get("title") or "正在直播"),
            channel=str(info.get("channel") or info.get("uploader") or ""),
            url=str(info.get("webpage_url") or url),
            video_id=video_id,
            start_time=_format_timestamp(info),
            source="yt-dlp",
        )
