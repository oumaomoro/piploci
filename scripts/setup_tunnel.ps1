# ============================================================
# Piploci — Cloudflare Named Tunnel Setup Script
# Creates a persistent named tunnel replacing temporary
# trycloudflare.com URLs so Streamlit Cloud never loses
# the backend endpoint.
#
# Prerequisites:
#   - cloudflared installed: winget install Cloudflare.cloudflared
#   - Cloudflare account logged in: cloudflared tunnel login
#
# Usage:
#   .\scripts\setup_tunnel.ps1
# ============================================================

param(
    [string]$TunnelName  = "piploci-tunnel",
    [string]$Hostname    = "api.piploci.trade",   # Replace with your actual domain
    [string]$LocalPort   = "8000",
    [string]$ConfigDir   = "$env:USERPROFILE\.cloudflared"
)

$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Piploci -- Cloudflare Named Tunnel Setup" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# ── Check cloudflared ────────────────────────────────────────────────────────
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] cloudflared not found. Install via:" -ForegroundColor Red
    Write-Host "        winget install Cloudflare.cloudflared" -ForegroundColor Yellow
    exit 1
}

Write-Host "[INFO] cloudflared found." -ForegroundColor Green

# ── Create tunnel ────────────────────────────────────────────────────────────
Write-Host "[INFO] Creating named tunnel: $TunnelName ..." -ForegroundColor Cyan
$tunnelOutput = cloudflared tunnel create $TunnelName 2>&1
Write-Host $tunnelOutput

# Extract tunnel UUID from output
$tunnelId = ($tunnelOutput | Select-String -Pattern "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}").Matches[0].Value

if (-not $tunnelId) {
    # Tunnel may already exist — list and grab it
    $listOutput = cloudflared tunnel list 2>&1
    $tunnelId = ($listOutput | Select-String -Pattern "([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\s+$TunnelName").Matches[0].Groups[1].Value
    if ($tunnelId) {
        Write-Host "[INFO] Tunnel already exists. Reusing ID: $tunnelId" -ForegroundColor Yellow
    } else {
        Write-Host "[ERROR] Could not extract tunnel ID. Run: cloudflared tunnel list" -ForegroundColor Red
        exit 1
    }
}

Write-Host "[OK] Tunnel ID: $tunnelId" -ForegroundColor Green

# ── Write config.yml ─────────────────────────────────────────────────────────
$configPath = "$ConfigDir\config.yml"

$configContent = @"
tunnel: $tunnelId
credentials-file: $ConfigDir\$tunnelId.json

ingress:
  - hostname: $Hostname
    service: http://127.0.0.1:$LocalPort
  - service: http_status:404
"@

Write-Host "[INFO] Writing config to: $configPath" -ForegroundColor Cyan
Set-Content -Path $configPath -Value $configContent -Encoding UTF8
Write-Host "[OK] config.yml written." -ForegroundColor Green

# ── DNS Route ────────────────────────────────────────────────────────────────
Write-Host "[INFO] Creating DNS CNAME route for $Hostname ..." -ForegroundColor Cyan
cloudflared tunnel route dns $TunnelName $Hostname
Write-Host "[OK] DNS route created." -ForegroundColor Green

# ── Run test ─────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[INFO] Validating tunnel config..." -ForegroundColor Cyan
cloudflared tunnel ingress validate

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host "  Tunnel Name : $TunnelName" -ForegroundColor Green
Write-Host "  Tunnel ID   : $tunnelId" -ForegroundColor Green
Write-Host "  Hostname    : $Hostname" -ForegroundColor Green
Write-Host "  Config      : $configPath" -ForegroundColor Green
Write-Host ""
Write-Host "  To run the tunnel as a Windows Service:" -ForegroundColor Cyan
Write-Host "    cloudflared service install" -ForegroundColor White
Write-Host ""
Write-Host "  Update Streamlit Cloud secrets:" -ForegroundColor Cyan
Write-Host "    API_BASE = https://$Hostname/api/v1" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Green
