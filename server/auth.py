#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اسکریپت تأیید یوزرنیم و پسورد برای OpenVPN.
فایل users.txt را با فرمت یوزرنیم:پسورد پر کنید.
"""
import os
import sys

USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.txt")

def main():
    # OpenVPN username و password را در یک فایل موقت می‌فرستد (خط اول یوزرنیم، خط دوم پسورد)
    if len(sys.argv) < 2:
        sys.exit(1)
    tmp_file = sys.argv[1]
    try:
        with open(tmp_file, "r", encoding="utf-8") as f:
            lines = f.read().strip().split("\n")
        if len(lines) < 2:
            sys.exit(1)
        username = lines[0].strip()
        password = lines[1].strip()
    except Exception:
        sys.exit(1)

    if not os.path.exists(USERS_FILE):
        sys.exit(1)

    with open(USERS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                u, p = line.split(":", 1)
                if u.strip() == username and p.strip() == password:
                    sys.exit(0)
    sys.exit(1)

if __name__ == "__main__":
    main()
