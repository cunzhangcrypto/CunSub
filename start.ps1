# CunSub Startup Script - CunZhang Lab
# Single window, backend(5278) + frontend(5277) together
# 后端/前端为独立进程, 日志汇聚到本窗口; 任一进程崩溃自动重启, 不互相拖累

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Step($msg) { Write-Host $msg -ForegroundColor Cyan }
function Write-OK { Write-Host " OK" -ForegroundColor Green }
function Write-Fail { Write-Host " FAILED" -ForegroundColor Red }

Write-Host ""
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host "   CunSub - AI Subtitle Workflow" -ForegroundColor Cyan
Write-Host "   CunZhang Lab" -ForegroundColor Cyan
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host ""

# 0. Clean up ports + leftover processes
Write-Host "[0/4] Cleaning ports 5277/5278..." -NoNewline
foreach ($port in 5277, 5278) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Milliseconds 800
Write-OK

# 1. ffmpeg
Write-Step "[1/4] Checking ffmpeg..." -NoNewline
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Fail
    Write-Host "  ffmpeg not found. Install and add to PATH." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-OK

# 2. .env
Write-Step "[2/4] Checking .env..." -NoNewline
if (-not (Test-Path (Join-Path $ProjectRoot "backend\.env"))) {
    Write-Fail
    Write-Host "  backend\.env not found. Create with: GEMINI_API_KEY=your_key" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-OK

# 3. frontend deps
Write-Step "[3/4] Checking frontend deps..." -NoNewline
if (-not (Test-Path (Join-Path $ProjectRoot "frontend\node_modules"))) {
    Write-Host " installing..." -ForegroundColor Yellow
    Push-Location (Join-Path $ProjectRoot "frontend")
    npm install
    Pop-Location
} else {
    Write-OK
}

Write-Host ""
Write-Host "  Starting backend (5278) + frontend (5277)..." -ForegroundColor Cyan
Write-Host "  Browser: http://localhost:5277" -ForegroundColor White
Write-Host "  Press Ctrl+C to stop both." -ForegroundColor Gray
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host ""

$BackendLog = Join-Path $ProjectRoot "backend\backend.log"
$BackendErr = Join-Path $ProjectRoot "backend\backend.err.log"
$FrontendLog = Join-Path $ProjectRoot "frontend\vite.log"
$FrontendErr = Join-Path $ProjectRoot "frontend\vite.err.log"
Remove-Item $BackendLog, $BackendErr, $FrontendLog, $FrontendErr -ErrorAction SilentlyContinue

$MAX_RESTART = 3   # 单个服务最多自动重启次数
$backendProc = $null
$frontendProc = $null
$backendRestarts = 0
$frontendRestarts = 0
$beTail = 0
$feTail = 0

function Start-Backend {
    param([string]$root)
    Start-Process -FilePath "python" -ArgumentList "run.py" `
        -WorkingDirectory (Join-Path $root "backend") `
        -RedirectStandardOutput (Join-Path $root "backend\backend.log") `
        -RedirectStandardError (Join-Path $root "backend\backend.err.log") `
        -WindowStyle Hidden -PassThru
}

function Start-Frontend {
    param([string]$root)
    $env:NO_COLOR = "1"   # 禁用 ANSI 颜色码, 避免日志乱码
    Start-Process -FilePath "npm.cmd" -ArgumentList @("run", "dev") `
        -WorkingDirectory (Join-Path $root "frontend") `
        -RedirectStandardOutput (Join-Path $root "frontend\vite.log") `
        -RedirectStandardError (Join-Path $root "frontend\vite.err.log") `
        -WindowStyle Hidden -PassThru
}

$backendProc = Start-Backend $ProjectRoot
$frontendProc = Start-Frontend $ProjectRoot

# 4. Wait for frontend + backend to be ready, then auto-open browser
Write-Host "[4/4] Waiting for services (max 40s)..." -ForegroundColor Gray
$feOk = $false
$beOk = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 1
    try {
        if ((Invoke-WebRequest -Uri "http://localhost:5277" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop).StatusCode -eq 200) { $feOk = $true }
    } catch {}
    try {
        if ((Invoke-WebRequest -Uri "http://127.0.0.1:5278/branding" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop).StatusCode -eq 200) { $beOk = $true }
    } catch {}
    if ($feOk -and $beOk) { break }
    # 启动期间崩溃也立刻重启
    if ($backendProc.HasExited -and $backendRestarts -lt $MAX_RESTART) {
        Write-Host "  [backend] crashed during startup, restarting..." -ForegroundColor Yellow
        $backendProc = Start-Backend $ProjectRoot
        $backendRestarts++
    }
    if ($frontendProc.HasExited -and $frontendRestarts -lt $MAX_RESTART) {
        Write-Host "  [frontend] crashed during startup, restarting..." -ForegroundColor Yellow
        $frontendProc = Start-Frontend $ProjectRoot
        $frontendRestarts++
    }
}
if ($feOk -and $beOk) {
    Write-Host "  Services ready. Opening browser..." -ForegroundColor Green
    Start-Process "http://localhost:5277"
} else {
    Write-Host "  Not fully ready: frontend=$feOk backend=$beOk" -ForegroundColor Yellow
    Write-Host "  Check log files: backend\backend.log / frontend\vite.log" -ForegroundColor Yellow
}

