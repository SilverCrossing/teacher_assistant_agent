param([switch]$SkipBrowser)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

function Run-Step([string]$Title, [scriptblock]$Action) {
    Write-Host "`n>>> $Title" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "$Title 失败。请检查网络，稍后再次双击安装；已完成的步骤会复用。" }
}

try {
    Write-Host "阅卷助手 · 首次安装（仅安装到项目目录）" -ForegroundColor Green
    Write-Host "需要联网下载依赖。无需手动输入命令；失败后可再次运行。"
    $pythonPath = Join-Path $projectRoot ".venv/Scripts/python.exe"
    if (!(Test-Path -LiteralPath $pythonPath)) {
        $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
        $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
        $pythonReady = $false
        if ($pyLauncher) {
            & $pyLauncher.Source -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) {
                Run-Step "创建独立 Python 环境" { & $pyLauncher.Source -3 -m venv .venv }
                $pythonReady = $true
            }
        }
        if (!$pythonReady -and $pythonCommand) {
            & $pythonCommand.Source -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) {
                Run-Step "创建独立 Python 环境" { & $pythonCommand.Source -m venv .venv }
                $pythonReady = $true
            }
        }
        if (!$pythonReady) {
            Write-Host "未找到 Python 3.11 或更新版本。推荐请学校管理员提供免安装便携包。" -ForegroundColor Yellow
            Write-Host "源码安装可访问 https://www.python.org/downloads/windows/，安装后再次运行本程序。"
            throw "Python 环境尚未准备完成。"
        }
    }
    Run-Step "安装已锁定的后端依赖" { & $pythonPath -m pip install -r requirements.lock.txt --disable-pip-version-check --timeout 30 --retries 2 }
    Run-Step "安装阅卷助手" { & $pythonPath -m pip install -e . --no-deps --disable-pip-version-check }
    if (!(Test-Path -LiteralPath (Join-Path $projectRoot "frontend/dist/index.html"))) {
        $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
        $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
        if (!$npmCommand -or !$nodeCommand) {
            throw "未找到 Node.js。请安装 https://nodejs.org/ 的 LTS 版本后重试，或让管理员提供已包含前端的便携包。"
        }
        Run-Step "检查 Node.js 版本" { & $nodeCommand.Source -e "const [a,b]=process.versions.node.split('.').map(Number); if(a<22 || (a===22 && b<12)) process.exit(1)" }
        Push-Location (Join-Path $projectRoot "frontend")
        try {
            Run-Step "安装界面依赖" { & $npmCommand.Source ci --fetch-retries=2 --fetch-timeout=30000 }
            Run-Step "生成界面" { & $npmCommand.Source run build }
        } finally { Pop-Location }
    }
    if (!$SkipBrowser) {
        $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $projectRoot ".browsers"
        Run-Step "下载只读浏览器（仅首次需要，约 300 MB）" { & $pythonPath -m playwright install chromium }
    }
    Write-Host "`n安装完成！今后双击【启动阅卷助手.bat】即可。" -ForegroundColor Green
} catch {
    Write-Host "`n$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "请将此窗口内容交给学校维护者。密钥无需提供给维护者。"
    exit 1
}
