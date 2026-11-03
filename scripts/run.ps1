[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if ([IO.Path]::GetPathRoot($projectRoot).TrimEnd('\').ToUpperInvariant() -eq 'C:') {
    throw '请将软件源码放到非 C 盘可写目录后运行。'
}
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw '项目虚拟环境不存在，请按 README 创建 .venv 并安装 requirements.txt。'
}
$temporaryRoot = Join-Path $projectRoot '.cache\temp'
New-Item -ItemType Directory -Path $temporaryRoot -Force | Out-Null
$previousTemp = $env:TEMP
$previousTmp = $env:TMP
try {
    $env:TEMP = $temporaryRoot
    $env:TMP = $temporaryRoot
    Push-Location -LiteralPath $projectRoot
    try {
        & $pythonPath (Join-Path $projectRoot 'main.py')
        if ($LASTEXITCODE -ne 0) {
            throw "软件退出代码：$LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
} finally {
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
}
