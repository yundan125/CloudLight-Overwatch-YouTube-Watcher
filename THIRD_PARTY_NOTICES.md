# Third-Party Notices

本文件记录 CloudLight Overwatch YouTube Watcher 的项目来源及主要第三方组件。各第三方项目的名称、源代码和许可证归其各自权利人所有。

## ucarno/ow-league-tokens

- 原项目：[ucarno/ow-league-tokens](https://github.com/ucarno/ow-league-tokens)
- 原作者：**ucarno**

CloudLight Overwatch YouTube Watcher was originally derived from / based on ucarno/ow-league-tokens and has since undergone substantial modification.

原项目为自动寻找 Overwatch YouTube 直播、使用浏览器持续观看、独立浏览器 Profile、多账号 / 多 Profile、Chrome / Brave 支持、自动静音、Headless 模式、定时检查及持续等待下一场直播等功能和设计提供了重要的早期基础。当前 CloudLight 版本在此基础上重新设计了直播发现、浏览器控制和桌面界面等主要实现，并增加了多频道管理、手动直播 URL、播放恢复、观看时长统计及 Windows 安装包等功能。

截至 2026-08-20，上游仓库没有 `LICENSE` 文件，GitHub 也未识别到已声明的许可证。因此，本文件仅记录项目来源和 attribution，不授予或暗示对上游代码的任何许可证；公开分发衍生版本前，维护者仍应与上游权利人确认适用的授权范围。

## 运行时组件

- [yt-dlp](https://github.com/yt-dlp/yt-dlp)：读取 YouTube 公开直播元数据。
- [PySide6 / Qt for Python](https://doc.qt.io/qtforpython-6/)：桌面 GUI 与 Qt 运行时。
- [Requests](https://requests.readthedocs.io/)：HTTP 客户端。
- [websocket-client](https://github.com/websocket-client/websocket-client)：Chrome / Brave DevTools WebSocket 客户端。

## 构建与安装工具

- [PyInstaller](https://pyinstaller.org/)：构建 Windows 可执行程序及随附运行文件。
- [Inno Setup](https://jrsoftware.org/isinfo.php)：生成 Windows 安装包。

以上组件分别适用其官方项目公布的许可证条款。本文件不替代各组件随附或官方发布的许可证文本。
