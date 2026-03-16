# اضافه کردن کاربر به فایل users.txt با تاریخ انقضا
# استفاده:
#   .\add-user.ps1 -Username "user1" -Password "pass123"           # انقضای پیش‌فرض 30 روز
#   .\add-user.ps1 -Username "user1" -Password "pass123" -Days 60  # انقضای 60 روزه

param(
    [Parameter(Mandatory=$true)]
    [string]$Username,
    [Parameter(Mandatory=$true)]
    [string]$Password,
    [int]$Days = 30
)

$usersFile = Join-Path $PSScriptRoot "..\server\users.txt"

if ($Days -le 0) {
    $Days = 30
}

$expiry = (Get-Date).AddDays($Days).ToString("yyyy-MM-dd")
$line = "${Username}:${Password}:${expiry}"
Add-Content -Path $usersFile -Value $line
Write-Host "کاربر '$Username' با انقضای $Days روزه (تا $expiry) اضافه شد."
