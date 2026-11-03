[CmdletBinding()]
param([switch]$SkipTests)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if ([IO.Path]::GetPathRoot($projectRoot).TrimEnd('\').ToUpperInvariant() -eq 'C:') {
    throw '请在非 C 盘可写项目目录中构建。'
}

function Assert-WorkspacePath([string]$Target) {
    $resolved = (& $pythonPath -c 'from pathlib import Path; import sys, json; print(json.dumps(str(Path(sys.argv[1]).resolve()), ensure_ascii=True))' $Target) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw '无法解析构建路径。' }
    $prefix = $projectRoot.TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "构建输出超出项目目录，已停止：$resolved"
    }
    return $resolved
}

$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw '请先创建 .venv 并安装 requirements-build.txt。'
}
$projectRoot = (& $pythonPath -c 'from pathlib import Path; import sys, json; print(json.dumps(str(Path(sys.argv[1]).resolve()), ensure_ascii=True))' $projectRoot) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or [IO.Path]::GetPathRoot($projectRoot).TrimEnd('\').ToUpperInvariant() -eq 'C:') {
    throw '项目目录解析后位于 C 盘或无法解析，已停止。'
}
$entryPath = Join-Path $projectRoot 'main.py'
if (-not (Test-Path -LiteralPath $entryPath -PathType Leaf)) {
    throw '找不到 main.py，不能构建。'
}
$appName = '题目查询助手'
$version = (& $pythonPath -c 'import sys; sys.path.insert(0, sys.argv[1]); from quiz_helper import __version__; print(__version__)' $projectRoot).Trim()
if ($LASTEXITCODE -ne 0 -or $version -notmatch '^\d+\.\d+\.\d+$') { throw '版本号无效。' }
$distRoot = Assert-WorkspacePath (Join-Path $projectRoot 'dist')
$releaseDistRoot = Assert-WorkspacePath (Join-Path $distRoot ('v' + $version))
$releaseRoot = Assert-WorkspacePath (Join-Path $releaseDistRoot $appName)
if (Test-Path -LiteralPath (Join-Path $releaseRoot 'data')) {
    throw '旧构建目录包含 data 运行数据，请先备份并改名该输出目录；本脚本不会覆盖它。'
}
$cacheRoot = Assert-WorkspacePath (Join-Path $projectRoot '.cache')
$workRoot = Assert-WorkspacePath (Join-Path $cacheRoot 'build')
$specRoot = Assert-WorkspacePath (Join-Path $cacheRoot 'spec')
$temporaryRoot = Assert-WorkspacePath (Join-Path $cacheRoot 'temp')
$installerCache = Assert-WorkspacePath (Join-Path $cacheRoot 'pyinstaller')
New-Item -ItemType Directory -Path $distRoot, $workRoot, $specRoot, $temporaryRoot, $installerCache -Force | Out-Null

