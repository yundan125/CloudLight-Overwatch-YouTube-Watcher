from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QInputDialog,
)

from config import load_config, profile_path, save_config, validate_profile_name
from constants import APP_NAME, APP_VERSION
from paths import RESOURCE_DIR
from watch_history import format_duration
from watcher import WatcherService


LOGGER = logging.getLogger(__name__)


STATUS_COLORS = {
    "未启动": "#6b7280",
    "正在检查直播": "#2563eb",
    "未发现直播": "#9a6700",
    "发现直播": "#059669",
    "正在观看": "#059669",
    "直播已结束": "#9a6700",
    "登录失效": "#dc2626",
    "发生错误": "#dc2626",
}


LIGHT_THEME_QSS = """
QMainWindow,
QWidget {
    background-color: #F5F7FA;
    color: #1F2937;
}

QLabel {
    background-color: transparent;
    color: #1F2937;
}

QLabel#appTitle {
    color: #0F172A;
    font-size: 22px;
    font-weight: 700;
}

QLabel#versionLabel,
QLabel#secondaryText {
    color: #64748B;
}

QLabel#statusValue {
    font-size: 18px;
    font-weight: 700;
}

QGroupBox {
    background-color: #FFFFFF;
    color: #334155;
    border: 1px solid #D5DBE5;
    border-radius: 7px;
    margin-top: 14px;
    padding: 12px 10px 8px 10px;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    background-color: #FFFFFF;
    color: #334155;
}

QPushButton {
    min-width: 88px;
    min-height: 30px;
    padding: 0 16px;
    background-color: #FFFFFF;
    color: #1F2937;
    border: 1px solid #C7CFDB;
    border-radius: 5px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #EAF2FF;
    color: #0F172A;
    border-color: #6AA0EA;
}

QPushButton:pressed {
    background-color: #DCEAFF;
    color: #0F172A;
}

QPushButton:disabled {
    background-color: #EEF0F3;
    color: #94A3B8;
    border-color: #D7DCE4;
}

QRadioButton,
QCheckBox {
    background-color: transparent;
    color: #1F2937;
    spacing: 7px;
}

QLineEdit,
QTextEdit,
QPlainTextEdit,
QComboBox,
QSpinBox,
QListWidget,
QTableWidget {
    background-color: #FFFFFF;
    color: #1F2937;
    selection-background-color: #DBEAFE;
    selection-color: #0F172A;
    border: 1px solid #CBD3DF;
    border-radius: 4px;
    padding: 4px;
}

QLineEdit:read-only,
QLineEdit:disabled,
QComboBox:disabled,
QSpinBox:disabled {
    background-color: #F1F5F9;
    color: #64748B;
}

QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    color: #1F2937;
    selection-background-color: #DBEAFE;
    selection-color: #0F172A;
    border: 1px solid #CBD3DF;
}

QHeaderView::section {
    background-color: #E9EEF5;
    color: #334155;
    border: 0;
    border-right: 1px solid #D5DBE5;
    border-bottom: 1px solid #D5DBE5;
    padding: 6px;
    font-weight: 600;
}

QTabWidget::pane {
    background-color: #FFFFFF;
    border: 1px solid #D5DBE5;
    border-radius: 0 5px 5px 5px;
}

QTabBar::tab {
    min-width: 105px;
    padding: 8px 16px;
    background-color: #E9EEF5;
    color: #334155;
    border: 1px solid #D5DBE5;
    border-bottom: 0;
}

QTabBar::tab:first {
    border-top-left-radius: 5px;
}

QTabBar::tab:last {
    border-top-right-radius: 5px;
}

QTabBar::tab:hover:!selected {
    background-color: #DDE6F1;
    color: #1F2937;
}

QTabBar::tab:selected {
    background-color: #2563EB;
    color: #FFFFFF;
    border-color: #2563EB;
    font-weight: 600;
}

QSplitter::handle {
    background-color: #D5DBE5;
}

QToolTip {
    background-color: #FFFFFF;
    color: #1F2937;
    border: 1px solid #94A3B8;
}
"""


