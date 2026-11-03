# GitHub 首次公开发布 · 2026-11-03

## 修改概述

按用户授权，准备将当前 v0.2.1 源码和便携包公开发布至 `https://github.com/PowerT-0704/window-quiz-helper`。README 新增薄荷图标、下载导航、功能对照、浅深色与设置预览；图片均来自自有模拟窗口。程序功能、超时设置和密钥处理保持原样，软件内 v0.2.1 功能公告沿用已有内容。

## 文件清单

新增：`.gitattributes`、`docs/images/README.md`、`docs/images/app-icon.png`、`docs/images/home-light.png`、`docs/images/home-dark.png`、`docs/images/settings.png`。

修改：`README.md`、`ROADMAP.md`、`CHANGELOG.md`、`DELIVERY.md`、`scripts/package_source.py`、`scripts/build.ps1`。无删除文件。生成的 Git 元数据和发布 ZIP 不属于程序源码。

## 检查与结果

进行中：标准库回归、文档本地链接、源码白名单／敏感信息检查、便携包一致性、GitHub 推送及 Release 资产校验。完成后将以实际结果更新。

## 剩余风险

真实 DeepSeek、用户手机投屏软件、Windows 10 和混合 DPI 仍待对应环境验收。项目尚未指定统一开源许可证，本轮不擅自替用户授予；第三方许可随包保留。Git 与 Release 不上传运行数据、密钥、日志或真实截图。

---

# 历史交付：v0.2.1

日期：2026-11-02。修复用户反馈的吸附悬浮窗“消失”。

## 本轮修改

已用自有置顶窗口复现：目标重新置顶后，悬浮窗被覆盖，但 Qt 仍报告可见，旧逻辑不恢复层级。现仅对本软件悬浮窗使用不激活的原生显示／层级恢复；不抢焦点、不操作目标窗口。增加主页“显示悬浮窗”、屏幕外位置恢复及无效 DWM 边界回退。

## 本轮文件清单

新增：`tests/test_overlay.py`、`scripts/overlay_smoke.py`。

修改：`quiz_helper/__init__.py`、`quiz_helper/win32.py`、`quiz_helper/docking.py`、`quiz_helper/ui.py`、`quiz_helper/app.py`、`quiz_helper/releases.py`、`README.md`、`ROADMAP.md`、`CHANGELOG.md`、`DELIVERY.md`。无删除文件，未改动实际运行配置、真实 API Key 或用户截图。

## 本轮检查

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -m compileall -q main.py quiz_helper scripts tests
# 以下使用普通 Windows Qt 平台，仅创建自有测试窗口：
.\.venv\Scripts\python.exe -u scripts\overlay_smoke.py
.\.venv\Scripts\python.exe -u scripts\ui_smoke.py --output .qa\v021
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build.ps1
```

70 项自动检查，69 项通过、1 项权限跳过，测试窗口清理后连续三次检查退出 0。原生置顶目标覆盖后找回、隐藏／最小化找回和前台焦点保持均通过；框选异常后跟随暂停能够正确解除。原有 WGC、本地模拟查询、快捷键、预览和取消流程通过。

v0.2.1 便携构建成功。解压到非 C 盘测试目录，清除 Python／Qt 开发环境变量，PATH 仅保留 Windows System32，冻结 EXE `--diagnose` 退出 0；版本、图标、PNG、DPAPI、应用／捕获模块和 Schannel TLS 均通过。源码包 46 个文件与工作区一致；发布包无运行数据、真实凭据或截图。旧版本产物保留。

## 本轮风险

用户实际手机投屏软件、Windows 10 和混合 DPI 仍待对应设备确认。关闭“悬浮窗置顶”时保留普通窗口层级；目标最小化时仍暂停和隐藏。未使用真实 API、未读取真实密钥，不改变目标窗口状态，不上传 GitHub。

---

# 历史交付：v0.2.0

日期：2026-11-02。本轮完成界面美化、图标、快捷搜题和目标窗口吸附，不新增第三方依赖。

## 本轮修改概述

- 多尺寸薄荷绿 ICO、Qt 图标及稳定 AppUserModelID；奶白、薄荷绿、浅蓝与深色主题。
- 完整窗口高亮选区、题区放大／缩小／原始比例／适应，以及按需刷新。
- 目标窗口右下角吸附、拖开与恢复吸附；最小化时隐藏，恢复后跟随。
- 可配置全局 Ctrl＋Alt＋Q 搜题，冲突回滚、按住不连发；查询按钮和快捷键共用入口。
- 取消当前查询保留目标和选区，拒绝迟到结果。
- 移除客户端单题 Token 限制与参数，兼容旧设置；请求超时保持原值，默认 60 秒。

## 本轮文件变动

根目录为 `D:\桌面\区域提交求答案`。新增：

```text
quiz_helper/branding.py
quiz_helper/docking.py
quiz_helper/hotkeys.py
quiz_helper/preview.py
quiz_helper/assets/app.ico
tests/test_v020.py
```

修改：

```text
main.py
quiz_helper/__init__.py
quiz_helper/ai.py
quiz_helper/app.py
quiz_helper/controller.py
quiz_helper/models.py
quiz_helper/storage.py
quiz_helper/ui.py
quiz_helper/theme.py
quiz_helper/releases.py
tests/test_core.py
tests/test_controller.py
scripts/build.ps1
scripts/package_source.py
scripts/ui_smoke.py
scripts/capture_smoke.py
README.md
ROADMAP.md
CHANGELOG.md
DELIVERY.md
```

无删除文件。真实凭据、现有运行配置与用户截图未作迁移或修改；迁移逻辑仅在软件读取旧设置时兼容忽略旧 Token 字段，保存时移除。

## 本轮检查与结果

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -m compileall -q main.py quiz_helper scripts tests
# 在普通 Windows Qt 平台运行真实自有窗口测试：
.\.venv\Scripts\python.exe -u scripts\ui_smoke.py --output .qa\v020
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build.ps1
```

