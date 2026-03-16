# Copy server.ovpn to user OpenVPN config folder so GUI finds it (no admin needed)

$userConfig = "$env:USERPROFILE\OpenVPN\config"
$source = Join-Path $PSScriptRoot "..\server\server.ovpn"

if (-not (Test-Path $source)) {
    Write-Host "Source not found: $source"
    exit 1
}
if (-not (Test-Path $userConfig)) {
    New-Item -ItemType Directory -Path $userConfig -Force
}
Copy-Item $source -Destination (Join-Path $userConfig "server.ovpn") -Force
Write-Host "Copied server.ovpn to $userConfig"
Write-Host "Open OpenVPN GUI again - it should see the profile. Connect only works if certs exist in C:\Program Files\OpenVPN\config\"
