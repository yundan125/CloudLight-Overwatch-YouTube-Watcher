"""Application constants."""

APP_NAME = "CloudLight Overwatch YouTube Watcher"
APP_VERSION = "3.0.0"

DEFAULT_CHANNELS = [
    {
        "name": "Overwatch Esports",
        "id": "UCiAInBL9kUzz1XRxk66v-gw",
        "url": "https://www.youtube.com/channel/UCiAInBL9kUzz1XRxk66v-gw/live",
        "enabled": True,
    },
    {
        "name": "Overwatch Contenders",
        "id": "UCWPW0pjx6gncOEnTW8kYzrg",
        "url": "https://www.youtube.com/channel/UCWPW0pjx6gncOEnTW8kYzrg/live",
        "enabled": False,
    },
]

DEFAULT_CONFIG = {
    "browser": "chrome",
    "browser_path": "",
    "headless": False,
    "mute": True,
    "mode": "auto",
    "manual_url": "",
    "check_interval": 300,
    "channels": DEFAULT_CHANNELS,
    "profiles": ["主账号"],
}

YOUTUBE_HOME = "https://www.youtube.com/"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3
