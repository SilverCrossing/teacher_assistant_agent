$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$address = "http://127.0.0.1:8765"

function Test-Assistant {
    try {
        $health = Invoke-RestMethod "$address/api/health" -TimeoutSec 2
        return $health.status -eq "ok" -and $health.schema_version -eq "1"
    } catch { return $false }
}

try {
    if (Test-Assistant) {
        Start-Process $address
        exit 0
    }
    $pythonPath = Join-Path $projectRoot ".venv/Scripts/python.exe"
    $needsInstall = !(Test-Path -LiteralPath $pythonPath) -or !(Test-Path -LiteralPath (Join-Path $projectRoot "frontend/dist/index.html"))
    if (!$needsInstall) {
        & $pythonPath -c "import importlib.util,sys; sys.exit(0 if all(importlib.util.find_spec(m) for m in ('fastapi','uvicorn','grading_assistant','pypdf')) else 1)"
        $needsInstall = $LASTEXITCODE -ne 0
    }
    if ($needsInstall) {
        Write-Host "首次运行，开始检查与安装环境。" -ForegroundColor Cyan
        & (Join-Path $PSScriptRoot "install.ps1")
        if ($LASTEXITCODE -ne 0) { exit 1 }
    }
    if (Test-Path -LiteralPath (Join-Path $projectRoot ".browsers")) {
        $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $projectRoot ".browsers"
    }
    if (!$env:GRADING_CONFIG -and (Test-Path -LiteralPath (Join-Path $projectRoot "config/local.json"))) {
        $env:GRADING_CONFIG = Join-Path $projectRoot "config/local.json"
    }
    # 在当前启动窗口中运行，教师可以通过关闭窗口退出，无需寻找后台进程。
    Write-Host "正在打开阅卷助手，请保留此窗口。使用结束后关闭此窗口即可退出。" -ForegroundColor Green
    & $pythonPath (Join-Path $PSScriptRoot "desktop_entry.py")
    if ($LASTEXITCODE -ne 0) { throw "程序启动失败，请将以上提示交给学校维护者。" }

} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
