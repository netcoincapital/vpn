import os
import subprocess
import uuid
import base64
import json
import re
import shutil
from urllib.parse import quote
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
# تشخیص باینری V2Ray بر اساس سیستم‌عامل
if os.name == "nt":
    _v2ray_default = os.path.join(PROJECT_DIR, "v2ray.exe")
else:
    _v2ray_default = "v2ray"  # روی Linux/Mac از path استفاده کن
V2RAY_BIN = os.environ.get("V2RAY_BIN", _v2ray_default)
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
CLIENT_HEADER_TYPE = os.environ.get("VPN_CLIENT_HEADER_TYPE", "")
PREFERRED_PROFILE_PROTOCOL = os.environ.get("VPN_PROFILE_PROTOCOL", "vless").lower()

# ─── تنظیمات Stealth (V2Ray + WebSocket + TLS) ──────────────────────────────
# این مقادیر بعد از اجرای install-stealth.sh از فایل ws-paths.conf خوانده می‌شوند
_WS_PATHS_FILE = os.path.join(PROJECT_DIR, "server", "ws-paths.conf")

def _load_ws_config() -> dict:
    """خواندن تنظیمات WS+TLS از فایل یا متغیرهای محیطی."""
    cfg = {
        "domain": os.environ.get("STEALTH_DOMAIN", ""),
        "vless_path": os.environ.get("STEALTH_VLESS_PATH", ""),
        "vmess_path": os.environ.get("STEALTH_VMESS_PATH", ""),
    }
    if os.path.exists(_WS_PATHS_FILE):
        try:
            with open(_WS_PATHS_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, _, v = line.partition("=")
                        k, v = k.strip(), v.strip()
                        if k == "STEALTH_DOMAIN" and not cfg["domain"]:
                            cfg["domain"] = v
                        elif k == "STEALTH_VLESS_PATH" and not cfg["vless_path"]:
                            cfg["vless_path"] = v
                        elif k == "STEALTH_VMESS_PATH" and not cfg["vmess_path"]:
                            cfg["vmess_path"] = v
        except OSError:
            pass
    return cfg

STEALTH_CONFIG = _load_ws_config()

# ─── تنظیمات OpenVPN Stealth (Stunnel) ──────────────────────────────────────
_OVPN_STEALTH_FILE = os.path.join(PROJECT_DIR, "server", "ovpn-stealth.conf")

def _load_stunnel_config() -> dict:
    """خواندن تنظیمات Stunnel از فایل یا متغیرهای محیطی."""
    cfg = {
        "enabled": os.environ.get("STUNNEL_ENABLED", "0") == "1",
        "port": os.environ.get("STUNNEL_PORT", "8443"),
        "tls_crypt_key": os.environ.get("TLS_CRYPT_KEY", "/etc/openvpn/server/tls-crypt.key"),
        "server_ip": os.environ.get("OPENVPN_SERVER_IP", ""),
    }
    if os.path.exists(_OVPN_STEALTH_FILE):
        try:
            with open(_OVPN_STEALTH_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, _, v = line.partition("=")
                        k, v = k.strip(), v.strip()
                        if k == "STUNNEL_ENABLED" and not cfg["enabled"]:
                            cfg["enabled"] = v == "1"
                        elif k == "STUNNEL_PORT":
                            cfg["port"] = v
                        elif k == "TLS_CRYPT_KEY":
                            cfg["tls_crypt_key"] = v
                        elif k == "SERVER_IP" and not cfg["server_ip"]:
                            cfg["server_ip"] = v
        except OSError:
            pass
    return cfg

STUNNEL_CONFIG = _load_stunnel_config()

# ─── تنظیمات OpenVPN ────────────────────────────────────────────────────────
OPENVPN_USERS_FILE = os.path.join(PROJECT_DIR, "server", "openvpn-users.txt")
OPENVPN_CLIENTS_DIR = os.path.join(PROJECT_DIR, "client", "openvpn")
OPENVPN_PKI_DIR = os.environ.get("OPENVPN_PKI_DIR", "/etc/openvpn/easy-rsa/pki")
OPENVPN_SERVER_DIR = os.environ.get("OPENVPN_SERVER_DIR", "/etc/openvpn/server")
OPENVPN_EASYRSA_DIR = os.environ.get("OPENVPN_EASYRSA_DIR", "/etc/openvpn/easy-rsa")
OPENVPN_SERVER_IP = os.environ.get("OPENVPN_SERVER_IP", "")
OPENVPN_PORT = os.environ.get("OPENVPN_PORT", "1194")
OPENVPN_PROTO = os.environ.get("OPENVPN_PROTO", "udp")
# regex اعتبارسنجی نام کاربری — فقط حروف، اعداد، خط تیره، آندرلاین
_USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')

# ─── تنظیمات OpenVPN ────────────────────────────────────────────────────────
OPENVPN_USERS_FILE = os.path.join(PROJECT_DIR, "server", "openvpn-users.txt")
OPENVPN_CLIENTS_DIR = os.path.join(PROJECT_DIR, "client", "openvpn")
OPENVPN_PKI_DIR = os.environ.get("OPENVPN_PKI_DIR", "/etc/openvpn/easy-rsa/pki")
OPENVPN_SERVER_DIR = os.environ.get("OPENVPN_SERVER_DIR", "/etc/openvpn/server")
OPENVPN_EASYRSA_DIR = os.environ.get("OPENVPN_EASYRSA_DIR", "/etc/openvpn/easy-rsa")
OPENVPN_SERVER_IP = os.environ.get("OPENVPN_SERVER_IP", "")
OPENVPN_PORT = os.environ.get("OPENVPN_PORT", "1194")
OPENVPN_PROTO = os.environ.get("OPENVPN_PROTO", "udp")
# regex اعتبارسنجی نام کاربری — فقط حروف، اعداد، خط تیره، آندرلاین
_USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')


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


def get_inbound_by_protocol(config, protocol_name):
    for inbound in config.get("inbounds", []):
        if inbound.get("protocol") == protocol_name:
            return inbound
    return None


def get_vmess_inbound(config):
    return get_inbound_by_protocol(config, "vmess")


def get_vless_inbound(config):
    return get_inbound_by_protocol(config, "vless")


def get_inbound_port(config, protocol_name, fallback_port="443"):
    inbound = get_inbound_by_protocol(config, protocol_name)
    if inbound and inbound.get("port"):
        return str(inbound.get("port"))
    return fallback_port


def get_vmess_port(config):
    return get_inbound_port(config, "vmess", "443")


def get_stream_profile(inbound):
    if not inbound:
        return {
            "network": "tcp",
            "tls": "",
            "header_type": "none",
            "host": "",
            "path": "",
        }

    stream = inbound.get("streamSettings", {})
    network = stream.get("network", "tcp")
    security = stream.get("security", "none")
    tls_value = "tls" if security == "tls" else ""

    header_type = "none"
    host_value = ""
    path_value = ""

    if network == "tcp":
        tcp_settings = stream.get("tcpSettings", {})
        header = tcp_settings.get("header", {})
        header_type = header.get("type", "none")

        request = header.get("request", {}) if header_type == "http" else {}
        headers = request.get("headers", {})
        host = headers.get("Host", "")
        if isinstance(host, list):
            host_value = host[0] if host else ""
        elif isinstance(host, str):
            host_value = host

        path = request.get("path", "")
        if isinstance(path, list):
            path_value = path[0] if path else ""
        elif isinstance(path, str):
            path_value = path

    return {
        "network": network,
        "tls": tls_value,
        "header_type": header_type,
        "host": host_value,
        "path": path_value,
    }


def get_vmess_stream_profile(config):
    return get_stream_profile(get_vmess_inbound(config))


def get_vless_stream_profile(config):
    return get_stream_profile(get_vless_inbound(config))


def write_v2ray_config(config):
    with open(V2RAY_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def add_user_to_v2ray_config(username, user_uuid):
    config = read_v2ray_config()
    changed = False

    vmess_inbound = get_vmess_inbound(config)
    if vmess_inbound:
        settings = vmess_inbound.setdefault("settings", {})
        clients = settings.setdefault("clients", [])
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
        changed = True

    vless_inbound = get_vless_inbound(config)
    if vless_inbound:
        settings = vless_inbound.setdefault("settings", {})
        clients = settings.setdefault("clients", [])
        clients[:] = [
            c
            for c in clients
            if c.get("id") != user_uuid and c.get("email", "").lower() != username.lower()
        ]
        clients.append(
            {
                "id": user_uuid,
                "email": username,
                "decryption": "none",
            }
        )
        changed = True

    if not changed:
        return

    write_v2ray_config(config)
    # Reload v2ray
    # subprocess.run(["systemctl", "reload", "v2ray"], check=False)


def sync_v2ray_clients_with_users():
    """Rebuild VMess/VLESS clients list from users.txt so server config is authoritative."""
    config = read_v2ray_config()
    vmess_inbound = get_vmess_inbound(config)
    vless_inbound = get_vless_inbound(config)
    if not vmess_inbound and not vless_inbound:
        return False

    desired_vmess_clients = []
    desired_vless_clients = []
    for user in read_users():
        if not user.get("uuid"):
            continue
        desired_vmess_clients.append(
            {
                "id": user["uuid"],
                "alterId": 0,
                "email": user["username"],
            }
        )
        desired_vless_clients.append(
            {
                "id": user["uuid"],
                "email": user["username"],
                "decryption": "none",
            }
        )

    changed = False

    if vmess_inbound:
        settings = vmess_inbound.setdefault("settings", {})
        current_clients = settings.setdefault("clients", [])
        if current_clients != desired_vmess_clients:
            settings["clients"] = desired_vmess_clients
            changed = True

    if vless_inbound:
        settings = vless_inbound.setdefault("settings", {})
        current_clients = settings.setdefault("clients", [])
        if current_clients != desired_vless_clients:
            settings["clients"] = desired_vless_clients
            changed = True

    if not changed:
        return False

    write_v2ray_config(config)
    return True

def remove_user_from_v2ray_config(user_uuid):
    config = read_v2ray_config()
    changed = False
    for inbound in (get_vmess_inbound(config), get_vless_inbound(config)):
        if not inbound:
            continue
        clients = inbound.setdefault("settings", {}).setdefault("clients", [])
        before = len(clients)
        clients[:] = [c for c in clients if c.get("id") != user_uuid]
        if len(clients) != before:
            changed = True

    if not changed:
        return

    write_v2ray_config(config)
    # subprocess.run(["systemctl", "reload", "v2ray"], check=False)

def write_client_profile(username: str, server_ip: str, user_uuid: str) -> None:
    """Create or overwrite VMess/VLESS client profile and sync V2Ray config."""

    profile_dir = os.path.join(CLIENTS_DIR, username)
    profile_path = os.path.join(profile_dir, "client.txt")

    config = read_v2ray_config()
    vmess_port = get_vmess_port(config)
    vless_port = get_inbound_port(config, "vless", vmess_port)
    stream_profile = get_vmess_stream_profile(config)

    profile_display_name = f"{PROFILE_NAME_PREFIX}{username}{PROFILE_NAME_SUFFIX}".strip()
    network = CLIENT_NETWORK if CLIENT_NETWORK in ("tcp", "ws") else stream_profile["network"]
    network = network if network in ("tcp", "ws") else "tcp"
    tls_value = "tls" if CLIENT_TLS_ENABLED else stream_profile["tls"]
    host_value = CLIENT_HOST.strip() if CLIENT_HOST.strip() else stream_profile["host"]
    path_value = CLIENT_PATH.strip() if CLIENT_PATH.strip() else stream_profile["path"]
    header_type = CLIENT_HEADER_TYPE.strip() if CLIENT_HEADER_TYPE.strip() else stream_profile["header_type"]
    header_type = header_type if header_type in ("none", "http") else "none"

    vmess_config = {
        "v": "2",
        "ps": profile_display_name,
        "add": server_ip,
        "port": vmess_port,
        "id": user_uuid,
        "aid": "0",
        "net": network,
        "type": header_type,
        "host": host_value,
        "path": path_value,
        "tls": tls_value,
    }

    config_json = json.dumps(vmess_config, separators=(',', ':'))
    vmess_link = "vmess://" + base64.b64encode(config_json.encode()).decode()

    vless_query_items = [
        ("encryption", "none"),
        ("security", tls_value if tls_value else "none"),
        ("type", network),
    ]
    if host_value:
        vless_query_items.append(("host", host_value))
    if header_type and header_type != "none":
        vless_query_items.append(("headerType", header_type))
    if path_value:
        vless_query_items.append(("path", path_value))

    vless_query = "&".join([f"{k}={quote(str(v), safe='')}" for k, v in vless_query_items])
    vless_link = (
        f"vless://{user_uuid}@{server_ip}:{vless_port}?{vless_query}"
        f"#{quote(profile_display_name, safe='')}"
    )

    links = [vmess_link, vless_link]
    if PREFERRED_PROFILE_PROTOCOL == "vless":
        links = [vless_link, vmess_link]

    os.makedirs(profile_dir, exist_ok=True)
    with open(profile_path, "w", encoding="utf-8") as f:
        f.write("\n".join(links))

    # Add user to V2Ray config
    add_user_to_v2ray_config(username, user_uuid)

    print(f"Generated profiles for {username}: {links[0]}")


def build_stealth_links(username: str, user_uuid: str) -> list:
    """ساخت لینک‌های VLESS/VMess با WebSocket + TLS (Stealth Mode).
    
    این لینک‌ها ترافیک را داخل HTTPS پنهان می‌کنند و برای
    فیلترینگ DPI شبیه بازدید از یک وب‌سایت عادی به نظر می‌رسند.
    """
    ws = STEALTH_CONFIG
    domain = ws.get("domain", "")
    vless_path = ws.get("vless_path", "")
    vmess_path = ws.get("vmess_path", "")

    if not domain:
        return []

    links = []
    profile_name = f"{PROFILE_NAME_PREFIX}{username}🔒{PROFILE_NAME_SUFFIX}".strip()

    # ── VLESS + WS + TLS ──────────────────────────────────────────
    if vless_path:
        vless_params = "&".join([
            "encryption=none",
            "security=tls",
            "type=ws",
            f"host={quote(domain, safe='')}",
            f"path={quote(vless_path, safe='')}",
            "fp=chrome",          # fingerprint مرورگر Chrome
            "alpn=h2%2Chttp%2F1.1",
        ])
        vless_stealth = (
            f"vless://{user_uuid}@{domain}:443"
            f"?{vless_params}"
            f"#{quote(profile_name + ' [Stealth]', safe='')}"
        )
        links.append(vless_stealth)

    # ── VMess + WS + TLS ──────────────────────────────────────────
    if vmess_path:
        vmess_obj = {
            "v": "2",
            "ps": profile_name + " [Stealth]",
            "add": domain,
            "port": "443",
            "id": user_uuid,
            "aid": "0",
            "net": "ws",
            "type": "none",
            "host": domain,
            "path": vmess_path,
            "tls": "tls",
        }
        import json as _json
        vmess_stealth = "vmess://" + base64.b64encode(
            _json.dumps(vmess_obj, separators=(",", ":")).encode()
        ).decode()
        links.append(vmess_stealth)

    return links


def write_stealth_profile(username: str, user_uuid: str) -> bool:
    """ذخیره پروفایل Stealth در client/<username>/stealth.txt."""
    links = build_stealth_links(username, user_uuid)
    if not links:
        return False
    profile_dir = os.path.join(CLIENTS_DIR, username)
    os.makedirs(profile_dir, exist_ok=True)
    stealth_path = os.path.join(profile_dir, "stealth.txt")
    with open(stealth_path, "w", encoding="utf-8") as f:
        f.write("\n".join(links))
    return True


def sync_all_client_profiles(default_server_ip="81.214.86.32"):
    """Regenerate all downloadable client profiles from current config/users state."""
    for user in read_users():
        write_client_profile(
            user["username"],
            default_server_ip,
            user["uuid"],
        )
        write_stealth_profile(user["username"], user["uuid"])


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
            [V2RAY_BIN, "run", "-config", V2RAY_CONFIG_FILE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True, "v2ray restarted"
    except OSError as exc:
        return False, str(exc)


# ══════════════════════════════════════════════════════════════════════════════
#  OpenVPN — توابع کمکی
# ══════════════════════════════════════════════════════════════════════════════

def _validate_ovpn_username(username: str) -> bool:
    """بررسی می‌کند که نام کاربر فقط شامل کاراکترهای مجاز است (جلوگیری از command injection)."""
    return bool(_USERNAME_PATTERN.match(username))


def openvpn_is_installed() -> bool:
    """بررسی وجود PKI و فایل‌های گواهی OpenVPN."""
    ca_path = os.path.join(OPENVPN_PKI_DIR, "ca.crt")
    ta_path = os.path.join(OPENVPN_SERVER_DIR, "ta.key")
    easyrsa = os.path.join(OPENVPN_EASYRSA_DIR, "easyrsa")
    return os.path.exists(ca_path) and os.path.exists(ta_path) and os.path.exists(easyrsa)


def read_openvpn_users() -> list:
    """خواندن فایل openvpn-users.txt و برگرداندن لیست دیکشنری‌های کاربران."""
    users = []
    if not os.path.exists(OPENVPN_USERS_FILE):
        return users

    today = datetime.now().date()
    with open(OPENVPN_USERS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.rstrip("\n")
            if not raw or raw.lstrip().startswith("#"):
                continue
            parts = raw.split(":")
            username = parts[0].strip()
            expiry_str = parts[1].strip() if len(parts) >= 2 else ""
            limit_gb = None
            if len(parts) >= 3:
                try:
                    limit_gb = float(parts[2].strip())
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

            ovpn_path = os.path.join(OPENVPN_CLIENTS_DIR, f"{username}.ovpn")
            users.append({
                "username": username,
                "expiry_str": expiry_str,
                "expiry_date": expiry_date,
                "status": status,
                "limit_gb": limit_gb,
                "raw": raw,
                "has_config": os.path.exists(ovpn_path),
            })
    return users


def write_openvpn_users(users: list) -> None:
    """نوشتن لیست کاربران در فایل openvpn-users.txt."""
    os.makedirs(os.path.dirname(OPENVPN_USERS_FILE), exist_ok=True)
    lines = []
    for u in users:
        if u.get("commented"):
            lines.append(f"# {u['raw']}")
        else:
            expiry = u.get("expiry_str") or ""
            limit_gb = u.get("limit_gb")
            if limit_gb is not None:
                lines.append(f"{u['username']}:{expiry}:{limit_gb}")
            else:
                lines.append(f"{u['username']}:{expiry}")
    with open(OPENVPN_USERS_FILE, "w", encoding="utf-8") as f:
        f.write("# لیست کاربران OpenVPN - تولید شده توسط پنل مدیریت\n")
        f.write("# یوزرنیم:تاریخ_انقضا:محدودیت_گیگ (اختیاری)\n")
        for line in lines:
            f.write(line + "\n")


def get_openvpn_user(username: str):
    """پیدا کردن کاربر OpenVPN با نام کاربری."""
    username = username.strip().lower()
    for u in read_openvpn_users():
        if u["username"].strip().lower() == username:
            return u
    return None


def _run_easyrsa(args: list, timeout: int = 120):
    """اجرای دستور easyrsa با امنیت کامل."""
    easyrsa_bin = os.path.join(OPENVPN_EASYRSA_DIR, "easyrsa")
    if not os.path.exists(easyrsa_bin):
        return False, f"easyrsa پیدا نشد: {easyrsa_bin}"
    try:
        env = os.environ.copy()
        env["EASYRSA_BATCH"] = "1"
        env["EASYRSA_PKI"] = OPENVPN_PKI_DIR
        # اگر vars در PKI وجود دارد، صریحاً به آن اشاره می‌کنیم تا تداخل با vars در base dir برطرف شود
        pki_vars = os.path.join(OPENVPN_PKI_DIR, "vars")
        if os.path.exists(pki_vars):
            env["EASYRSA_VARS_FILE"] = pki_vars
        result = subprocess.run(
            [easyrsa_bin] + args,
            cwd=OPENVPN_EASYRSA_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return True, result.stdout
        return False, result.stderr or result.stdout
    except subprocess.TimeoutExpired:
        return False, "دستور easyrsa time-out شد"
    except OSError as exc:
        return False, str(exc)


def generate_openvpn_client_cert(username: str):
    """ساخت گواهی کلاینت با EasyRSA برای کاربر داده‌شده."""
    if not _validate_ovpn_username(username):
        return False, "نام کاربری نامعتبر است"

    cert_path = os.path.join(OPENVPN_PKI_DIR, "issued", f"{username}.crt")
    key_path = os.path.join(OPENVPN_PKI_DIR, "private", f"{username}.key")

    # اگر گواهی قبلاً وجود دارد، ابتدا revoke کن
    if os.path.exists(cert_path) or os.path.exists(key_path):
        _run_easyrsa(["revoke", username])
        for path in (cert_path, key_path,
                     os.path.join(OPENVPN_PKI_DIR, "reqs", f"{username}.req")):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    ok, msg = _run_easyrsa(["gen-req", username, "nopass"])
    if not ok:
        return False, f"خطا در gen-req: {msg}"

    ok, msg = _run_easyrsa(["sign-req", "client", username])
    if not ok:
        return False, f"خطا در sign-req: {msg}"

    return True, "گواهی با موفقیت ساخته شد"


def revoke_openvpn_client_cert(username: str):
    """ابطال گواهی کلاینت و به‌روزرسانی CRL."""
    if not _validate_ovpn_username(username):
        return False, "نام کاربری نامعتبر است"
    ok, msg = _run_easyrsa(["revoke", username])
    if not ok:
        return False, f"خطا در revoke: {msg}"
    _run_easyrsa(["gen-crl"])
    return True, "گواهی ابطال شد"


def _read_file_content(path: str) -> str:
    """خواندن محتوای فایل به صورت امن."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def build_ovpn_config(username: str, server_ip: str):
    """ساخت فایل .ovpn کامل با گواهی‌های Embed شده برای کاربر."""
    if not _validate_ovpn_username(username):
        return None

    ca_path = os.path.join(OPENVPN_PKI_DIR, "ca.crt")
    cert_path = os.path.join(OPENVPN_PKI_DIR, "issued", f"{username}.crt")
    key_path = os.path.join(OPENVPN_PKI_DIR, "private", f"{username}.key")
    ta_path = os.path.join(OPENVPN_SERVER_DIR, "ta.key")

    for path in (ca_path, cert_path, key_path, ta_path):
        if not os.path.exists(path):
            return None

    ca_content = _read_file_content(ca_path)
    ta_content = _read_file_content(ta_path)

    # استخراج بخش گواهی از فایل .crt (ممکن است سربرگ‌های اضافی داشته باشد)
    cert_content = _read_file_content(cert_path)
    cert_match = re.search(
        r"(-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----)",
        cert_content,
        re.DOTALL,
    )
    cert_clean = cert_match.group(1) if cert_match else cert_content

    key_content = _read_file_content(key_path)

    ovpn = (
        f"# کانفیگ OpenVPN برای کاربر: {username}\n"
        f"# تولید شده توسط پنل مدیریت VPN\n"
        f"client\n"
        f"dev tun\n"
        f"proto {OPENVPN_PROTO}\n"
        f"remote {server_ip} {OPENVPN_PORT}\n"
        f"resolv-retry infinite\n"
        f"nobind\n"
        f"persist-key\n"
        f"persist-tun\n"
        f"cipher AES-256-GCM\n"
        f"auth SHA256\n"
        f"tls-client\n"
        f"tls-version-min 1.2\n"
        f"key-direction 1\n"
        f"verb 3\n\n"
        f"<ca>\n{ca_content}\n</ca>\n\n"
        f"<cert>\n{cert_clean}\n</cert>\n\n"
        f"<key>\n{key_content}\n</key>\n\n"
        f"<tls-auth>\n{ta_content}\n</tls-auth>\n"
    )
    return ovpn


def build_ovpn_stunnel_config(username: str) -> str | None:
    """ساخت پروفایل OpenVPN+Stunnel — ترافیک از طریق TLS روی پورت 8443 هدایت می‌شود."""
    if not _validate_ovpn_username(username):
        return None

    sc = STUNNEL_CONFIG
    if not sc.get("enabled"):
        return None

    ca_path = os.path.join(OPENVPN_PKI_DIR, "ca.crt")
    cert_path = os.path.join(OPENVPN_PKI_DIR, "issued", f"{username}.crt")
    key_path = os.path.join(OPENVPN_PKI_DIR, "private", f"{username}.key")
    tls_crypt_path = sc.get("tls_crypt_key", "/etc/openvpn/server/tls-crypt.key")

    for path in (ca_path, cert_path, key_path):
        if not os.path.exists(path):
            return None

    ca_content = _read_file_content(ca_path)
    cert_content = _read_file_content(cert_path)
    cert_match = re.search(
        r"(-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----)",
        cert_content, re.DOTALL,
    )
    cert_clean = cert_match.group(1) if cert_match else cert_content
    key_content = _read_file_content(key_path)

    server_ip = sc.get("server_ip") or OPENVPN_SERVER_IP or "YOUR_SERVER_IP"
    stunnel_port = sc.get("port", "8443")

    # اگر کلید tls-crypt موجود است، آن را embed کنیم
    tls_crypt_block = ""
    if os.path.exists(tls_crypt_path):
        tls_crypt_content = _read_file_content(tls_crypt_path)
        tls_crypt_block = f"\n<tls-crypt>\n{tls_crypt_content}\n</tls-crypt>\n"

    ovpn = (
        f"# OpenVPN + Stunnel (Stealth) — کاربر: {username}\n"
        f"# ترافیک داخل TLS روی پورت {stunnel_port} — ضد فیلترینگ هوشمند\n"
        f"# نیاز به نصب Stunnel روی کلاینت: stunnel.net\n"
        f"#\n"
        f"# ── راهنمای اتصال ──────────────────────────────────────────\n"
        f"# ۱. فایل stunnel-client.conf را از پنل دانلود و Stunnel را نصب کنید\n"
        f"# ۲. Stunnel را اجرا کنید (پورت 1195 محلی → سرور:8443)\n"
        f"# ۳. این فایل .ovpn را در OpenVPN Connect باز کنید\n"
        f"# ──────────────────────────────────────────────────────────\n"
        f"client\n"
        f"dev tun\n"
        f"proto tcp\n"
        f"remote 127.0.0.1 1195\n"
        f"resolv-retry infinite\n"
        f"nobind\n"
        f"persist-key\n"
        f"persist-tun\n"
        f"cipher AES-256-GCM\n"
        f"auth SHA256\n"
        f"tls-client\n"
        f"tls-version-min 1.2\n"
        f"key-direction 1\n"
        f"# ضد fingerprinting\n"
        f"tls-cipher TLS-ECDHE-RSA-WITH-AES-256-GCM-SHA384\n"
        f"reneg-sec 0\n"
        f"verb 3\n\n"
        f"<ca>\n{ca_content}\n</ca>\n\n"
        f"<cert>\n{cert_clean}\n</cert>\n\n"
        f"<key>\n{key_content}\n</key>\n"
        f"{tls_crypt_block}"
    )

    # فایل config Stunnel کلاینت را هم می‌سازیم
    stunnel_client = (
        f"; Stunnel Client Config — OpenVPN Stealth\n"
        f"; این فایل را در مسیر Stunnel قرار دهید\n"
        f"; Windows: C:\\Program Files (x86)\\stunnel\\config\\stunnel.conf\n"
        f"; Linux/Mac: /etc/stunnel/stunnel.conf\n\n"
        f"[openvpn-stealth]\n"
        f"client = yes\n"
        f"accept  = 127.0.0.1:1195\n"
        f"connect = {server_ip}:{stunnel_port}\n"
        f"verify = 0\n"
        f"; برای امنیت بیشتر، گواهی سرور را verify کنید:\n"
        f"; CAfile = /path/to/stunnel-server.crt\n"
        f"; verify = 2\n"
    )

    return ovpn, stunnel_client


def write_openvpn_client_config(username: str, server_ip: str) -> bool:
    """نوشتن فایل .ovpn کلاینت در پوشه client/openvpn/."""
    if not _validate_ovpn_username(username):
        return False
    ovpn_content = build_ovpn_config(username, server_ip)
    if ovpn_content is None:
        return False
    os.makedirs(OPENVPN_CLIENTS_DIR, exist_ok=True)
    out_path = os.path.join(OPENVPN_CLIENTS_DIR, f"{username}.ovpn")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(ovpn_content)
    return True


def create_openvpn_user(username: str, days: int, limit_gb=None, server_ip: str = ""):
    """ایجاد کاربر جدید OpenVPN: ثبت در فایل + ساخت گواهی + ساخت .ovpn."""
    if not _validate_ovpn_username(username):
        return False, "نام کاربری نامعتبر است (فقط A-Z, 0-9, _ و - مجاز هستند)"

    if openvpn_is_installed():
        ok, msg = generate_openvpn_client_cert(username)
        if not ok:
            return False, msg

    users = read_openvpn_users()
    expiry_str = ""
    if days > 0:
        expiry_str = (datetime.now().date() + timedelta(days=days)).strftime("%Y-%m-%d")

    raw_line = f"{username}:{expiry_str}:{limit_gb}" if limit_gb is not None else f"{username}:{expiry_str}"
    found = False
    for u in users:
        if u["username"].lower() == username.lower():
            u["expiry_str"] = expiry_str
            u["limit_gb"] = limit_gb
            u["commented"] = False
            u["raw"] = raw_line
            found = True
            break
    if not found:
        users.append({
            "username": username,
            "expiry_str": expiry_str,
            "limit_gb": limit_gb,
            "commented": False,
            "raw": raw_line,
        })
    write_openvpn_users(users)

    effective_ip = server_ip or OPENVPN_SERVER_IP or "YOUR_SERVER_IP"
    if openvpn_is_installed():
        write_openvpn_client_config(username, effective_ip)

    return True, f"کاربر {username} با موفقیت ایجاد شد"


def deactivate_openvpn_user(username: str) -> bool:
    """غیرفعال‌سازی کاربر OpenVPN (comment کردن در فایل + ابطال گواهی)."""
    if not _validate_ovpn_username(username):
        return False
    users = read_openvpn_users()
    found = False
    for u in users:
        if u["username"].lower() == username.lower():
            u["commented"] = True
            found = True
            break
    if found:
        write_openvpn_users(users)
        if openvpn_is_installed():
            revoke_openvpn_client_cert(username)
    return found


def delete_openvpn_user(username: str) -> bool:
    """حذف کامل کاربر OpenVPN از فایل + ابطال گواهی + حذف .ovpn."""
    if not _validate_ovpn_username(username):
        return False
    users = read_openvpn_users()
    new_users = [u for u in users if u["username"].lower() != username.lower()]
    removed = len(new_users) < len(users)
    if removed:
        write_openvpn_users(new_users)
        if openvpn_is_installed():
            revoke_openvpn_client_cert(username)
        ovpn_path = os.path.join(OPENVPN_CLIENTS_DIR, f"{username}.ovpn")
        if os.path.exists(ovpn_path):
            os.remove(ovpn_path)
    return removed


def extend_openvpn_user(username: str, days: int) -> bool:
    """تمدید انقضای کاربر OpenVPN."""
    if not _validate_ovpn_username(username):
        return False
    users = read_openvpn_users()
    today = datetime.now().date()
    extended = False
    for u in users:
        if u["username"].lower() == username.lower():
            try:
                base = datetime.strptime(u["expiry_str"], "%Y-%m-%d").date() if u["expiry_str"] else today
            except ValueError:
                base = today
            u["expiry_str"] = (base + timedelta(days=days)).strftime("%Y-%m-%d")
            u["commented"] = False
            extended = True
            break
    if extended:
        write_openvpn_users(users)
    return extended


def get_openvpn_summary() -> dict:
    """خلاصه آمار کاربران OpenVPN."""
    total = active = inactive = 0
    if os.path.exists(OPENVPN_USERS_FILE):
        with open(OPENVPN_USERS_FILE, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                raw = line.strip()
                if not raw or raw.startswith("# لیست") or raw.startswith("# یوزر"):
                    continue
                if raw.startswith("#"):
                    payload = raw[1:].strip()
                    if payload and ":" in payload:
                        inactive += 1
                        total += 1
                    continue
                if ":" in raw:
                    active += 1
                    total += 1
    return {"total": total, "active": active, "inactive": inactive}


def get_openvpn_online_usernames() -> set:
    """خواندن فایل status سرور OpenVPN و برگرداندن نام کاربران متصل."""
    online = set()
    # مسیرهای احتمالی فایل status
    status_paths = [
        "/run/openvpn-server/status-server.log",
        "/var/log/openvpn/openvpn-status.log",
        os.path.join(OPENVPN_SERVER_DIR, "openvpn-status.log"),
    ]
    for path in status_paths:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    # فرمت version 2: CLIENT_LIST,commonname,real_addr,...
                    if line.startswith("CLIENT_LIST,"):
                        parts = line.strip().split(",")
                        if len(parts) >= 2:
                            cn = parts[1].strip().lower()
                            if cn:
                                online.add(cn)
        except OSError:
            pass
        break  # اولین فایلی که پیدا شد کافی است
    return online


def restart_openvpn_service():
    """ری‌استارت سرویس OpenVPN برای اعمال CRL به‌روز شده."""
    try:
        result = subprocess.run(
            ["systemctl", "reload-or-restart", "openvpn-server@server"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return True, "سرویس OpenVPN ری‌استارت شد"
        return False, result.stderr.strip() or "خطا در ری‌استارت"
    except (OSError, subprocess.TimeoutExpired) as exc:
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
            # بررسی وجود پروفایل stealth
            stealth_path = os.path.join(CLIENTS_DIR, u["username"], "stealth.txt")
            u["has_stealth"] = os.path.exists(stealth_path)
        ovpn_users = read_openvpn_users()
        ovpn_online = get_openvpn_online_usernames()
        for u in ovpn_users:
            u["is_online"] = u["username"].lower() in ovpn_online
        ws = STEALTH_CONFIG
        return render_template(
            "index.html",
            users=users,
            ovpn_users=ovpn_users,
            ovpn_installed=openvpn_is_installed(),
            ovpn_server_ip=OPENVPN_SERVER_IP or "",
            stealth_enabled=bool(ws.get("domain")),
            stealth_domain=ws.get("domain", ""),
            stunnel_enabled=bool(STUNNEL_CONFIG.get("enabled")),
            stunnel_port=STUNNEL_CONFIG.get("port", "8443"),
        )

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
            write_stealth_profile(username, user["uuid"])

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

    @app.get("/download-stealth/<username>")
    def download_stealth_profile(username):
        """دانلود پروفایل Stealth (WS+TLS) برای کاربر."""
        from flask import send_file as _sf

        user = get_user_by_username(username)
        if not user:
            flash("کاربر پیدا نشد.", "danger")
            return redirect(url_for("index"))

        write_stealth_profile(username, user["uuid"])
        stealth_path = os.path.join(CLIENTS_DIR, username, "stealth.txt")

        if not os.path.exists(stealth_path):
            flash("پروفایل Stealth برای این کاربر موجود نیست. ابتدا install-stealth.sh را اجرا کنید.", "warning")
            return redirect(url_for("index"))

        return _sf(
            stealth_path,
            as_attachment=True,
            download_name=f"{username}-stealth.txt",
        )

    # ──────────────────────────────────────────────────────────────────────────
    #  مسیرهای OpenVPN
    # ──────────────────────────────────────────────────────────────────────────

    @app.get("/openvpn")
    def openvpn_page():
        users = read_openvpn_users()
        installed = openvpn_is_installed()
        summary = get_openvpn_summary()
        return render_template(
            "openvpn.html",
            users=users,
            installed=installed,
            summary=summary,
            server_ip=OPENVPN_SERVER_IP or "",
        )

    @app.post("/openvpn/add")
    def openvpn_add():
        from flask import send_file as _sf

        username = request.form.get("username", "").strip()
        days_str = request.form.get("days", "30").strip()
        limit_str = request.form.get("limit_gb", "").strip()
        server_ip = request.form.get("server_ip", OPENVPN_SERVER_IP or "").strip()

        if not username:
            flash("یوزرنیم الزامی است.", "danger")
            return redirect(url_for("index") + "?tab=openvpn")

        if not _validate_ovpn_username(username):
            flash("یوزرنیم نامعتبر است — فقط حروف انگلیسی، اعداد، خط تیره و آندرلاین مجاز هستند.", "danger")
            return redirect(url_for("index") + "?tab=openvpn")

        try:
            days = max(1, int(days_str))
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

        ok, msg = create_openvpn_user(username, days, limit_gb, server_ip)
        if ok:
            flash(f"کاربر OpenVPN «{username}» با اعتبار {days} روزه ایجاد شد.", "success")
        else:
            flash(f"خطا در ایجاد کاربر: {msg}", "danger")

        return redirect(url_for("index") + "?tab=openvpn")

    @app.post("/openvpn/deactivate/<username>")
    def openvpn_deactivate(username):
        if deactivate_openvpn_user(username):
            restart_openvpn_service()
            flash(f"کاربر OpenVPN «{username}» غیرفعال شد.", "warning")
        else:
            flash(f"کاربر «{username}» پیدا نشد.", "danger")
        return redirect(url_for("index") + "?tab=openvpn")

    @app.post("/openvpn/delete/<username>")
    def openvpn_delete(username):
        if delete_openvpn_user(username):
            restart_openvpn_service()
            flash(f"کاربر OpenVPN «{username}» حذف شد.", "danger")
        else:
            flash(f"کاربر «{username}» پیدا نشد.", "danger")
        return redirect(url_for("index") + "?tab=openvpn")

    @app.post("/openvpn/extend/<username>")
    def openvpn_extend(username):
        days_str = request.form.get("days", "30").strip()
        try:
            days = max(1, int(days_str))
        except ValueError:
            days = 30
        if extend_openvpn_user(username, days):
            flash(f"اعتبار کاربر OpenVPN «{username}» به اندازه {days} روز تمدید شد.", "success")
        else:
            flash(f"کاربر «{username}» پیدا نشد.", "danger")
        return redirect(url_for("index") + "?tab=openvpn")

    @app.get("/openvpn/download/<username>")
    def openvpn_download(username):
        from flask import send_file as _sf

        if not _validate_ovpn_username(username):
            flash("نام کاربری نامعتبر است.", "danger")
            return redirect(url_for("index") + "?tab=openvpn")

        ovpn_path = os.path.join(OPENVPN_CLIENTS_DIR, f"{username}.ovpn")

        # اگر فایل وجود ندارد ولی گواهی وجود دارد، دوباره بساز
        if not os.path.exists(ovpn_path) and openvpn_is_installed():
            effective_ip = OPENVPN_SERVER_IP or "YOUR_SERVER_IP"
            write_openvpn_client_config(username, effective_ip)

        if not os.path.exists(ovpn_path):
            flash("فایل .ovpn برای این کاربر موجود نیست. لطفاً ابتدا OpenVPN را نصب و PKI را راه‌اندازی کنید.", "danger")
            return redirect(url_for("index") + "?tab=openvpn")

        return _sf(
            ovpn_path,
            as_attachment=True,
            download_name=f"{username}.ovpn",
            mimetype="application/x-openvpn-profile",
        )

    @app.get("/openvpn/download-stunnel/<username>")
    def openvpn_download_stunnel(username):
        """دانلود پروفایل OpenVPN+Stunnel (ضد فیلترینگ هوشمند)."""
        from flask import send_file as _sf
        import io, zipfile

        if not _validate_ovpn_username(username):
            flash("نام کاربری نامعتبر است.", "danger")
            return redirect(url_for("index") + "?tab=openvpn")

        if not STUNNEL_CONFIG.get("enabled"):
            flash("حالت Stunnel فعال نیست. ابتدا install-openvpn-stealth.sh را اجرا کنید.", "warning")
            return redirect(url_for("index") + "?tab=openvpn")

        result = build_ovpn_stunnel_config(username)
        if result is None:
            flash("گواهی این کاربر یافت نشد.", "danger")
            return redirect(url_for("index") + "?tab=openvpn")

        ovpn_content, stunnel_conf = result

        # هر دو فایل را در یک ZIP برمی‌گردانیم
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{username}-stealth.ovpn", ovpn_content)
            zf.writestr("stunnel-client.conf", stunnel_conf)
            zf.writestr("README.txt",
                "راهنمای اتصال OpenVPN Stealth\n"
                "═══════════════════════════════\n\n"
                "Windows:\n"
                "  ۱. Stunnel دانلود کنید: https://www.stunnel.org/downloads.html\n"
                "  ۲. فایل stunnel-client.conf را در C:\\Program Files (x86)\\stunnel\\config\\ کپی کنید\n"
                "  ۳. Stunnel را اجرا کنید (system tray)\n"
                "  ۴. فایل .ovpn را در OpenVPN Connect وارد کنید\n\n"
                "Android:\n"
                "  ۱. SSHTunnel یا Stunnel4Android نصب کنید\n"
                "  ۲. تنظیمات: server=YOUR_SERVER_IP port=8443\n"
                "  ۳. OpenVPN Connect: remote 127.0.0.1 1195\n\n"
                "Linux/Mac:\n"
                "  sudo apt install stunnel4   # یا brew install stunnel\n"
                "  sudo stunnel stunnel-client.conf\n"
                "  sudo openvpn --config .ovpn\n"
            )
        buf.seek(0)
        return _sf(
            buf,
            as_attachment=True,
            download_name=f"{username}-openvpn-stealth.zip",
            mimetype="application/zip",
        )

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("VPN_ADMIN_PORT", "5000"))
    host = os.environ.get("VPN_ADMIN_HOST", "0.0.0.0")
    app.run(host=host, port=port, debug=False)


