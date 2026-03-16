@echo off
chcp 65001 >nul
echo اجرای اسکریپت‌ها با حقوق Administrator
echo.
echo اول OpenVPN را نصب کنید، بعد این فایل را اجرا کنید.
pause
powershell -ExecutionPolicy Bypass -Command "Start-Process powershell -ArgumentList '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', '%~dp01-run-after-openvpn-install.ps1' -Verb RunAs"
