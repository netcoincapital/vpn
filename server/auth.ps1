# اسکریپت تأیید یوزرنیم و پسورد برای OpenVPN (Windows)
# فرمت فایل users.txt:
# یوزرنیم:پسورد:تاریخ_انقضا
# تاریخ انقضا به فرمت YYYY-MM-DD (مثال: 2026-04-15)

$usersFile = Join-Path $PSScriptRoot "users.txt"
$credFile = $args[0]

if (-not $credFile -or -not (Test-Path $credFile)) { exit 1 }

$lines = Get-Content $credFile
if ($lines.Count -lt 2) { exit 1 }

$user = $lines[0].Trim()
$pass = $lines[1].Trim()

# لاگ ساده برای اشکال‌زدایی احراز هویت
try {
    $logDir = "C:\Users\mohammad\OpenVPN"
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
    $logLine = "[{0}] user='{1}' pass='{2}'" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $user, $pass
    Add-Content -Path (Join-Path $logDir "auth-debug.log") -Value $logLine
} catch {
    # اگر نتوانستیم لاگ بنویسیم، احراز هویت را خراب نکن
}

if (-not (Test-Path $usersFile)) { exit 1 }

$today = Get-Date

Get-Content $usersFile -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }

    $parts = $line -split ":", 3
    $u = $parts[0].Trim()
    $p = if ($parts.Count -ge 2) { $parts[1].Trim() } else { "" }
    $expiryStr = if ($parts.Count -ge 3) { $parts[2].Trim() } else { $null }

    if ($u -eq $user -and $p -eq $pass) {
        if ($expiryStr) {
            try {
                $expiry = [DateTime]::ParseExact($expiryStr, "yyyy-MM-dd", [System.Globalization.CultureInfo]::InvariantCulture)
                if ($expiry -lt $today.Date) {
                    # منقضی شده
                    exit 1
                }
            } catch {
                # اگر تاریخ قابل خواندن نباشد، کاربر را نامعتبر در نظر بگیر
                exit 1
            }
        }
        # یوزرنیم/پسورد درست است و (تاریخ انقضا خالی است یا نرسیده است)
        exit 0
    }
}

exit 1
