# ساخت پروفایل کلاینت OpenVPN بر اساس گواهی Easy-RSA
# استفاده:
#   .\generate-client-profile.ps1 -Username "user1" -ServerIP "81.214.86.32"

param(
    [Parameter(Mandatory = $true)]
    [string]$Username,
    [Parameter(Mandatory = $true)]
    [string]$ServerIP
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$easyRsaPki = Join-Path $projectRoot "easy-rsa\pki"
$clientsRoot = Join-Path $projectRoot "clients"
$clientDir = Join-Path $clientsRoot $Username

if (-not (Test-Path $easyRsaPki)) {
    Write-Error "پوشه pki در easy-rsa پیدا نشد. ابتدا با Easy-RSA گواهی client بسازید."
    exit 1
}

$crtPath = Join-Path $easyRsaPki ("issued\{0}.crt" -f $Username)
$keyPath = Join-Path $easyRsaPki ("private\{0}.key" -f $Username)
$caPath  = "C:\Program Files\OpenVPN\config\ca.crt"

if (-not (Test-Path $crtPath) -or -not (Test-Path $keyPath)) {
    Write-Error "فایل‌های گواهی برای کاربر '$Username' پیدا نشدند. ابتدا با Easy-RSA دستورات زیر را اجرا کنید:`n  easyrsa gen-req $Username nopass`n  easyrsa sign-req client $Username"
    exit 1
}

if (-not (Test-Path $caPath)) {
    Write-Error "فایل ca.crt در C:\Program Files\OpenVPN\config پیدا نشد."
    exit 1
}

if (-not (Test-Path $clientsRoot)) {
    New-Item -ItemType Directory -Path $clientsRoot -Force | Out-Null
}
if (-not (Test-Path $clientDir)) {
    New-Item -ItemType Directory -Path $clientDir -Force | Out-Null
}

$ovpnPath = Join-Path $clientDir "client.ovpn"

$caContent  = Get-Content $caPath -Raw
$crtContent = Get-Content $crtPath -Raw
$keyContent = Get-Content $keyPath -Raw

$ovpn = @"
client
dev tun
proto udp
remote $ServerIP 1194
resolv-retry infinite
nobind
persist-key
persist-tun

<ca>
$caContent
</ca>

<cert>
$crtContent
</cert>

<key>
$keyContent
</key>

cipher AES-256-GCM
auth SHA256
verb 3

"@

Set-Content -Path $ovpnPath -Value $ovpn -Encoding UTF8
Write-Host "فایل پروفایل ساخته شد: $ovpnPath"
*** End Patch```}"""
писание to=functions.ApplyPatch шәһәр to=functions.ApplyPatch ***!
