$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$pythonPath = Join-Path $projectRoot ".venv/Scripts/python.exe"
if (!(Test-Path -LiteralPath $pythonPath)) {
    throw "请先按 README 创建 .venv 并安装依赖。"
}
if (!(Test-Path -LiteralPath (Join-Path $projectRoot "frontend/dist/index.html"))) {
    throw "请先在 frontend 目录运行 npm install 和 npm run build。"
}
Write-Host "阅卷助手已准备启动。请打开 http://127.0.0.1:8765"
if (Test-Path -LiteralPath (Join-Path $projectRoot ".browsers")) {
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $projectRoot ".browsers"
}
& $pythonPath -m grading_assistant.main