# Main loop: tail logs + auto-restart crashed services
try {
    while ($true) {
        # 输出后端日志(增量)
        if (Test-Path $BackendLog) {
            $lines = @(Get-Content $BackendLog -ErrorAction SilentlyContinue)
            if ($lines.Count -gt $beTail) {
                for ($i = $beTail; $i -lt $lines.Count; $i++) { Write-Host "[backend] $($lines[$i])" -ForegroundColor Gray }
                $beTail = $lines.Count
            }
        }
        # 输出前端日志(增量)
        if (Test-Path $FrontendLog) {
            $lines = @(Get-Content $FrontendLog -ErrorAction SilentlyContinue)
            if ($lines.Count -gt $feTail) {
                for ($i = $feTail; $i -lt $lines.Count; $i++) { Write-Host "[frontend] $($lines[$i])" -ForegroundColor DarkGray }
                $feTail = $lines.Count
            }
        }
        # 后端崩溃 → 自动重启
        if ($backendProc -and $backendProc.HasExited) {
            if ($backendRestarts -lt $MAX_RESTART) {
                Write-Host "[backend] exited (code $($backendProc.ExitCode)), restarting ($($backendRestarts+1)/$MAX_RESTART)..." -ForegroundColor Yellow
                $backendProc = Start-Backend $ProjectRoot
                $backendRestarts++
            } else {
                Write-Host "[backend] exited permanently after $MAX_RESTART restarts." -ForegroundColor Red
                Write-Host "  See backend\backend.err.log for details." -ForegroundColor Red
                $backendProc = $null
            }
        }
        # 前端崩溃 → 自动重启
        if ($frontendProc -and $frontendProc.HasExited) {
            if ($frontendRestarts -lt $MAX_RESTART) {
                Write-Host "[frontend] exited (code $($frontendProc.ExitCode)), restarting ($($frontendRestarts+1)/$MAX_RESTART)..." -ForegroundColor Yellow
                $frontendProc = Start-Frontend $ProjectRoot
                $frontendRestarts++
            } else {
                Write-Host "[frontend] exited permanently after $MAX_RESTART restarts." -ForegroundColor Red
                $frontendProc = $null
            }
        }
        Start-Sleep -Milliseconds 500
    }
} finally {
    Write-Host "  Stopping services..." -ForegroundColor Gray
    if ($backendProc -and -not $backendProc.HasExited) { Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue }
    if ($frontendProc -and -not $frontendProc.HasExited) { Stop-Process -Id $frontendProc.Id -Force -ErrorAction SilentlyContinue }
    Write-Host "  Done. Bye." -ForegroundColor Gray
}
