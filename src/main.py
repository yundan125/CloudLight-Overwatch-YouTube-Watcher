from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from constants import APP_NAME
from gui import LIGHT_THEME_QSS, MainWindow
from logging_setup import configure_logging
from paths import ensure_runtime_dirs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--detector-smoke", metavar="URL", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_runtime_dirs()
    configure_logging()
    if args.detector_smoke:
        from live_detector import LiveDetector

        try:
            return 0 if LiveDetector(timeout=25).inspect_video(args.detector_smoke) else 2
        except Exception:
            return 3
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(LIGHT_THEME_QSS)
    try:
        window = MainWindow(smoke_test=args.smoke_test)
    except Exception as exc:
        QMessageBox.critical(None, "启动失败", str(exc))
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
