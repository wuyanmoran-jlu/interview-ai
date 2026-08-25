# ============================================
# AI Interview Simulator - One-Click Start
# ============================================
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

chcp 65001 > $null 2>&1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI Interview Simulator - Starting..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# ---------- 1. Start Judge0 (code sandbox) ----------
Write-Host ""
Write-Host "[1/4] Starting Judge0 (code sandbox)..." -ForegroundColor Yellow
Write-Host "  This may take 30-60 seconds on first run..." -ForegroundColor DarkGray
Push-Location "$root\judge0"
try {
    $output = docker-compose up -d server workers db redis 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: Judge0 failed to start." -ForegroundColor Red
        Write-Host "  $output" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "  Judge0 is starting (port 2358) - wait ~30s before using code execution" -ForegroundColor Green
} finally {
    Pop-Location
}

# ---------- 2. Start Redis ----------
Write-Host ""
Write-Host "[2/4] Starting Redis..." -ForegroundColor Yellow
Push-Location "$root\judge0"
try {
    $output = docker-compose up -d session-redis 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: Redis failed to start." -ForegroundColor Red
        Write-Host "  $output" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "  Redis is running (localhost:6379)" -ForegroundColor Green
} finally {
    Pop-Location
}

# ---------- 3. Start Backend ----------
Write-Host ""
Write-Host "[3/4] Starting Backend (FastAPI)..." -ForegroundColor Yellow
$venvPython = "$root\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "  ERROR: Virtual environment not found: $venvPython" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Start-Process -FilePath $venvPython `
    -ArgumentList "$root\backend\main.py" `
    -WorkingDirectory "$root\backend" `
    -WindowStyle Normal
Write-Host "  Backend started -> http://localhost:8000" -ForegroundColor Green

# ---------- 4. Start Frontend ----------
Write-Host ""
Write-Host "[4/4] Starting Frontend (Vite)..." -ForegroundColor Yellow
$npmPath = (Get-Command npm -ErrorAction SilentlyContinue).Source
if (-not $npmPath) { $npmPath = "C:\Program Files\nodejs\npm.cmd" }
Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c", "cd /d `"$root\frontend`" && npm run dev" `
    -WindowStyle Normal
Write-Host "  Frontend started -> http://localhost:5173" -ForegroundColor Green

# ---------- Done ----------
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  All services started!" -ForegroundColor Cyan
Write-Host "  Judge0  : http://localhost:2358 (code sandbox)" -ForegroundColor White
Write-Host "  Backend : http://localhost:8000" -ForegroundColor White
Write-Host "  Frontend: http://localhost:5173" -ForegroundColor White
Write-Host "  Stop    : Run stop.ps1 or close the pop-up windows" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Cyan

Read-Host "Press Enter to close this window (services keep running)"