class MainWindow(QMainWindow):
    def __init__(self, smoke_test: bool = False) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(980, 760)
        icon_path = RESOURCE_DIR / "assets" / "app-icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.service = WatcherService()
        self.service.log_message.connect(self.append_log)
        self.service.status_changed.connect(self.set_status)
        self.service.stream_changed.connect(self.set_stream_info)
        self.service.running_changed.connect(self.set_running)
        self.service.error_occurred.connect(self.show_error)

        self.config = load_config()
        self._build_ui()
        self._load_into_ui()
        self.history_refresh_timer = QTimer(self)
        self.history_refresh_timer.setInterval(15_000)
        self.history_refresh_timer.timeout.connect(self.refresh_watch_history)
        self.history_refresh_timer.start()
        self.refresh_watch_history()
        self.set_status("未启动")
        self.append_log("程序已启动；默认使用有窗口模式，登录请在真实浏览器中手动完成")

        if smoke_test:
            QTimer.singleShot(1200, QApplication.instance().quit)

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel(APP_NAME)
        title.setObjectName("appTitle")
        header.addWidget(title)
        header.addStretch()
        version = QLabel(f"v{APP_VERSION}")
        version.setObjectName("versionLabel")
        header.addWidget(version)
        layout.addLayout(header)

        status_group = QGroupBox("当前状态")
        status_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        status_layout = QGridLayout(status_group)
        status_layout.setContentsMargins(12, 8, 12, 8)
        status_layout.setHorizontalSpacing(12)
        status_layout.setVerticalSpacing(4)
        self.status_value = QLabel("未启动")
        self.status_value.setObjectName("statusValue")
        status_layout.addWidget(QLabel("状态"), 0, 0)
        status_layout.addWidget(self.status_value, 0, 1)
        self.title_value = QLabel("—")
        self.channel_value = QLabel("—")
        self.url_value = QLineEdit()
        self.url_value.setReadOnly(True)
        self.start_value = QLabel("—")
        status_layout.addWidget(QLabel("直播标题"), 1, 0)
        status_layout.addWidget(self.title_value, 1, 1)
        status_layout.addWidget(QLabel("频道"), 2, 0)
        status_layout.addWidget(self.channel_value, 2, 1)
        status_layout.addWidget(QLabel("直播 URL"), 3, 0)
        status_layout.addWidget(self.url_value, 3, 1)
        status_layout.addWidget(QLabel("开始时间"), 4, 0)
        status_layout.addWidget(self.start_value, 4, 1)
        status_layout.setColumnStretch(1, 1)
        layout.addWidget(status_group)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_watch_tab(), "观看")
        self.tabs.addTab(self._build_profiles_tab(), "Profiles")
        self.tabs.addTab(self._build_settings_tab(), "设置与频道")
        layout.addWidget(self.tabs, 1)

        buttons = QHBoxLayout()
        self.start_button = QPushButton("开始")
        self.stop_button = QPushButton("停止")
        self.browser_button = QPushButton("打开浏览器")
        self.check_button = QPushButton("检查直播")
        self.start_button.clicked.connect(self.start_watching)
        self.stop_button.clicked.connect(self.stop_watching)
        self.browser_button.clicked.connect(self.open_browser)
        self.check_button.clicked.connect(self.check_once)
        for button in (self.start_button, self.stop_button, self.browser_button, self.check_button):
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)

        log_group = QGroupBox("日志")
        log_layout = QVBoxLayout(log_group)
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.document().setMaximumBlockCount(1000)
        self.log_area.setMinimumHeight(150)
        log_layout.addWidget(self.log_area)
        layout.addWidget(log_group)

    def _build_watch_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        mode_group = QGroupBox("模式")
        mode_layout = QVBoxLayout(mode_group)
        row = QHBoxLayout()
        self.auto_radio = QRadioButton("自动检测官方直播")
        self.manual_radio = QRadioButton("手动指定直播 URL")
        self.auto_radio.setMinimumWidth(180)
        self.manual_radio.setMinimumWidth(190)
        row.setSpacing(28)
        row.addWidget(self.auto_radio)
        row.addWidget(self.manual_radio)
        row.addStretch()
        mode_layout.addLayout(row)
        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel("YouTube URL"))
        self.manual_url = QLineEdit()
        self.manual_url.setPlaceholderText("https://www.youtube.com/watch?v=xxxx")
        manual_row.addWidget(self.manual_url, 1)
        mode_layout.addLayout(manual_row)
        self.auto_radio.toggled.connect(self._update_mode_controls)
        layout.addWidget(mode_group)

        note = QLabel(
            "软件只负责寻找、打开并维持 YouTube 直播观看，不保证掉宝、奖励或观看时长一定被 Blizzard / YouTube 计入。\n"
            "最低画质：为避免依赖易变的 YouTube 菜单 DOM，本版不自动点击 144p；请首次观看时手动选择，YouTube 通常会记住偏好。"
        )
        note.setWordWrap(True)
        note.setObjectName("secondaryText")
        note.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(note)

        history_group = QGroupBox("近 7 天观看记录")
        history_layout = QVBoxLayout(history_group)
        summary_row = QHBoxLayout()
        self.today_total_label = QLabel("今日累计：00:00:00")
        self.week_total_label = QLabel("近 7 天累计：00:00:00")
        clear_history_button = QPushButton("清空记录")
        clear_history_button.clicked.connect(self.clear_watch_history)
        summary_row.addWidget(self.today_total_label)
        summary_row.addSpacing(24)
        summary_row.addWidget(self.week_total_label)
        summary_row.addStretch()
        summary_row.addWidget(clear_history_button)
        history_layout.addLayout(summary_row)

        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(["日期", "Profile", "直播标题", "频道", "实际观看时长"])
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setMinimumHeight(180)
        history_header = self.history_table.horizontalHeader()
        history_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        history_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        history_header.setSectionResizeMode(2, QHeaderView.Stretch)
        history_header.setSectionResizeMode(3, QHeaderView.Interactive)
        history_header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.history_table.setColumnWidth(3, 180)
        history_layout.addWidget(self.history_table, 1)
        layout.addWidget(history_group, 1)
        return page

    def _build_profiles_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.profile_list = QListWidget()
        self.profile_list.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.profile_list)
        row = QHBoxLayout()
        add_button = QPushButton("新增 Profile")
        delete_button = QPushButton("删除 Profile")
        login_button = QPushButton("打开登录窗口")
        add_button.clicked.connect(self.add_profile)
        delete_button.clicked.connect(self.delete_profile)
        login_button.clicked.connect(self.open_browser)
        row.addWidget(add_button)
        row.addWidget(delete_button)
        row.addWidget(login_button)
        row.addStretch()
        layout.addLayout(row)
        hint = QLabel("每个 Profile 对应 profiles/ 下一个独立目录。首次请用有窗口模式手动登录 Google / YouTube。")
        hint.setWordWrap(True)
        hint.setObjectName("secondaryText")
        layout.addWidget(hint)
        return page

    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        splitter = QSplitter(Qt.Vertical)
        page_layout = QVBoxLayout(page)
        page_layout.addWidget(splitter)

        settings = QWidget()
        settings.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        form = QFormLayout(settings)
        self.browser_combo = QComboBox()
        self.browser_combo.addItem("Google Chrome", "chrome")
        self.browser_combo.addItem("Brave", "brave")
        browser_path_row = QHBoxLayout()
        self.browser_path = QLineEdit()
        self.browser_path.setPlaceholderText("留空则自动检测")
        choose_button = QPushButton("选择 exe")
        choose_button.clicked.connect(self.choose_browser)
        browser_path_row.addWidget(self.browser_path, 1)
        browser_path_row.addWidget(choose_button)
        self.headless_check = QCheckBox("启用无头模式（登录前不要开启）")
        self.mute_check = QCheckBox("自动静音")
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(180, 3600)
        self.interval_spin.setSuffix(" 秒")
        form.addRow("浏览器", self.browser_combo)
        form.addRow("浏览器路径", browser_path_row)
        form.addRow("窗口", self.headless_check)
        form.addRow("声音", self.mute_check)
        form.addRow("检查周期", self.interval_spin)
        splitter.addWidget(settings)

        channels = QWidget()
        channels.setMinimumHeight(260)
        channels.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        channels_layout = QVBoxLayout(channels)
        channels_layout.addWidget(QLabel("自动检测频道（勾选启用）"))
        self.channel_table = QTableWidget(0, 3)
        self.channel_table.setHorizontalHeaderLabels(["启用", "名称", "频道 ID 或 URL"])
        self.channel_table.setMinimumHeight(220)
        self.channel_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        channel_header = self.channel_table.horizontalHeader()
        channel_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        channel_header.setSectionResizeMode(1, QHeaderView.Interactive)
        channel_header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.channel_table.setColumnWidth(1, 200)
        self.channel_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        channels_layout.addWidget(self.channel_table, 1)
        channel_buttons = QHBoxLayout()
        add_channel = QPushButton("增加频道")
        remove_channel = QPushButton("删除频道")
        add_channel.clicked.connect(self.add_channel)
        remove_channel.clicked.connect(self.remove_channel)
        channel_buttons.addWidget(add_channel)
        channel_buttons.addWidget(remove_channel)
        channel_buttons.addStretch()
        channels_layout.addLayout(channel_buttons)
        splitter.addWidget(channels)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([190, 360])
        return page

    def _load_into_ui(self) -> None:
        mode = self.config.get("mode", "auto")
        self.auto_radio.setChecked(mode == "auto")
        self.manual_radio.setChecked(mode == "manual")
        self.manual_url.setText(str(self.config.get("manual_url", "")))
        index = self.browser_combo.findData(self.config.get("browser", "chrome"))
        self.browser_combo.setCurrentIndex(max(index, 0))
        self.browser_path.setText(str(self.config.get("browser_path", "")))
        self.headless_check.setChecked(bool(self.config.get("headless", False)))
        self.mute_check.setChecked(bool(self.config.get("mute", True)))
        self.interval_spin.setValue(int(self.config.get("check_interval", 300)))
        self.profile_list.addItems(self.config.get("profiles", ["主账号"]))
        if self.profile_list.count():
            self.profile_list.setCurrentRow(0)
        self.channel_table.setRowCount(0)
        for channel in self.config.get("channels", []):
            self._append_channel_row(channel)
        self._update_mode_controls()

    def _append_channel_row(self, channel: dict[str, Any]) -> None:
        row = self.channel_table.rowCount()
        self.channel_table.insertRow(row)
        enabled = QTableWidgetItem()
        enabled.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
        enabled.setCheckState(Qt.Checked if channel.get("enabled", True) else Qt.Unchecked)
        name = QTableWidgetItem(str(channel.get("name", "")))
        value = QTableWidgetItem(str(channel.get("url") or channel.get("id") or ""))
        self.channel_table.setItem(row, 0, enabled)
        self.channel_table.setItem(row, 1, name)
        self.channel_table.setItem(row, 2, value)

    def _update_mode_controls(self) -> None:
        self.manual_url.setEnabled(self.manual_radio.isChecked())

    def _collect_config(self) -> dict[str, Any]:
        channels = []
        for row in range(self.channel_table.rowCount()):
            enabled_item = self.channel_table.item(row, 0)
            name_item = self.channel_table.item(row, 1)
            value_item = self.channel_table.item(row, 2)
            name = name_item.text().strip() if name_item else ""
            value = value_item.text().strip() if value_item else ""
            if not value:
                continue
            if value.startswith(("http://", "https://")):
                channel_id, url = "", value
            else:
                channel_id, url = value, f"https://www.youtube.com/channel/{value}/live"
            channels.append({
                "name": name or channel_id or url,
                "id": channel_id,
                "url": url,
                "enabled": bool(enabled_item and enabled_item.checkState() == Qt.Checked),
            })
        profiles = [self.profile_list.item(i).text() for i in range(self.profile_list.count())]
        return {
            "browser": self.browser_combo.currentData(),
            "browser_path": self.browser_path.text().strip(),
            "headless": self.headless_check.isChecked(),
            "mute": self.mute_check.isChecked(),
            "mode": "auto" if self.auto_radio.isChecked() else "manual",
            "manual_url": self.manual_url.text().strip(),
            "check_interval": self.interval_spin.value(),
            "channels": channels,
            "profiles": profiles,
        }

    def _save_from_ui(self) -> dict[str, Any] | None:
        try:
            self.config = self._collect_config()
            save_config(self.config)
            return self.config
        except Exception as exc:
            self.show_error(f"保存配置失败：{exc}")
            return None

    def start_watching(self) -> None:
        config = self._save_from_ui()
        if config:
            self.service.start(config)

    def stop_watching(self) -> None:
        self.service.stop(close_browsers=True)

    def check_once(self) -> None:
        config = self._save_from_ui()
        if config:
            self.service.check_once(config)

    def selected_profile(self) -> str:
        item = self.profile_list.currentItem()
        return item.text() if item else (self.profile_list.item(0).text() if self.profile_list.count() else "主账号")

    def open_browser(self) -> None:
        config = self._save_from_ui()
        if not config:
            return
        if config.get("headless"):
            answer = QMessageBox.question(
                self,
                "无头模式",
                "当前启用了无头模式，看不到登录窗口。是否临时使用有窗口模式打开？",
            )
            if answer != QMessageBox.Yes:
                return
            config["headless"] = False
        self.service.open_login(config, self.selected_profile())

    def add_profile(self) -> None:
        name, accepted = QInputDialog.getText(self, "新增 Profile", "Profile 名称：")
        if not accepted:
            return
        valid, result = validate_profile_name(name)
        if not valid:
            self.show_error(result)
            return
        existing = {self.profile_list.item(i).text() for i in range(self.profile_list.count())}
        if result in existing:
            self.show_error("该 Profile 已存在")
            return
        profile_path(result).mkdir(parents=True, exist_ok=True)
        self.profile_list.addItem(result)
        self.profile_list.setCurrentRow(self.profile_list.count() - 1)
        self._save_from_ui()
        self.append_log(f"已新增 Profile“{result}”")

    def delete_profile(self) -> None:
        item = self.profile_list.currentItem()
        if not item:
            return
        if self.profile_list.count() <= 1:
            self.show_error("至少保留一个 Profile")
            return
        name = item.text()
        answer = QMessageBox.warning(
            self,
            "删除 Profile",
            f"将删除 Profile“{name}”及其本地浏览器登录数据。此操作无法由软件恢复。是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        path = profile_path(name)
        if path.exists():
            shutil.rmtree(path)
        self.profile_list.takeItem(self.profile_list.row(item))
        self.profile_list.setCurrentRow(0)
        self._save_from_ui()
        self.append_log(f"已删除 Profile“{name}”及其本地数据")

    def choose_browser(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 Chrome 或 Brave", "", "浏览器程序 (*.exe)")
        if path:
            self.browser_path.setText(str(Path(path)))

    def add_channel(self) -> None:
        name, accepted = QInputDialog.getText(self, "增加频道", "频道名称：")
        if not accepted:
            return
        value, accepted = QInputDialog.getText(self, "增加频道", "YouTube 频道 ID 或频道 URL：")
        if not accepted or not value.strip():
            return
        self._append_channel_row({"name": name.strip() or value.strip(), "url": value.strip(), "enabled": True})
        self._save_from_ui()

    def remove_channel(self) -> None:
        rows = sorted({item.row() for item in self.channel_table.selectedItems()}, reverse=True)
        for row in rows:
            self.channel_table.removeRow(row)
        if rows:
            self._save_from_ui()

    def refresh_watch_history(self) -> None:
        snapshot = self.service.history_snapshot()
        self.today_total_label.setText(f"今日累计：{format_duration(snapshot.get('today_total', 0.0))}")
        self.week_total_label.setText(f"近 7 天累计：{format_duration(snapshot.get('week_total', 0.0))}")
        rows = list(snapshot.get("rows", []))
        self.history_table.setUpdatesEnabled(False)
        try:
            self.history_table.setRowCount(len(rows))
            for row_index, record in enumerate(rows):
                title = str(record.get("title", ""))
                values = [
                    str(record.get("date", "")),
                    str(record.get("profile", "")),
                    title,
                    str(record.get("channel", "")),
                    format_duration(float(record.get("watch_seconds", 0.0))),
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    if column == 2:
                        item.setToolTip(title)
                    if column == 4:
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.history_table.setItem(row_index, column, item)
        finally:
            self.history_table.setUpdatesEnabled(True)

    def clear_watch_history(self) -> None:
        answer = QMessageBox.question(
            self,
            "清空观看记录",
            "确定要清空所有观看时长记录吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.service.clear_history()
        self.refresh_watch_history()
        self.append_log("观看时长记录已清空")

    def set_status(self, status: str) -> None:
        self.status_value.setText(status)
        self.status_value.setStyleSheet(
            f"font-size: 18px; font-weight: 700; color: {STATUS_COLORS.get(status, '#334155')};"
        )

    def set_stream_info(self, info: object) -> None:
        value = info if isinstance(info, dict) else {}
        self.title_value.setText(str(value.get("title") or "—"))
        self.channel_value.setText(str(value.get("channel") or "—"))
        self.url_value.setText(str(value.get("url") or ""))
        self.start_value.setText(str(value.get("start_time") or "—"))

    def set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)

    def append_log(self, message: str) -> None:
        self.log_area.append(message)

    def show_error(self, message: str) -> None:
        QMessageBox.critical(self, "错误", message)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_from_ui()
        self.service.stop(close_browsers=True)
        event.accept()
