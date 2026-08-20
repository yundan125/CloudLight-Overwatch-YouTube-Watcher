from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from paths import WATCH_HISTORY_PATH


LOGGER = logging.getLogger(__name__)


def format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class WatchHistory:
    """Thread-safe watch totals keyed by local date, profile, and video id."""

    def __init__(self, path: Path = WATCH_HISTORY_PATH) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._records: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            records = data.get("records", {}) if isinstance(data, dict) else {}
            if isinstance(records, dict):
                self._records = records
        except (OSError, ValueError, TypeError) as exc:
            LOGGER.error("读取观看记录失败，将使用空记录：%s", exc)

    def add_interval(
        self,
        profile: str,
        video_id: str,
        title: str,
        channel: str,
        url: str,
        seconds: float,
        started_at: datetime,
        ended_at: datetime,
    ) -> None:
        """Add a verified playback interval, splitting it at local midnight."""
        if seconds <= 0 or not video_id:
            return
        if started_at.tzinfo is None:
            started_at = started_at.astimezone()
        if ended_at.tzinfo is None:
            ended_at = ended_at.astimezone()
        wall_seconds = max((ended_at - started_at).total_seconds(), 0.0)
        if wall_seconds <= 0:
            self._add(profile, video_id, title, channel, url, seconds, ended_at)
            return

        cursor = started_at
        remaining = seconds
        with self._lock:
            while cursor.date() < ended_at.date():
                midnight = datetime.combine(cursor.date() + timedelta(days=1), time.min, cursor.tzinfo)
                fraction = max((midnight - cursor).total_seconds(), 0.0) / wall_seconds
                part = min(remaining, seconds * fraction)
                if part > 0:
                    self._add_locked(profile, video_id, title, channel, url, part, midnight - timedelta(microseconds=1))
                    remaining -= part
                cursor = midnight
            if remaining > 0:
                self._add_locked(profile, video_id, title, channel, url, remaining, ended_at)

    def _add(
        self,
        profile: str,
        video_id: str,
        title: str,
        channel: str,
        url: str,
        seconds: float,
        watched_at: datetime,
    ) -> None:
        with self._lock:
            self._add_locked(profile, video_id, title, channel, url, seconds, watched_at)

    def _add_locked(
        self,
        profile: str,
        video_id: str,
        title: str,
        channel: str,
        url: str,
        seconds: float,
        watched_at: datetime,
    ) -> None:
        date_key = watched_at.astimezone().date().isoformat()
        record = self._records.setdefault(date_key, {}).setdefault(profile, {}).setdefault(video_id, {
            "title": title,
            "channel": channel,
            "url": url,
            "watch_seconds": 0.0,
            "last_watched_at": watched_at.astimezone().isoformat(timespec="seconds"),
        })
        if title:
            record["title"] = title
        if channel:
            record["channel"] = channel
        if url:
            record["url"] = url
        record["watch_seconds"] = float(record.get("watch_seconds", 0.0)) + seconds
        record["last_watched_at"] = watched_at.astimezone().isoformat(timespec="seconds")
        self._dirty = True

    def snapshot(self, now: datetime | None = None) -> dict[str, Any]:
        now = (now or datetime.now().astimezone()).astimezone()
        dates = [(now.date() - timedelta(days=offset)).isoformat() for offset in range(7)]
        rows: list[dict[str, Any]] = []
        today_total = 0.0
        week_total = 0.0
        with self._lock:
            for date_key in dates:
                for profile, videos in self._records.get(date_key, {}).items():
                    if not isinstance(videos, dict):
                        continue
                    for video_id, record in videos.items():
                        if not isinstance(record, dict):
                            continue
                        seconds = float(record.get("watch_seconds", 0.0) or 0.0)
                        week_total += seconds
                        if date_key == dates[0]:
                            today_total += seconds
                        rows.append({
                            "date": date_key,
                            "profile": profile,
                            "video_id": video_id,
                            "title": str(record.get("title", "")),
                            "channel": str(record.get("channel", "")),
                            "url": str(record.get("url", "")),
                            "watch_seconds": seconds,
                            "last_watched_at": str(record.get("last_watched_at", "")),
                        })
        rows.sort(key=lambda item: (item["date"], item["last_watched_at"]), reverse=True)
        return {"rows": rows, "today_total": today_total, "week_total": week_total}

    def save(self, force: bool = False) -> None:
        with self._lock:
            if not self._dirty and not force:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + ".tmp")
            payload = {"records": self._records}
            try:
                with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
                self._dirty = False
            except OSError:
                LOGGER.exception("保存观看记录失败")
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def clear(self) -> None:
        with self._lock:
            self._records = {}
            self._dirty = True
            self.save(force=True)
