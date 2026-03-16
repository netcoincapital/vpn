# ============================================================
# ساخت فایل کانفیگ کلاینت با IP سرور شما
# استفاده: .\3-create-client-config.ps1 -ServerIP "1.2.3.4"
# ============================================================

param(
    [Parameter(Mandatory=$true)]
    [string]$ServerIP
)

$clientDir = Join-Path $PSScriptRoot "..\client"
$template = Join-Path $clientDir "client-template.ovpn"
$output = Join-Path $clientDir "client.ovpn"

$content = Get-Content $template -Raw -Encoding UTF8
$content = $content -replace "YOUR_SERVER_IP", $ServerIP
Set-Content -Path $output -Value $content -Encoding UTF8
Write-Host "فایل ساخته شد: $output"
Write-Host "این فایل را به همراه ca.crt (از پوشه config سرور) به کاربران بدهید."
