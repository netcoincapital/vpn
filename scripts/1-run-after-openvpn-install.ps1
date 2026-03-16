# Run after OpenVPN install - MUST run as Administrator

$ErrorActionPreference = "Stop"
$openvpnConfig = "C:\Program Files\OpenVPN\config"
$sourceServer = Join-Path $PSScriptRoot "..\server"

# Require Administrator (needed to write to Program Files and add firewall rule)
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Re-launching as Administrator (approve the UAC prompt)..."
    Start-Process powershell -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File", "`"$PSCommandPath`"" -Verb RunAs
    exit 0
}

if (-not (Test-Path "C:\Program Files\OpenVPN")) {
    Write-Host "OpenVPN is not installed. Install from: https://openvpn.net/community-downloads/"
    Write-Host "During install, select EasyRSA option."
    exit 1
}

if (-not (Test-Path $openvpnConfig)) {
    New-Item -ItemType Directory -Path $openvpnConfig -Force
    Write-Host "Created config folder: $openvpnConfig"
}

$files = @("openvpn-server.conf", "auth.ps1", "auth.bat", "users.txt")
foreach ($f in $files) {
    $src = Join-Path $sourceServer $f
    if (Test-Path $src) {
        Copy-Item $src -Destination (Join-Path $openvpnConfig $f) -Force
        Write-Host "Copied: $f"
    }
}
Copy-Item (Join-Path $openvpnConfig "openvpn-server.conf") -Destination (Join-Path $openvpnConfig "server.ovpn") -Force -ErrorAction SilentlyContinue

$ruleName = "OpenVPN-UDP-1194"
$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if (-not $existing) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol UDP -LocalPort 1194 -Action Allow
    Write-Host "Firewall rule for UDP 1194 added."
} else {
    Write-Host "Firewall rule already exists."
}

Write-Host ""
Write-Host "Next: run 2-generate-certificates.ps1 to create certificates."
