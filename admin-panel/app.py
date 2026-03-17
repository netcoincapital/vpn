import os
import subprocess
import uuid
import base64
import json
import re
from datetime import datetime, timedelta

from flask import Flask, render_template, request, redirect, url_for, flash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))

# مسیرهای نسبی - روی ویندوز و لینوکس کار می‌کنند
USERS_FILE = os.path.join(PROJECT_DIR, "server", "users.txt")
V2RAY_CONFIG_FILE = os.path.join(PROJECT_DIR, "config", "v2ray-config.json")
ACTIVITY_STATS_FILE = os.path.join(PROJECT_DIR, "server", "activity_stats.json")
# لاگ دسترسی V2Ray برای تشخیص کاربران آنلاین
V2RAY_ACCESS_LOG = os.path.join(PROJECT_DIR, "logs", "access.log")
# پوشه خروجی پروفایل کلاینت‌ها
CLIENTS_DIR = os.path.join(PROJECT_DIR, "client")
V2RAY_BIN = os.environ.get("V2RAY_BIN", os.path.join(PROJECT_DIR, "v2ray.exe"))
AUTO_RESTART_V2RAY = os.environ.get("VPN_AUTO_RESTART_V2RAY", "1").lower() in (
    "1",
    "true",
    "yes",
)
ENFORCE_SINGLE_DEVICE = os.environ.get("VPN_ENFORCE_SINGLE_DEVICE", "1").lower() in (
    "1",
    "true",
    "yes",
)
SINGLE_DEVICE_WINDOW_MINUTES = int(os.environ.get("VPN_SINGLE_DEVICE_WINDOW_MIN", "5"))

