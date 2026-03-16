import os
import subprocess
import uuid
import base64
import json
from datetime import datetime, timedelta

from flask import Flask, render_template, request, redirect, url_for, flash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# مسیر فایل users.txt سرور V2Ray
USERS_FILE = "/workspaces/vpn/server/users.txt"
# مسیر فایل کانفیگ V2Ray
V2RAY_CONFIG_FILE = "/workspaces/vpn/config/v2ray-config.json"
# پوشه خروجی پروفایل کلاینت‌ها
CLIENTS_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "client"))

# تنظیمات ساده برای احراز هویت پنل مدیریت
ADMIN_USERNAME = os.environ.get("VPN_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("VPN_ADMIN_PASS", "change-me")


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
    for u in users:
        if u["username"].lower() == username.lower():
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


def extend_user(username, days):
    username = username.strip()
    users = read_users()
    today = datetime.now().date()
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
    write_users(users)


def read_v2ray_config():
    if not os.path.exists(V2RAY_CONFIG_FILE):
        return {"inbounds": [{"settings": {"clients": []}}]}
    with open(V2RAY_CONFIG_FILE, "r") as f:
        return json.load(f)

def write_v2ray_config(config):
    with open(V2RAY_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

def add_user_to_v2ray_config(username, user_uuid):
    config = read_v2ray_config()
    clients = config["inbounds"][0]["settings"]["clients"]
    # Remove existing user if present
    clients[:] = [c for c in clients if c.get("id") != user_uuid]
    # Add new user
    clients.append({
        "id": user_uuid,
        "alterId": 0,
        "email": username
    })
    write_v2ray_config(config)
    # Reload v2ray
    # subprocess.run(["systemctl", "reload", "v2ray"], check=False)

def remove_user_from_v2ray_config(user_uuid):
    config = read_v2ray_config()
    clients = config["inbounds"][0]["settings"]["clients"]
    clients[:] = [c for c in clients if c.get("id") != user_uuid]
    write_v2ray_config(config)
    # subprocess.run(["systemctl", "reload", "v2ray"], check=False)

def ensure_client_profile(username: str, server_ip: str, user_uuid: str) -> None:
    """Create a client profile if it does not already exist.

    Creates a VMess link for V2Ray using the provided UUID.
    """

    profile_dir = os.path.join(CLIENTS_DIR, username)
    profile_path = os.path.join(profile_dir, "client.txt")
    if os.path.exists(profile_path):
        return

    # Create VMess config
    vmess_config = {
        "v": "2",
        "ps": username,
        "add": server_ip,
        "port": "443",
        "id": user_uuid,
        "aid": "0",
        "net": "tcp",
        "type": "none",
        "host": "",
        "path": "",
        "tls": ""
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


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("VPN_ADMIN_SECRET", "change-this-secret")

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
        users = read_users()
        return render_template("index.html", users=users)

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
        user_uuid = str(uuid.uuid4())
        upsert_user(username, user_uuid, days, limit_gb)
        ensure_client_profile(username, server_ip, user_uuid)
        flash(f"کاربر {username} با انقضای {days} روزه ذخیره شد.", "success")
        return redirect(url_for("index"))

    @app.post("/deactivate/<username>")
    def route_deactivate(username):
        deactivate_user(username)
        flash(f"کاربر {username} غیر فعال شد.", "warning")
        return redirect(url_for("index"))

    @app.post("/delete/<username>")
    def route_delete(username):
        remove_user(username)
        flash(f"کاربر {username} حذف شد.", "danger")
        return redirect(url_for("index"))

    @app.post("/bulk-delete")
    def route_bulk_delete():
        usernames = request.form.getlist("selected_users")
        for username in usernames:
            remove_user(username)
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
        extend_user(username, days)
        flash(f"انقضای کاربر {username} به اندازه {days} روز تمدید شد.", "success")
        return redirect(url_for("index"))

    @app.get("/download/<username>")
    def download_profile(username):
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