- 64 项自动测试，63 项通过，1 项符号链接测试因权限跳过。
- 编译检查通过；窗口原生图标句柄、全局快捷键注册与 Windows 热键消息通路通过。
- 实际 WGC → 本地模拟接口 → 主界面与悬浮答案通过；刷新不调用 AI、缓存、强制查询、解析、窗口移动与缩放、暂停恢复、取消和停止均通过。
- 奶白浅色、深色及预览缩放已渲染检查。图标包含 16、24、32、48、64、128、256 像素层。
- v0.2.0 目录式构建成功。便携包解压到非 C 盘目录，移除 Python／Qt 开发环境变量、PATH 仅保留 Windows System32 后，`--diagnose` 退出码 0，版本为 0.2.0；应用图标、窗口捕获模块、PNG、DPAPI 和 Schannel TLS 通过。
- PE 内嵌 7 档图标资源，运行时 ICO 同步入包。源码包 44 个文件与工作区逐项一致，发布包无运行数据、真实 Key、截图或开发环境。旧 v0.1.0 产物保留。
- 新产物：`dist/题目查询助手-portable-v0.2.0.zip`、`dist/题目查询助手-source-v0.2.0.zip`。

## 本轮剩余风险

- 移除客户端 Token 参数后，服务商仍有默认生成与服务时间限制；原请求超时继续生效。
- 真实 DeepSeek API、Windows 10、混合 DPI 多屏、旧任务栏固定项目缓存仍待对应环境验收。
- 混合 DPI 使用 Windows 物理显示器原点与 Qt 比例换算；已覆盖几何边界测试，不能以此替代多设备实测。
- 沿用当前用户 DPAPI、不保存答题历史、不注入、不读取目标内存、不模拟鼠标点击。不上传 GitHub。

---

# 历史交付：v0.1.0

日期：2026-11-02。交付类型：Windows 64 位预览版、源码与开发路线。

## 1. 修改概述

已实现三页中文界面、浅色与深色主题、单题框选、遮挡窗口捕获、悬浮查询和答案、单选／多选／判断校验、可选简短解析、自定义兼容接口、DPAPI 密钥保存、非 C 盘截图与清理、最近一次结果缓存和强制重查。首版不模拟鼠标、不保存答题历史。最小化时暂停并使未完成任务失效，恢复后重新取图。

静态窗口未输出首帧时，在等待 250 毫秒后向所选窗口发送一次异步重绘请求，不改变目标位置、尺寸、焦点或最小化状态。没有 DLL 注入、目标内存读取或桌面截图回退。

## 2. 文件变动清单

项目根目录：`D:\桌面\区域提交求答案`。以下为新增的源码、测试、脚本与文档文件；无删除文件。此清单中的路径均相对此根目录，便于 GitHub 查看。