$previousTemp = $env:TEMP
$previousTmp = $env:TMP
$previousInstallerCache = $env:PYINSTALLER_CONFIG_DIR
$previousPath = $env:PATH
try {
    $env:TEMP = $temporaryRoot
    $env:TMP = $temporaryRoot
    $env:PYINSTALLER_CONFIG_DIR = $installerCache
    # Dependency analysis must not collect same-named ICU/API-set DLLs from
    # unrelated SDK, image, OCR, or developer-tool directories on PATH.
    $systemDirectory = [Environment]::GetFolderPath([Environment+SpecialFolder]::System)
    $windowsDirectory = Split-Path -Parent $systemDirectory
    $env:PATH = @((Split-Path -Parent $pythonPath), $systemDirectory, $windowsDirectory) -join ';'
    Push-Location -LiteralPath $projectRoot
    try {
        if (-not $SkipTests) {
            & $pythonPath -m unittest discover -s tests -v
            if ($LASTEXITCODE -ne 0) { throw '自动测试未通过，未执行打包。' }
        }
        $qtRoot = (& $pythonPath -c 'from pathlib import Path; import PySide6, json; print(json.dumps(str(Path(PySide6.__file__).parent), ensure_ascii=True))') | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) { throw '无法定位 PySide6。' }
        $ffmpegPlugin = Join-Path $qtRoot 'plugins\multimedia\ffmpegmediaplugin.dll'
        if (-not (Test-Path -LiteralPath $ffmpegPlugin -PathType Leaf)) {
            throw '缺少 QtMultimedia FFmpeg 插件，请安装完整且版本一致的 PySide6。'
        }
        $installerArguments = @(
            '-m', 'PyInstaller', '--noconfirm', '--onedir', '--windowed', '--noupx',
            '--name', $appName, '--distpath', $releaseDistRoot, '--workpath', $workRoot,
            '--specpath', $specRoot, '--paths', $projectRoot,
            '--additional-hooks-dir', (Join-Path $projectRoot 'scripts\hooks'),
            '--hidden-import', 'PySide6.QtMultimedia',
            '--icon', (Join-Path $projectRoot 'quiz_helper\assets\app.ico'),
            '--add-data', ((Join-Path $projectRoot 'quiz_helper\assets\app.ico') + ';quiz_helper/assets'),
            '--exclude-module', 'PySide6.QtWebEngineCore',
            '--exclude-module', 'PySide6.QtWebEngineWidgets',
            '--exclude-module', 'PySide6.QtWebEngineQuick',
            '--exclude-module', 'PySide6.QtPdf',
            '--exclude-module', 'PySide6.QtPdfWidgets',
            '--exclude-module', 'PySide6.QtWebView',
            '--add-binary', ($ffmpegPlugin + ';PySide6/plugins/multimedia'),
            $entryPath
        )
        & $pythonPath @installerArguments
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 打包失败。' }
        if (-not (Test-Path -LiteralPath (Join-Path $releaseRoot ($appName + '.exe')) -PathType Leaf)) {
            throw '未找到预期 EXE。'
        }
        if (-not (Get-ChildItem -LiteralPath $releaseRoot -Filter 'ffmpegmediaplugin.dll' -File -Recurse)) {
            throw '构建产物中缺少窗口捕获所需 FFmpeg 插件。'
        }

        foreach ($document in @('README.md', 'ROADMAP.md', 'CHANGELOG.md', 'THIRD_PARTY_NOTICES.md')) {
            Copy-Item -LiteralPath (Join-Path $projectRoot $document) -Destination $releaseRoot -Force
        }
        $deliveryReport = Join-Path $projectRoot 'DELIVERY.md'
        if (Test-Path -LiteralPath $deliveryReport -PathType Leaf) {
            Copy-Item -LiteralPath $deliveryReport -Destination $releaseRoot -Force
        }
        $documentationRoot = Join-Path $projectRoot 'docs'
        if (Test-Path -LiteralPath $documentationRoot -PathType Container) {
            Copy-Item -LiteralPath $documentationRoot -Destination $releaseRoot -Recurse -Force
        }
        $licenseRoot = Assert-WorkspacePath (Join-Path $releaseRoot 'LICENSES')
        New-Item -ItemType Directory -Path $licenseRoot -Force | Out-Null
        $sourceLicenses = Join-Path $projectRoot 'LICENSES'
        if (Test-Path -LiteralPath $sourceLicenses -PathType Container) {
            Get-ChildItem -LiteralPath $sourceLicenses -File | ForEach-Object {
                Copy-Item -LiteralPath $_.FullName -Destination $licenseRoot -Force
            }
        }
        $sitePackages = Join-Path $projectRoot '.venv\Lib\site-packages'
        Get-ChildItem -LiteralPath $sitePackages -Directory -Filter '*.dist-info' |
            Where-Object { $_.Name -match '^(pyside6-\d|pyside6_(addons|essentials)-|shiboken6-|pyinstaller-)' } |
            ForEach-Object {
                $bundledLicenses = Join-Path $_.FullName 'licenses'
                if (Test-Path -LiteralPath $bundledLicenses -PathType Container) {
                    $destination = Assert-WorkspacePath (Join-Path $licenseRoot $_.Name)
                    Copy-Item -LiteralPath $bundledLicenses -Destination $destination -Recurse -Force
                }
            }
        $pythonLicense = (& $pythonPath -c 'from pathlib import Path; import sys, json; print(json.dumps(str(Path(sys.base_prefix) / sys.argv[1]), ensure_ascii=True))' 'LICENSE.txt') | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) { throw '无法定位 Python 发行版许可证。' }
        if (Test-Path -LiteralPath $pythonLicense -PathType Leaf) {
            Copy-Item -LiteralPath $pythonLicense -Destination (Join-Path $licenseRoot 'PYTHON-LICENSE.txt') -Force
        } else {
            throw '缺少 Python 发行版许可证，未完成发布准备。'
        }
        $portableArchive = Assert-WorkspacePath (Join-Path $distRoot ('题目查询助手-portable-v' + $version + '.zip'))
        Compress-Archive -LiteralPath $releaseRoot -DestinationPath $portableArchive -Force
        if (-not (Test-Path -LiteralPath $portableArchive -PathType Leaf)) {
            throw '未生成便携版 ZIP。'
        }
        & $pythonPath (Join-Path $projectRoot 'scripts\package_source.py')
        if ($LASTEXITCODE -ne 0) { throw '源码 ZIP 生成失败。' }
        Write-Host "构建完成：$(Join-Path $releaseRoot ($appName + '.exe'))"
        Write-Host "便携版压缩包：$portableArchive"
    } finally {
        Pop-Location
    }
} finally {
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
    $env:PYINSTALLER_CONFIG_DIR = $previousInstallerCache
    $env:PATH = $previousPath
}
