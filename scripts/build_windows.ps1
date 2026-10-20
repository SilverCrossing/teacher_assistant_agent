param([switch]$IncludeBrowser)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$pythonPath = Join-Path $projectRoot ".venv/Scripts/python.exe"
if (!(Test-Path -LiteralPath $pythonPath)) { throw "请先运行首次安装.bat。" }
if (!(Test-Path -LiteralPath (Join-Path $projectRoot "frontend/dist/index.html"))) { throw "请先构建前端。" }

# 只有维护者在构建机安装打包工具；教师收到的包不需要 Python、Node 或 pip。
& $pythonPath -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('PyInstaller') else 1)"
if ($LASTEXITCODE -ne 0) {
    & $pythonPath -m pip install "pyinstaller>=6.12,<7"
    if ($LASTEXITCODE -ne 0) { throw "打包工具安装失败。" }
}
$frontendPath = Join-Path $projectRoot "frontend/dist"
$sourcePath = Join-Path $projectRoot "src"
$arguments = @("--noconfirm", "--onedir", "--name", "TeacherGradingAssistant", "--distpath", "release", "--workpath", ".build/pyinstaller", "--specpath", ".build", "--paths", $sourcePath, "--add-data", "$frontendPath;frontend/dist", "--collect-all", "playwright", "--collect-all", "keyring", "--hidden-import", "keyring.backends.Windows", "scripts/desktop_entry.py")
& $pythonPath -m PyInstaller @arguments
if ($LASTEXITCODE -ne 0) { throw "程序打包失败。" }
$releaseRoot = Join-Path $projectRoot "release/TeacherGradingAssistant"
New-Item -ItemType Directory -Path (Join-Path $releaseRoot "config") -Force | Out-Null
# 分发只复制白名单文件，绝不带入本机配置、草稿、日志或浏览器登录状态。
Copy-Item -LiteralPath "config/example.json" -Destination (Join-Path $releaseRoot "config/example.json")
Copy-Item -LiteralPath "docs/教师使用指南.md" -Destination (Join-Path $releaseRoot "使用说明.md")
if ($IncludeBrowser) {
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $projectRoot ".browsers"
    & $pythonPath -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw "浏览器内核下载失败。" }
    Copy-Item -LiteralPath (Join-Path $projectRoot ".browsers") -Destination (Join-Path $releaseRoot "browsers") -Recurse -Force
}
Compress-Archive -Path (Join-Path $releaseRoot "*") -DestinationPath (Join-Path $projectRoot "release/TeacherGradingAssistant-windows.zip") -Force
Write-Host "分发包已生成：release/TeacherGradingAssistant-windows.zip" -ForegroundColor Green
if (!$IncludeBrowser) { Write-Host "此包未包含浏览器内核，可离线演示；真实网站读取需提供内核。" -ForegroundColor Yellow }
