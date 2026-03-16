#!/usr/bin/env python3
"""محدودیت مصرف ترافیک برای هر کاربر (بر اساس UUID).

این اسکریپت:
- استفاده‌ی هر کاربر را از API آمار V2Ray می‌خواند.
- اگر مصرف کاربر از سقف (گیگابایت) بیشتر شود، آن کاربر را غیرفعال می‌کند.

نحوه اجرا: 
    python scripts/limit-traffic.py

پیشنهاد: 
    این را با cron اجرا کنید (مثلاً هر ۵ دقیقه).
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request

# مسیرها
BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
USERS_FILE = os.path.join(BASE, "server", "users.txt")
V2RAY_CONFIG_FILE = os.path.join(BASE, "config", "v2ray-config.json")

# تنظیمات پیش‌فرض
API_HOST = "127.0.0.1"
API_PORT = 10085
DEFAULT_LIMIT_GB = 5.0

# اگر می‌خواهید محدودیت متفاوت باشد، می‌توانید اینجا مقدار را تغییر دهید.
# همچنین می‌توانید برای هر کاربر مقادیر متفاوت وارد کنید (ستون چهارم در users.txt).

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def read_users():
    users = []
    if not os.path.exists(USERS_FILE):
        return users

    with open(USERS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.rstrip("\n")
            if not raw or raw.lstrip().startswith("#"):
                continue
            parts = raw.split(":")
            username = parts[0].strip()
            uuid_val = parts[1].strip() if len(parts) >= 2 else ""
            expiry = parts[2].strip() if len(parts) >= 3 else ""
            limit_gb = None
            if len(parts) >= 4:
                try:
                    limit_gb = float(parts[3])
                except ValueError:
                    limit_gb = None
            users.append({
                "username": username,
                "uuid": uuid_val,
                "expiry": expiry,
                "limit_gb": limit_gb,
                "raw": raw,
            })
    return users


def write_users(users):
    lines = [
        "# لیست کاربران - تولید شده توسط ابزار محدودیت ترافیک",
        "# یوزرنیم:UUID:تاریخ_انقضا:محدودیت_گیگ (اختیاری)",
    ]
    for u in users:
        if u.get("commented"):
            lines.append("# " + u["raw"])
            continue
        parts = [u["username"], u["uuid"], u.get("expiry", "")]
        if u.get("limit_gb") is not None:
            parts.append(str(u["limit_gb"]))
        lines.append(":".join(parts))
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")


def read_v2ray_config():
    if not os.path.exists(V2RAY_CONFIG_FILE):
        return {}
    with open(V2RAY_CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def write_v2ray_config(cfg):
    with open(V2RAY_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")


def get_stat(key):
    url = f"http://{API_HOST}:{API_PORT}/stats?key={urllib.parse.quote(key, safe='')}"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            data = r.read().decode("utf-8").strip()
            if not data:
                return 0
            return int(data)
    except Exception as e:
        print(f"خطا در دریافت آمار برای {key}: {e}")
        return 0


def bytes_to_gb(b):
    return b / (1024 ** 3)


def disable_user_in_config(uuid_val):
    cfg = read_v2ray_config()
    inbounds = cfg.get("inbounds", [])
    if not inbounds:
        return
    clients = inbounds[0].get("settings", {}).get("clients", [])
    clients[:] = [c for c in clients if c.get("id") != uuid_val]
    write_v2ray_config(cfg)


def comment_user(user):
    user["commented"] = True


def main():
    users = read_users()
    if not users:
        print("هیچ کاربری برای بررسی وجود ندارد.")
        return

    for u in users:
        uuid_val = u.get("uuid", "")
        if not UUID_RE.match(uuid_val):
            continue

        limit_gb = u.get("limit_gb") if u.get("limit_gb") is not None else DEFAULT_LIMIT_GB
        down = get_stat(f"user>>>{uuid_val}>>>traffic>>>downlink")
        up = get_stat(f"user>>>{uuid_val}>>>traffic>>>uplink")
        total_gb = bytes_to_gb(down + up)

        print(f"{u['username']} ({uuid_val}): {total_gb:.2f} GB / {limit_gb:.2f} GB")

        if total_gb >= limit_gb:
            print(f"--> محدودیت به پایان رسیده؛ کاربر غیرفعال می‌شود.")
            comment_user(u)
            disable_user_in_config(uuid_val)

    write_users(users)


if __name__ == "__main__":
    main()
