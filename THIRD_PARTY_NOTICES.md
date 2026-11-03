# 第三方组件说明

本软件使用 Python、Qt for Python（PySide6／Shiboken6）和其运行组件；使用 PyInstaller 生成目录式可执行程序。应用源码本轮尚未选定整体开源许可证，第三方软件的版权和许可保持有效。

| 组件 | 使用方式 | 上游许可与来源 |
|---|---|---|
| Python 3.14 | 随便携包附带解释器和标准库 | PSF License 及 Python 发行版附带的其他许可；[Python 许可](https://docs.python.org/3/license.html) |
| PySide6／Shiboken6 6.12.0 | Python 到 Qt 的绑定，动态加载 | 安装包元数据列出 LGPL-3.0-only／GPL-2.0-only／GPL-3.0-only 选项；[Qt for Python 许可](https://doc.qt.io/qtforpython-6/licenses.html) |
| Qt Core／Gui／Widgets／Network／Multimedia 及实际依赖 | 界面、异步网络与窗口捕获，动态 DLL | 各模块许可及其第三方组件声明；[Qt 许可](https://doc.qt.io/qt-6/licensing.html)、[第三方代码](https://doc.qt.io/qt-6/licenses-used-in-qt.html) |
| FFmpeg | QtMultimedia 随包插件及运行库 | 具体配置适用 LGPL／GPL 许可，保留 Qt 发布物的组件声明；[FFmpeg 法律与许可](https://ffmpeg.org/legal.html)、[Qt FFmpeg 组件](https://doc.qt.io/qt-6/qtmultimedia-attribution-ffmpeg.html) |
| PyInstaller 6.22.3 | 构建工具及可执行程序 bootloader | GPL-2.0-or-later，包含 bootloader 分发例外；[PyInstaller 许可](https://pyinstaller.org/en/stable/license.html) |

发布构建将本目录 `LICENSES` 中的上游标准许可文本，以及安装环境实际附带的 Python、PySide6、Shiboken6 和 PyInstaller 许可文件复制到便携目录 `LICENSES`。部分 PySide6 wheel 的 `licenses` 目录只附 Qt 商业参考文本；该文件的存在不意味着本软件拥有商业许可证，也不改变 wheel 元数据提供的开源许可选项。

Qt DLL 保留为独立文件，不把 Qt 静态链接进应用。没有修改 Qt、PySide6 或 FFmpeg 源码。对应源代码可从 [Qt 源码库](https://code.qt.io/)、[PySide 源码库](https://code.qt.io/cgit/pyside/pyside-setup.git/) 和 [FFmpeg 源码](https://ffmpeg.org/download.html) 获取；替换组件时须满足实际所用版本和许可的要求。

本说明不以应用自身的许可证覆盖第三方组件。便携包不包含 WebEngine／Chromium 或 Qt PDF 模块；最终动态依赖清单以构建输出为准。
