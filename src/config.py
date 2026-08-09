from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from constants import DEFAULT_CONFIG
from paths import CONFIG_PATH, PROFILES_DIR, ensure_runtime_dirs


INVALID_PROFILE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def validate_profile_name(name: str) -> tuple[bool, str]:
    value = name.strip()
    if not value:
        return False, "Profile 名称不能为空"
    if len(value) > 40:
        return False, "Profile 名称不能超过 40 个字符"
    if value in {".", ".."} or value.endswith((".", " ")):
        return False, "Profile 名称格式无效"
    if INVALID_PROFILE_CHARS.search(value):
        return False, "Profile 名称包含 Windows 不允许的字符"
    if value.upper() in WINDOWS_RESERVED:
        return False, "该名称是 Windows 保留名称"
    return True, value


def profile_path(name: str) -> Path:
    valid, normalized = validate_profile_name(name)
    if not valid:
        raise ValueError(normalized)
    root = PROFILES_DIR.resolve()
    path = (root / normalized).resolve()
    if path.parent != root:
        raise ValueError("Profile 路径无效")
    return path


def _merge_defaults(raw: dict) -> dict:
    config = copy.deepcopy(DEFAULT_CONFIG)
    for key in config:
        if key in raw:
            config[key] = raw[key]

    if config["browser"] not in {"chrome", "brave"}:
        config["browser"] = "chrome"
    if config["mode"] not in {"auto", "manual"}:
        config["mode"] = "auto"
    try:
        config["check_interval"] = max(180, min(3600, int(config["check_interval"])))
    except (TypeError, ValueError):
        config["check_interval"] = 300

    channels = []
    raw_channels = config.get("channels", [])
    if not isinstance(raw_channels, list):
        raw_channels = []
    for item in raw_channels:
        if not isinstance(item, dict):
            continue
        channel_id = str(item.get("id", "")).strip()
        url = str(item.get("url", "")).strip()
        if not channel_id and not url:
            continue
        channels.append({
            "name": str(item.get("name", channel_id or url)).strip() or channel_id or url,
            "id": channel_id,
            "url": url,
            "enabled": bool(item.get("enabled", True)),
        })
    config["channels"] = channels or copy.deepcopy(DEFAULT_CONFIG["channels"])

    profiles = []
    raw_profiles = config.get("profiles", [])
    if not isinstance(raw_profiles, list):
        raw_profiles = []
    for name in raw_profiles:
        valid, normalized = validate_profile_name(str(name))
        if valid and normalized not in profiles:
            profiles.append(normalized)
    config["profiles"] = profiles or copy.deepcopy(DEFAULT_CONFIG["profiles"])
    return config


def load_config(path: Path = CONFIG_PATH) -> dict:
    ensure_runtime_dirs()
    if not path.exists():
        config = copy.deepcopy(DEFAULT_CONFIG)
        save_config(config, path)
        return config
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("config.json 顶层必须是对象")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 config.json：{exc}") from exc
    config = _merge_defaults(raw)
    if config != raw:
        save_config(config, path)
    return config


def save_config(config: dict, path: Path = CONFIG_PATH) -> None:
    ensure_runtime_dirs()
    normalized = _merge_defaults(config)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
