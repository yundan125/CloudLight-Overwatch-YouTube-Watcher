# CloudLight Overwatch YouTube Watcher

一个面向 Windows 的本地桌面工具：定期检查指定的守望先锋官方 YouTube 频道，发现直播后使用用户自己的 Chrome / Brave 独立 Profile 打开直播，并在运行期间检查浏览器和视频页面、尝试恢复意外暂停。

> 本项目最初基于 [**ucarno/ow-league-tokens**](https://github.com/ucarno/ow-league-tokens) 开发，并在此基础上进行了较大幅度的重构与扩展；感谢原作者 **ucarno** 及贡献者公开源代码和早期实现。

> 本软件只负责自动打开并维持 YouTube 直播观看，不保证任何具体掉宝、奖励或观看时长一定被 Blizzard / YouTube 计入。

## 🙏 特别鸣谢

本项目最初直接以 [**ucarno/ow-league-tokens**](https://github.com/ucarno/ow-league-tokens) 作为开发底座。

原项目为 Overwatch YouTube 自动观赛提供了重要的早期设计和实现基础，包括自动寻找直播、使用浏览器持续观看、独立浏览器 Profile、多账号 / 多 Profile、Chrome / Brave 支持、自动静音、Headless 模式、定时检查直播状态，以及直播结束后继续等待下一场直播等思路。

当前 CloudLight 版本在此基础上针对现在的 YouTube、Chrome 和 Overwatch 赛事 / 直播环境进行了较大幅度的重构：从 OWL / League Token 定位迁移为通用 Overwatch YouTube Watcher，移除了旧 OWL Schedule、`hqdefault_live.jpg` 检测和 Selenium / undetected-chromedriver 主控制链路，改用真实 Chrome / Brave 持久化 Profile，并增加 PySide6 中文 GUI、新的直播发现方式、手动直播 URL、多频道管理、播放状态监控与恢复、实际观看时长统计、近 7 天观看历史，以及 Windows 安装包等功能。

感谢原作者 **ucarno** 及原项目贡献者公开源代码，使本项目能够在其基础上继续演进。

原项目：**[ucarno/ow-league-tokens](https://github.com/ucarno/ow-league-tokens)**

## 当前功能

- 简体中文 Windows GUI，显示检测/观看状态、标题、频道、URL、开始时间和日志。
- 自动检测模式：检查所有已启用频道，只在元数据明确为正在直播时打开。
- 手动 URL 模式：直接粘贴 `youtube.com/watch` 或 `youtu.be` 地址，自动检测失效时仍可使用。
- Chrome / Brave 自动检测，也可手动选择浏览器 `.exe`。
- 每个 Profile 使用软件目录下独立的 `profiles/<名称>/`，Cookie 和 Google / YouTube 登录状态由浏览器原生保存。
- 可同时为多个 Profile 启动独立浏览器实例；第一版仍建议先用单账号验证。
- 默认显示浏览器窗口、默认静音；可选 Chromium 新无头模式。
- 3～60 分钟检查周期（默认 300 秒）。浏览器退出后自动重新打开；直播连续两轮离线后回到等待。
- 通过本机 `127.0.0.1` DevTools 检查直播标签页和 `<video>` 状态，尝试恢复意外暂停；没有 Selenium / ChromeDriver。
- 日志写入 `logs/watcher.log`，单文件约 1 MB，保留 3 个轮转备份。

## 目录与数据

```text
CloudLight Overwatch YouTube Watcher/
├─ CloudLight Overwatch YouTube Watcher.exe
├─ config.json
├─ profiles/
├─ logs/
└─ _internal/                 # PyInstaller 运行文件
```

配置和登录 Profile 均在软件目录，不写入 Documents 或 AppData。不要让两个程序实例同时使用同一个 Profile。

默认配置：

```json
{
  "browser": "chrome",
  "browser_path": "",
  "headless": false,
  "mute": true,
  "mode": "auto",
  "manual_url": "",
  "check_interval": 300,
  "channels": [],
  "profiles": ["主账号"]
}
```

实际随包的 `channels` 默认包含 Overwatch Esports 主频道，并额外提供一个默认关闭的 Overwatch Contenders 频道。也可以在 GUI 中增加频道 ID 或频道 URL。

## 直接运行

要求 Windows 10/11 x64，以及已安装并更新的 Google Chrome 或 Brave。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple -r requirements.txt
.\.venv\Scripts\python.exe .\src\main.py
```

## 首次 Google / YouTube 登录

1. 保持“无头模式”关闭。
2. 在 **Profiles** 页选择 `主账号`，点击“打开登录窗口”。
3. 在打开的真实 Chrome / Brave 窗口内自行登录 Google；软件不会读取或自动填写密码。
4. 打开 YouTube 确认头像/账号正确，然后正常关闭浏览器。
5. 再次点击“打开登录窗口”，确认登录仍然保留。
6. 如当前活动要求连接 Battle.net 与 YouTube，按 Blizzard / YouTube 当前活动页面的说明由用户自行完成连接。

Chrome/Brave 的 Cookie、Local Storage 等会保存在 `profiles/主账号/`。删除 Profile 会同时删除这份本地登录数据。

Google 可能随时要求重新验证账号。本软件只能在直播标签页被重定向到 `accounts.google.com` 时提示“登录失效”，不能替代人工确认账号头像或奖励连接状态。

## 自动模式与手动模式

自动模式依次访问频道 `/live` 地址，通过最新版 `yt-dlp` 读取公开元数据。只有 `is_live=true` 或 `live_status=is_live` 才视为直播；`is_upcoming`（预约）和 `was_live`（回放）不会自动打开。若 yt-dlp 因 YouTube 改版失败，再尝试从公开页面中读取明确的 `isLiveNow=true` 标记；两种方法都不需要 YouTube API Key。

手动模式不判断活动资格，也允许打开普通 YouTube 视频。粘贴 URL 后点击“开始观看”；程序会打开并监控浏览器。自动检测发生未来兼容性问题时，这是稳定的降级入口。

## Headless 与画质

Headless 默认关闭。它适合已经成功登录并确认播放稳定的 Profile；Google 登录、验证码和账号重新验证必须回到有窗口模式完成。

本版不自动设置 144p，因为不同语言、A/B 测试和 YouTube DOM 更新会让菜单点击非常不稳定。建议第一次观看时手动选择最低画质，浏览器通常会在该 Profile 中保存偏好。

## Windows 打包

构建必须在 Windows x64 上执行：

```powershell
python -m venv .venv
.\build.ps1
```

脚本只清理本项目 `dist/CloudLight Overwatch YouTube Watcher` 和同名 ZIP，然后安装 `requirements-dev.txt`、运行 PyInstaller、复制默认配置并创建空的 `profiles/`、`logs/`。

输出：

```text
dist/CloudLight Overwatch YouTube Watcher/CloudLight Overwatch YouTube Watcher.exe
dist/CloudLight-Overwatch-YouTube-Watcher.zip
```

## 第三方开源组件

- [yt-dlp](https://github.com/yt-dlp/yt-dlp)：读取 YouTube 公开直播元数据。
- [PySide6 / Qt for Python](https://doc.qt.io/qtforpython-6/)：构建桌面 GUI。
- [Requests](https://requests.readthedocs.io/)：发送 HTTP 请求。
- [websocket-client](https://github.com/websocket-client/websocket-client)：连接 Chrome / Brave DevTools WebSocket。
- [PyInstaller](https://pyinstaller.org/)：构建 Windows 可执行程序。
- [Inno Setup](https://jrsoftware.org/isinfo.php)：生成 Windows 安装包。

更完整的项目来源与第三方说明见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。各组件分别适用其官方项目公布的许可证条款。

## 已知限制

- YouTube 的公开页面和内部播放器会继续变化；因此保留了手动 URL 模式，但自动检测仍可能需要后续升级 `yt-dlp`。
- 软件不能证明 YouTube/Blizzard 已把当前播放计入活动时长，也无法读取游戏奖励后台。
- 视频播放恢复是尽力而为：网络断开、地区限制、年龄确认、Cookie 弹窗或验证码仍需要人工处理。
- 无头播放是否被当前活动认可由活动规则决定；优先使用可见窗口。
- 多 Profile 会成倍增加内存和带宽占用。
- 打包程序没有代码签名，Windows SmartScreen 可能显示“未知发布者”。

## 手动验证当前掉宝活动

1. 在 Blizzard 官方的当期 OWCS / 守望先锋观赛指南中确认：活动时间、合资格直播平台/频道、地区、奖励档位和账号连接要求。
2. 在有窗口模式打开登录 Profile，确认 YouTube 头像账号正确；按活动说明确认 Battle.net 连接状态。
3. 在活动开始后先手动观看 10～15 分钟，确认直播没有显示地区/年龄/同意 Cookie 等阻塞页面。
4. 在 GUI 查看“正在观看”，并在浏览器中确认时间轴持续推进、没有暂停。
5. 到活动规则规定的同步等待时间后，在游戏内或 Blizzard 指定的奖励/连接页面检查进度；以官方页面为准。
6. 如果没有进度，先改用有窗口、非静音不是必要条件但可临时关闭静音、关闭其他同账号直播，并人工观看验证。不要仅凭本软件日志判断奖励已计入。

## 声明

本项目与 Blizzard Entertainment、Google 或 YouTube 无隶属或背书关系。Overwatch、Battle.net、YouTube、Chrome、Brave 等名称和商标归各自权利人所有。