```text
.gitignore
main.py
requirements.txt
requirements-build.txt
README.md
ROADMAP.md
CHANGELOG.md
DELIVERY.md
THIRD_PARTY_NOTICES.md
quiz_helper/__init__.py
quiz_helper/ai.py
quiz_helper/app.py
quiz_helper/capture.py
quiz_helper/controller.py
quiz_helper/models.py
quiz_helper/releases.py
quiz_helper/storage.py
quiz_helper/theme.py
quiz_helper/ui.py
quiz_helper/win32.py
tests/__init__.py
tests/test_ai.py
tests/test_capture.py
tests/test_controller.py
tests/test_core.py
tests/test_ui.py
scripts/build.ps1
scripts/hooks/hook-PySide6.QtGui.py
scripts/capture_smoke.py
scripts/package_source.py
scripts/run.ps1
scripts/ui_smoke.py
LICENSES/README.md
LICENSES/FFmpeg-9.0.1-ATTRIBUTION.html
LICENSES/GPL-2.0-only.txt
LICENSES/GPL-3.0-only.txt
LICENSES/LGPL-2.1-or-later.txt
LICENSES/LGPL-3.0-only.txt
```

`.venv`、`.cache`、`.qa`、`data` 与 `dist` 是本地开发、检查或构建产物，已排除 Git；源码 ZIP 按白名单打包，不包含运行数据、截图或凭据。没有读取或修改已有 `.env`、用户密钥和证书。

## 3. 测试与检查命令

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q main.py quiz_helper scripts tests
.\.venv\Scripts\python.exe -u scripts\capture_smoke.py --output .qa\capture-occluded.png
.\.venv\Scripts\python.exe -u scripts\capture_smoke.py --fixture-type chromium --output .qa\capture-chromium.png
.\.venv\Scripts\python.exe -u scripts\ui_smoke.py
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1
```

接口测试仅使用本地 HTTP 模拟服务与虚构 Key。凭据测试实际经过当前 Windows 用户的 DPAPI 加解密。界面测试使用独立合成窗口，没有向真实 AI 发送用户窗口图片。

## 4. 检查结果

- 标准库自动测试：51 项，50 项通过；一项符号链接测试因 Windows 权限不足跳过。
- 普通 Qt 与 Chromium 静态窗口：完全遮挡捕获、最小化拒绝、恢复新帧及关闭拒绝均实测通过。
- 整体流程：实际 WGC 捕获 → 本地模拟 API → 主页和悬浮答案，通过。
- 重复图片缓存、强制重查、解析、最小化暂停与恢复、停止后迟到答案抑制，通过。
- 源码编译检查通过。浅色／深色、三个页面、设置三个标签与悬浮窗已渲染检查。
- 目录式 PyInstaller 构建完成，包含独立 Python／Qt DLL、FFmpeg 插件和许可证；不包含 WebEngine／PDF 二进制。
- 构建隔离外部工具 PATH，避免第三方图像工具的同名 ICU／API-set DLL 被错误收集；只在构建进程内生效，结束后还原。
- 便携 EXE 解压到 D 盘中文目录，移除 PYTHONHOME／PYTHONPATH／VIRTUAL_ENV 并将 PATH 限定为 Windows System32，`--diagnose` 退出码 0、`ok: true`。应用与窗口捕获模块、PNG、DPAPI 和 Schannel TLS 后端通过，未依赖已安装 Python 的 PATH。
- 桌面自动化因用户按 Escape 已停止，后续未继续进行桌面点击。便携 EXE 以 `--diagnose` 离屏检查，实时捕获待交互验收。

## 5. 剩余风险与待验收

- 真实 DeepSeek 图片查询尚未调用，需要用户在本地设置页输入 Key 后验收；连接测试成功不等于图片理解能力或答题正确率已验证。
- Windows 10、不同操作系统缩放比例及混合 DPI 多屏尚未实机验收。受保护窗口、特殊渲染和部分游戏不保证捕获成功。
- JSON 校验确保格式符合约定，无法证明 AI 答案事实正确。模型负载、网络、思考预算会影响耗时。
- DPAPI 保护静态凭据，无法防御已经控制同一登录账户的程序。任务图片为临时明文，默认完成后十分钟清理。
- 取消或超时仅停止本地等待，远端可能已经处理并计费；软件不自动重试。
- PySide6 便携包包含 Python、Qt 和窗口捕获运行组件，其体积高于原生 C 界面。后续优先根据实测缩减组件，而非重写整个应用。

尚未创建 GitHub 仓库、上传源码或推送任何内容。后续版本状态见 ROADMAP.md；每轮交付同步维护 README、路线、变更日志与软件内公告。