# تنظیمات ساده برای احراز هویت پنل مدیریت
ADMIN_USERNAME = os.environ.get("VPN_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("VPN_ADMIN_PASS", "change-me")
PROFILE_NAME_PREFIX = os.environ.get("VPN_PROFILE_NAME_PREFIX", "🇫🇮")
PROFILE_NAME_SUFFIX = os.environ.get("VPN_PROFILE_NAME_SUFFIX", "(🟢)")
CLIENT_NETWORK = os.environ.get("VPN_CLIENT_NETWORK", "tcp")
CLIENT_TLS_ENABLED = os.environ.get("VPN_CLIENT_TLS", "0").lower() in ("1", "true", "yes")
CLIENT_HOST = os.environ.get("VPN_CLIENT_HOST", "")
CLIENT_PATH = os.environ.get("VPN_CLIENT_PATH", "")


def load_activity_stats():
    defaults = {"deleted_users": 0, "extended_users": 0}
    if not os.path.exists(ACTIVITY_STATS_FILE):
        return defaults
    try:
        with open(ACTIVITY_STATS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "deleted_users": int(data.get("deleted_users", 0)),
            "extended_users": int(data.get("extended_users", 0)),
        }
    except (OSError, ValueError, TypeError):
        return defaults


def save_activity_stats(stats):
    os.makedirs(os.path.dirname(ACTIVITY_STATS_FILE), exist_ok=True)
    with open(ACTIVITY_STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


def increment_activity_stat(key, amount=1):
    stats = load_activity_stats()
    stats[key] = max(0, int(stats.get(key, 0)) + int(amount))
    save_activity_stats(stats)


def get_user_summary_counts():
    total_users = 0
    active_users = 0
    inactive_users = 0

    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                raw = line.strip()
                if not raw:
                    continue

                # Header comments are ignored.
                if raw.startswith("# لیست کاربران") or raw.startswith("# یوزرنیم"):
                    continue

                if raw.startswith("#"):
                    payload = raw[1:].strip()
                    if payload and ":" in payload:
                        inactive_users += 1
                        total_users += 1
                    continue

                if ":" in raw:
                    active_users += 1
                    total_users += 1

    stats = load_activity_stats()
    return {
        "total_users": total_users,
        "active_users": active_users,
        "inactive_users": inactive_users,
        "deleted_users": stats.get("deleted_users", 0),
        "extended_users": stats.get("extended_users", 0),
    }


def read_users():
    users = []
    if not os.path.exists(USERS_FILE):
        return users

    today = datetime.now().date()
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.rstrip("\n")
            if not raw or raw.lstrip().startswith("#"):
                continue
            parts = raw.split(":")
            username = parts[0].strip()
            uuid_val = parts[1].strip() if len(parts) >= 2 else ""
            expiry_str = parts[2].strip() if len(parts) >= 3 else ""
            limit_gb = None
            if len(parts) >= 4:
                try:
                    limit_gb = float(parts[3].strip())
                except ValueError:
                    limit_gb = None

            expiry_date = None
            status = "unknown"
            try:
                if expiry_str:
                    expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
                    status = "expired" if expiry_date < today else "active"
                else:
                    status = "no-expiry"
            except ValueError:
                status = "invalid-date"

            profile_path = os.path.join(CLIENTS_DIR, username, "client.txt")
            users.append(
                {
                    "username": username,
                    "uuid": uuid_val,
                    "expiry_str": expiry_str,
                    "expiry_date": expiry_date,
                    "status": status,
                    "limit_gb": limit_gb,
                    "raw": raw,
                    "has_profile": os.path.exists(profile_path),
                }
            )
    return users


def get_online_usernames():
    """کاربرانی که در ۵ دقیقه اخیر در لاگ V2Ray فعالیت داشته‌اند آنلاین محسوب می‌شوند."""
    online = set()
    if not os.path.exists(V2RAY_ACCESS_LOG):
        return online

    cutoff = datetime.now() - timedelta(minutes=5)
    try:
        with open(V2RAY_ACCESS_LOG, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                # فرمت لاگ V2Ray:
                # 2026/03/17 10:00:00 accepted tcp:google.com:443 [vmess-in >> direct] email: omid
                if "email:" not in line:
                    continue
                try:
                    date_part = line[:19]  # "2026/03/17 10:00:00"
                    log_time = datetime.strptime(date_part, "%Y/%m/%d %H:%M:%S")
                    if log_time >= cutoff:
                        email_idx = line.index("email:") + len("email:")
                        username = line[email_idx:].strip().split()[0].strip()
                        if username:
                            online.add(username.lower())
                except (ValueError, IndexError):
                    continue
    except OSError:
        pass
    return online


def parse_recent_accepted_ips_by_user(window_minutes=5):
    """Return mapping of username -> set(source_ip) for recent accepted sessions."""
    user_ips = {}
    if not os.path.exists(V2RAY_ACCESS_LOG):
        return user_ips

    cutoff = datetime.now() - timedelta(minutes=window_minutes)
    pattern = re.compile(
        r"^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})\s+([0-9.]+):\d+\s+accepted.*email:\s*(\S+)"
    )

    try:
        with open(V2RAY_ACCESS_LOG, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = pattern.search(line)
                if not m:
                    continue

                try:
                    log_time = datetime.strptime(m.group(1), "%Y/%m/%d %H:%M:%S")
                except ValueError:
                    continue
                if log_time < cutoff:
                    continue

                source_ip = m.group(2).strip()
                username = m.group(3).strip().lower()
                if not username or not source_ip:
                    continue
                user_ips.setdefault(username, set()).add(source_ip)
    except OSError:
        pass

    return user_ips


def enforce_single_device_policy():
    """Disable users that are simultaneously active from more than one source IP."""
    if not ENFORCE_SINGLE_DEVICE:
        return []

    violations = []
    ip_map = parse_recent_accepted_ips_by_user(SINGLE_DEVICE_WINDOW_MINUTES)
    if not ip_map:
        return violations

    users = read_users()
    users_by_name = {u["username"].lower(): u for u in users}

    for username, ips in ip_map.items():
        if len(ips) <= 1:
            continue
        target = users_by_name.get(username)
        if not target:
            continue
        # Skip already disabled users.
        if target.get("raw", "").lstrip().startswith("#"):
            continue

        deactivate_user(target["username"])
        violations.append({"username": target["username"], "ips": sorted(list(ips))})

    if violations:
        restart_v2ray_process()

    return violations


def write_users(users):
    lines = []
    for u in users:
        if u.get("commented"):
            lines.append(f"# {u['raw']}")
        else:
            expiry = u.get("expiry_str") or ""
            limit_gb = u.get("limit_gb")
            if limit_gb is not None:
                lines.append(f"{u['username']}:{u['uuid']}:{expiry}:{limit_gb}")
            else:
                lines.append(f"{u['username']}:{u['uuid']}:{expiry}")
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        f.write("# لیست کاربران - تولید شده توسط پنل مدیریت V2Ray\n")
        f.write("# یوزرنیم:UUID:تاریخ_انقضا:محدودیت_گیگ (اختیاری)\n")
        for line in lines:
            f.write(line + "\n")


def upsert_user(username, uuid_val, days, limit_gb=None):
    username = username.strip()
    users = read_users()
    expiry_date = datetime.now().date() + timedelta(days=days)
    expiry_str = expiry_date.strftime("%Y-%m-%d")

    found = False
    for u in users:
        if u["username"].lower() == username.lower():
            u["uuid"] = uuid_val
            u["expiry_str"] = expiry_str
            u["status"] = "active"
            u["commented"] = False
            u["limit_gb"] = limit_gb
            found = True
            break

    if not found:
        users.append(
            {
                "username": username,
                "uuid": uuid_val,
                "expiry_str": expiry_str,
                "status": "active",
                "limit_gb": limit_gb,
                "raw": f"{username}:{uuid_val}:{expiry_str}:{limit_gb}" if limit_gb is not None else f"{username}:{uuid_val}:{expiry_str}",
            }
        )
    write_users(users)


def get_user_by_username(username):
    username = username.strip().lower()
    for u in read_users():
        if u["username"].strip().lower() == username:
            return u
    return None


def deactivate_user(username):
    username = username.strip()
    users = read_users()
    for u in users:
        if u["username"].lower() == username.lower():
            u["commented"] = True
            remove_user_from_v2ray_config(u["uuid"])
    write_users(users)


def remove_user(username):
    username = username.strip()
    users = read_users()
    new_users = []
    removed = False
    for u in users:
        if u["username"].lower() == username.lower():
            removed = True
            remove_user_from_v2ray_config(u.get("uuid", ""))
            # remove client profile folder
            profile_dir = os.path.join(CLIENTS_DIR, username)
            if os.path.isdir(profile_dir):
                for root, dirs, files in os.walk(profile_dir, topdown=False):
                    for name in files:
                        try:
                            os.remove(os.path.join(root, name))
                        except OSError:
                            pass
                    for name in dirs:
                        try:
                            os.rmdir(os.path.join(root, name))
                        except OSError:
                            pass
                try:
                    os.rmdir(profile_dir)
                except OSError:
                    pass
            continue
        new_users.append(u)
    write_users(new_users)
    return removed


def extend_user(username, days):
    username = username.strip()
    users = read_users()
    today = datetime.now().date()
    extended = False

    for u in users:
        if u["username"].lower() == username.lower():
            try:
                base = (
                    datetime.strptime(u["expiry_str"], "%Y-%m-%d").date()
                    if u["expiry_str"]
                    else today
                )
            except ValueError:
                base = today

            new_expiry = base + timedelta(days=days)
            u["expiry_str"] = new_expiry.strftime("%Y-%m-%d")
            u["status"] = "active"
            u["commented"] = False
            extended = True

    write_users(users)
    return extended


def read_v2ray_config():
    if not os.path.exists(V2RAY_CONFIG_FILE):
        return {"inbounds": [{"settings": {"clients": []}}]}
    with open(V2RAY_CONFIG_FILE, "r") as f:
        return json.load(f)


def get_vmess_inbound(config):
    for inbound in config.get("inbounds", []):
        if inbound.get("protocol") == "vmess":
            return inbound
    return None


def get_vmess_port(config):
    inbound = get_vmess_inbound(config)
    if inbound and inbound.get("port"):
        return str(inbound.get("port"))
    return "443"


def write_v2ray_config(config):
    with open(V2RAY_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def add_user_to_v2ray_config(username, user_uuid):
    config = read_v2ray_config()
    inbound = get_vmess_inbound(config)
    if not inbound:
        return

    settings = inbound.setdefault("settings", {})
    clients = settings.setdefault("clients", [])

    # Remove existing client by id or email, then add the latest one.
    clients[:] = [
        c
        for c in clients
        if c.get("id") != user_uuid and c.get("email", "").lower() != username.lower()
    ]
    clients.append(
        {
            "id": user_uuid,
            "alterId": 0,
            "email": username,
        }
    )
    write_v2ray_config(config)
    # Reload v2ray
    # subprocess.run(["systemctl", "reload", "v2ray"], check=False)


def sync_v2ray_clients_with_users():
    """Rebuild VMess clients list from users.txt so server config is always authoritative."""
    config = read_v2ray_config()
    inbound = get_vmess_inbound(config)
    if not inbound:
        return False

    desired_clients = []
    for user in read_users():
        if not user.get("uuid"):
            continue
        desired_clients.append(
            {
                "id": user["uuid"],
                "alterId": 0,
                "email": user["username"],
            }
        )

    settings = inbound.setdefault("settings", {})
    current_clients = settings.setdefault("clients", [])
    if current_clients == desired_clients:
        return False

    settings["clients"] = desired_clients
    write_v2ray_config(config)
    return True

def remove_user_from_v2ray_config(user_uuid):
    config = read_v2ray_config()
    inbound = get_vmess_inbound(config)
    if not inbound:
        return
    clients = inbound.setdefault("settings", {}).setdefault("clients", [])
    clients[:] = [c for c in clients if c.get("id") != user_uuid]
    write_v2ray_config(config)
    # subprocess.run(["systemctl", "reload", "v2ray"], check=False)

def write_client_profile(username: str, server_ip: str, user_uuid: str) -> None:
    """Create or overwrite VMess client profile and sync V2Ray config."""

    profile_dir = os.path.join(CLIENTS_DIR, username)
    profile_path = os.path.join(profile_dir, "client.txt")

    config = read_v2ray_config()
    vmess_port = get_vmess_port(config)

    profile_display_name = f"{PROFILE_NAME_PREFIX}{username}{PROFILE_NAME_SUFFIX}".strip()
    network = CLIENT_NETWORK if CLIENT_NETWORK in ("tcp", "ws") else "tcp"
    tls_value = "tls" if CLIENT_TLS_ENABLED else ""
    host_value = CLIENT_HOST.strip()
    path_value = CLIENT_PATH.strip()

    # Create VMess config
    vmess_config = {
        "v": "2",
        "ps": profile_display_name,
        "add": server_ip,
        "port": vmess_port,
        "id": user_uuid,
        "aid": "0",
        "net": network,
        "type": "none",
        "host": host_value,
        "path": path_value,
        "tls": tls_value,
    }

    # Encode to base64
    config_json = json.dumps(vmess_config, separators=(',', ':'))
    vmess_link = "vmess://" + base64.b64encode(config_json.encode()).decode()

    # Create profile directory and file
    os.makedirs(profile_dir, exist_ok=True)
    with open(profile_path, "w", encoding="utf-8") as f:
        f.write(vmess_link)

    # Add user to V2Ray config
    add_user_to_v2ray_config(username, user_uuid)

    print(f"Generated VMess link for {username}: {vmess_link}")


def sync_all_client_profiles(default_server_ip="81.214.86.32"):
    """Regenerate all downloadable client profiles from current config/users state."""
    for user in read_users():
        write_client_profile(
            user["username"],
            default_server_ip,
            user["uuid"],
        )


def reconcile_runtime_state(default_server_ip="81.214.86.32"):
    """Keep server config and client files synchronized with users.txt."""
    config_changed = sync_v2ray_clients_with_users()
    sync_all_client_profiles(default_server_ip)
    return config_changed


def restart_v2ray_process():
    """Restart local V2Ray process to apply config changes immediately."""
    if not AUTO_RESTART_V2RAY:
        return False, "auto restart disabled"

    if not os.path.exists(V2RAY_CONFIG_FILE):
        return False, "config file not found"

    try:
        if os.name == "nt":
            # Stop all existing v2ray instances.
            subprocess.run(
                ["taskkill", "/F", "/IM", "v2ray.exe"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            if not os.path.exists(V2RAY_BIN):
                return False, f"v2ray binary not found: {V2RAY_BIN}"

            creationflags = 0x00000008 | 0x00000200 | 0x08000000
            subprocess.Popen(
                [V2RAY_BIN, "run", "-config", V2RAY_CONFIG_FILE],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            return True, "v2ray restarted"

        # Linux/macOS fallback
        subprocess.run(
            ["pkill", "-f", "v2ray"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.Popen(
            ["v2ray", "run", "-config", V2RAY_CONFIG_FILE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True, "v2ray restarted"
    except OSError as exc:
        return False, str(exc)


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("VPN_ADMIN_SECRET", "change-this-secret")

    reconcile_runtime_state()

    @app.before_request
    def basic_auth():
        # اگر می‌خواهیم موقتاً احراز هویت را غیرفعال کنیم (برای تست).
        if os.environ.get("VPN_ADMIN_NOAUTH", "").lower() in ("1", "true", "yes"):
            return

        from flask import request, Response

        auth = request.authorization
        if (
            not auth
            or auth.username != ADMIN_USERNAME
            or auth.password != ADMIN_PASSWORD
        ):
            return Response(
                "Authentication required",
                401,
                {"WWW-Authenticate": 'Basic realm="VPN Admin"'},
            )

    @app.route("/")
    def index():
        violations = enforce_single_device_policy()
        for v in violations:
            flash(
                f"کاربر {v['username']} به دلیل اتصال همزمان از چند دستگاه غیرفعال شد: {', '.join(v['ips'])}",
                "warning",
            )
        users = read_users()
        online_users = get_online_usernames()
        for u in users:
            u["is_online"] = u["username"].lower() in online_users
        return render_template("index.html", users=users)

    @app.get("/stats")
    def stats_page():
        violations = enforce_single_device_policy()
        for v in violations:
            flash(
                f"کاربر {v['username']} به دلیل اتصال همزمان از چند دستگاه غیرفعال شد.",
                "warning",
            )
        summary = get_user_summary_counts()
        return render_template("stats.html", summary=summary)

    @app.post("/add")
    def add():
        username = request.form.get("username", "").strip()
        days_str = request.form.get("days", "30").strip()
        limit_str = request.form.get("limit_gb", "").strip()
        server_ip = request.form.get("server_ip", "81.214.86.32").strip()
        if not username:
            flash("یوزرنیم الزامی است.", "danger")
            return redirect(url_for("index"))
        try:
            days = int(days_str)
            if days <= 0:
                days = 30
        except ValueError:
            days = 30
        limit_gb = None
        if limit_str:
            try:
                limit_gb = float(limit_str)
                if limit_gb <= 0:
                    limit_gb = None
            except ValueError:
                limit_gb = None
        existing_user = get_user_by_username(username)
        user_uuid = existing_user.get("uuid") if existing_user and existing_user.get("uuid") else str(uuid.uuid4())
        upsert_user(username, user_uuid, days, limit_gb)
        write_client_profile(username, server_ip, user_uuid)
        sync_v2ray_clients_with_users()
        restarted, msg = restart_v2ray_process()
        if restarted:
            flash("سرویس V2Ray برای اعمال تغییرات کاربر ری‌استارت شد.", "success")
        else:
            flash(f"تغییرات ذخیره شد، اما ری‌استارت خودکار V2Ray انجام نشد: {msg}", "warning")
        flash(f"کاربر {username} با انقضای {days} روزه ذخیره شد.", "success")
        return redirect(url_for("index"))

    @app.post("/deactivate/<username>")
    def route_deactivate(username):
        deactivate_user(username)
        sync_v2ray_clients_with_users()
        restart_v2ray_process()
        flash(f"کاربر {username} غیر فعال شد.", "warning")
        return redirect(url_for("index"))

    @app.post("/delete/<username>")
    def route_delete(username):
        removed = remove_user(username)
        if removed:
            increment_activity_stat("deleted_users", 1)
        sync_v2ray_clients_with_users()
        restart_v2ray_process()
        flash(f"کاربر {username} حذف شد.", "danger")
        return redirect(url_for("index"))

    @app.post("/bulk-delete")
    def route_bulk_delete():
        usernames = request.form.getlist("selected_users")
        removed_count = 0
        for username in usernames:
            if remove_user(username):
                removed_count += 1
        if removed_count:
            increment_activity_stat("deleted_users", removed_count)
        sync_v2ray_clients_with_users()
        if usernames:
            restart_v2ray_process()
        flash(f"{len(usernames)} کاربر حذف شد.", "danger")
        return redirect(url_for("index"))

    @app.post("/extend/<username>")
    def route_extend(username):
        days_str = request.form.get("days", "30").strip()
        try:
            days = int(days_str)
            if days <= 0:
                days = 30
        except ValueError:
            days = 30
        if extend_user(username, days):
            increment_activity_stat("extended_users", 1)
        sync_all_client_profiles()
        flash(f"انقضای کاربر {username} به اندازه {days} روز تمدید شد.", "success")
        return redirect(url_for("index"))

    @app.get("/download/<username>")
    def download_profile(username):
        user = get_user_by_username(username)
        if user:
            sync_v2ray_clients_with_users()
            write_client_profile(username, "81.214.86.32", user["uuid"])

        profile_path = os.path.join(CLIENTS_DIR, username, "client.txt")
        if not os.path.exists(profile_path):
            flash("برای این کاربر هنوز پروفایل کلاینت ساخته نشده است.", "danger")
            return redirect(url_for("index"))

        from flask import send_file

        return send_file(
            profile_path,
            as_attachment=True,
            download_name=f"{username}.txt",
        )

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("VPN_ADMIN_PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=False)

