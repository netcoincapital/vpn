# اسکریپت ساخت گواهی‌ها برای OpenVPN (Windows)
# پیش‌نیاز: نصب OpenVPN و قرار دادن easy-rsa در مسیر زیر یا دانلود easy-rsa

$ErrorActionPreference = "Stop"
$openvpnPath = "C:\Program Files\OpenVPN"
$configPath = "$openvpnPath\config"
$easyRsaPath = "C:\Program Files\OpenVPN\easy-rsa"  # در صورت استفاده از easy-rsa جدا، مسیر را عوض کنید

if (-not (Test-Path $configPath)) {
    New-Item -ItemType Directory -Path $configPath -Force
}

Write-Host "ساخت گواهی‌ها با easy-rsa..."
Write-Host "اگر easy-rsa نصب نیست، از لینک زیر دانلود کنید:"
Write-Host "https://github.com/OpenVPN/easy-rsa/releases"
Write-Host ""

# اگر OpenVPN از طریق Chocolatey یا نصبگر نصب شده، ممکن است easy-rsa در مسیر نمونه باشد
$samplePath = "C:\Program Files\OpenVPN\sample-config"
if (Test-Path "$openvpnPath\easy-rsa") {
    Set-Location "$openvpnPath\easy-rsa"
    # با توجه به نسخه easy-rsa دستورات متفاوت است
    # برای easy-rsa 3.x:
    if (Test-Path "vars") {
        .\vars
        ./easyrsa init-pki
        ./easyrsa build-ca nopass
        ./easyrsa gen-req server nopass
        ./easyrsa sign-req server server
        ./easyrsa gen-dh
        Copy-Item "pki\ca.crt" $configPath
        Copy-Item "pki\issued\server.crt" $configPath
        Copy-Item "pki\private\server.key" $configPath
        Copy-Item "pki\dh.pem" $configPath
        Write-Host "گواهی‌ها در $configPath ساخته شد."
    }
} else {
    Write-Host "easy-rsa در مسیر پیش‌فرض یافت نشد."
    Write-Host "می‌توانید از OpenVPN GUI یا دستورات openssl گواهی بسازید."
    Write-Host "فایل ca.crt را در پوشه client قرار دهید تا کلاینت‌ها بتوانند سرور را تأیید کنند."
}
