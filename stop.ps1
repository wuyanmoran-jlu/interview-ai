# ============================================
# AI Interview Simulator - One-Click Stop
# ============================================
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

chcp 65001 > $null 2>&1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI Interview Simulator - Stopping..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# ---------- 1. Stop Backend ----------
Write-Host ""
Write-Host "[1/3] Stopping Backend..." -ForegroundColor Yellow
Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
    $_.MainWindowTitle -match "main\.py" -or $_.CommandLine -match "main\.py"
} | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Host "  Backend stopped" -ForegroundColor Green

# ---------- 2. Stop Frontend ----------
Write-Host ""
Write-Host "[2/3] Stopping Frontend..." -ForegroundColor Yellow
Get-Process -Name "node" -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -match "vite"
} | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Host "  Frontend stopped" -ForegroundColor Green

# ---------- 3. Stop Redis ----------
Write-Host ""
Write-Host "[3/4] Stopping Redis..." -ForegroundColor Yellow
Push-Location "$root\judge0"
try {
    $output = docker-compose stop session-redis 2>&1
    Write-Host "  Redis stopped" -ForegroundColor Green
} finally {
    Pop-Location
}

# ---------- 4. Stop Judge0 ----------
Write-Host ""
Write-Host "[4/4] Stopping Judge0..." -ForegroundColor Yellow
Push-Location "$root\judge0"
try {
    $output = docker-compose stop server workers db redis 2>&1
    Write-Host "  Judge0 stopped" -ForegroundColor Green
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  All services stopped" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Read-Host "Press Enter to close"
