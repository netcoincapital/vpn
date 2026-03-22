#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
#  install-stealth.sh — V2Ray + WebSocket + TLS Stealth Setup
#  معماری: کلاینت ──► HTTPS:443 ──► Nginx ──► V2Ray(WS)
#  ترافیک برای فیلترینگ DPI کاملاً شبیه وب‌سایت HTTPS عادی است
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

# ─── رنگ‌ها ────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERR]${NC}  $*"; exit 1; }

# ─── پیکربندی ──────────────────────────────────────────────────────
PROJECT_DIR="${PROJECT_DIR:-/opt/vpn}"
V2RAY_CONFIG="${PROJECT_DIR}/config/v2ray-config.json"
NGINX_CONF="/etc/nginx/sites-available/stealth-vpn"
NGINX_ENABLED="/etc/nginx/sites-enabled/stealth-vpn"

# پورت‌های داخلی V2Ray (فقط localhost — هرگز expose نشوند)
VLESS_WS_PORT=10011
VMESS_WS_PORT=10012

# مسیرهای WebSocket — تصادفی و غیرقابل حدس
WS_VLESS_PATH="/$(head -c 12 /dev/urandom | base64 | tr -d '+/=' | head -c 16)"
WS_VMESS_PATH="/$(head -c 12 /dev/urandom | base64 | tr -d '+/=' | head -c 16)"

# شناسه‌های ذخیره‌شده
PATHS_FILE="${PROJECT_DIR}/server/ws-paths.conf"

echo -e "${BOLD}"
echo "┌─────────────────────────────────────────────────────────────┐"
echo "│          🔒  Stealth VPN Setup — WS + TLS                  │"
echo "│     ترافیک شبیه HTTPS عادی | ضد فیلترینگ هوشمند            │"
echo "└─────────────────────────────────────────────────────────────┘"
echo -e "${NC}"

# ─── مرحله ۱: دریافت دامنه ─────────────────────────────────────────
if [[ -f "$PATHS_FILE" ]]; then
    source "$PATHS_FILE"
    DOMAIN="${STEALTH_DOMAIN:-}"
    WS_VLESS_PATH="${STEALTH_VLESS_PATH:-$WS_VLESS_PATH}"
    WS_VMESS_PATH="${STEALTH_VMESS_PATH:-$WS_VMESS_PATH}"
fi

if [[ -z "${DOMAIN:-}" ]]; then
    read -rp "$(echo -e "${BOLD}دامنه یا ساب‌دامین سرور:${NC} (مثال: vpn.example.com): ")" DOMAIN
    [[ -z "$DOMAIN" ]] && error "دامنه الزامی است"
fi

read -rp "$(echo -e "${BOLD}ایمیل برای Let's Encrypt:${NC} ")" LE_EMAIL
[[ -z "$LE_EMAIL" ]] && error "ایمیل الزامی است"

info "دامنه: ${BOLD}$DOMAIN${NC}"
info "مسیر VLESS-WS: ${BOLD}$WS_VLESS_PATH${NC}"
info "مسیر VMess-WS: ${BOLD}$WS_VMESS_PATH${NC}"

# ─── مرحله ۲: نصب Nginx و Certbot ──────────────────────────────────
info "نصب Nginx و Certbot ..."
apt-get update -qq
apt-get install -y nginx certbot python3-certbot-nginx -qq
success "Nginx و Certbot نصب شدند"

# ─── مرحله ۳: صفحه وب فیک (Decoy Website) ──────────────────────────
info "ساخت وب‌سایت پوششی (Decoy) ..."
DECOY_DIR="/var/www/stealth-decoy"
mkdir -p "$DECOY_DIR"

# صفحه HTML ساده که شبیه یک بلاگ فنی است
cat > "$DECOY_DIR/index.html" << 'DECOY_HTML'
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tech Notes — Developer Blog</title>
<style>
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:800px;margin:40px auto;padding:0 20px;color:#333;line-height:1.6}
  h1{color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:10px}
  h2{color:#34495e;margin-top:30px}
  .post{background:#f8f9fa;border-left:4px solid #3498db;padding:15px;margin:20px 0;border-radius:4px}
  .date{color:#7f8c8d;font-size:0.85em}
  code{background:#ecf0f1;padding:2px 6px;border-radius:3px;font-family:monospace}
  footer{margin-top:60px;padding-top:20px;border-top:1px solid #eee;color:#7f8c8d;font-size:0.85em}
</style>
</head>
<body>
<h1>⚙️ Tech Notes</h1>
<p>A minimal blog about networking, systems, and open-source tools.</p>
<div class="post">
  <h2>Understanding TLS 1.3 Improvements</h2>
  <span class="date">March 15, 2026</span>
  <p>TLS 1.3 brings significant performance improvements with its <code>0-RTT</code> resumption
  and reduced handshake latency. In this post we explore the key differences from TLS 1.2 and
  why upgrading matters for modern web infrastructure.</p>
</div>
<div class="post">
  <h2>Linux Kernel Networking Optimizations</h2>
  <span class="date">February 28, 2026</span>
  <p>Tuning <code>tcp_congestion_control</code>, <code>net.core.rmem_max</code>, and BBR
  algorithm settings can dramatically improve throughput on high-latency links...</p>
</div>
<div class="post">
  <h2>Nginx as a Reverse Proxy — Best Practices</h2>
  <span class="date">January 12, 2026</span>
  <p>Proper use of <code>proxy_cache_bypass</code>, upstream keepalive, and connection pooling
  ensures your Nginx proxy layer scales efficiently...</p>
</div>
<footer>Tech Notes &copy; 2026 — Hosted on a VPS somewhere in the cloud.</footer>
</body>
</html>
DECOY_HTML

success "وب‌سایت پوششی ساخته شد"

# ─── مرحله ۴: کانفیگ اولیه Nginx (HTTP برای certbot) ──────────────
info "پیکربندی Nginx (مرحله اول — HTTP) ..."
cat > "$NGINX_CONF" << NGINX_HTTP
server {
    listen 80;
    server_name ${DOMAIN};
    root ${DECOY_DIR};
    index index.html;
    location / { try_files \$uri \$uri/ =404; }
}
NGINX_HTTP

ln -sfn "$NGINX_CONF" "$NGINX_ENABLED"
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
nginx -t && systemctl reload nginx
success "Nginx (HTTP) فعال شد"

# ─── مرحله ۵: دریافت SSL از Let's Encrypt ─────────────────────────
info "دریافت گواهی SSL از Let's Encrypt ..."
certbot --nginx -d "$DOMAIN" --email "$LE_EMAIL" --agree-tos --non-interactive \
    --redirect || {
    warn "Let's Encrypt ناموفق بود — از گواهی self-signed استفاده می‌شود"
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout "/etc/ssl/private/${DOMAIN}.key" \
        -out "/etc/ssl/certs/${DOMAIN}.crt" \
        -subj "/C=FI/ST=Helsinki/L=Helsinki/O=TechNotes/CN=${DOMAIN}" 2>/dev/null
    SSL_CERT="/etc/ssl/certs/${DOMAIN}.crt"
    SSL_KEY="/etc/ssl/private/${DOMAIN}.key"
    SELF_SIGNED=1
}

if [[ -z "${SELF_SIGNED:-}" ]]; then
    SSL_CERT="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
    SSL_KEY="/etc/letsencrypt/live/${DOMAIN}/privkey.pem"
fi

success "گواهی SSL آماده شد"

# ─── مرحله ۶: کانفیگ کامل Nginx با WS Proxy ────────────────────────
info "پیکربندی Nginx با WebSocket proxy ..."
cat > "$NGINX_CONF" << NGINX_FULL
# ─── Stealth VPN — Nginx Config ────────────────────────────────────
# HTTP → HTTPS redirect
server {
    listen 80;
    server_name ${DOMAIN};
    return 301 https://\$host\$request_uri;
}

# HTTPS + WebSocket Proxy
server {
    listen 443 ssl http2;
    server_name ${DOMAIN};

    # ─── SSL ───────────────────────────────────────────────────────
    ssl_certificate     ${SSL_CERT};
    ssl_certificate_key ${SSL_KEY};
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
    ssl_prefer_server_ciphers on;
    ssl_session_timeout 1d;
    ssl_session_cache   shared:MozSSL:10m;
    ssl_session_tickets off;

    # ─── امنیت اضافی HTTP ─────────────────────────────────────────
    add_header Strict-Transport-Security "max-age=63072000" always;
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;

    # ─── وب‌سایت پوششی (هر درخواست غیر-WS) ──────────────────────
    root ${DECOY_DIR};
    index index.html;
    location / {
        try_files \$uri \$uri/ =404;
    }

    # ─── VLESS + WebSocket ─────────────────────────────────────────
    location ${WS_VLESS_PATH} {
        proxy_pass          http://127.0.0.1:${VLESS_WS_PORT};
        proxy_http_version  1.1;
        proxy_set_header    Upgrade \$http_upgrade;
        proxy_set_header    Connection "upgrade";
        proxy_set_header    Host \$host;
        proxy_set_header    X-Real-IP \$remote_addr;
        proxy_set_header    X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout  300s;
        proxy_send_timeout  300s;
    }

    # ─── VMess + WebSocket ─────────────────────────────────────────
    location ${WS_VMESS_PATH} {
        proxy_pass          http://127.0.0.1:${VMESS_WS_PORT};
        proxy_http_version  1.1;
        proxy_set_header    Upgrade \$http_upgrade;
        proxy_set_header    Connection "upgrade";
        proxy_set_header    Host \$host;
        proxy_set_header    X-Real-IP \$remote_addr;
        proxy_set_header    X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout  300s;
        proxy_send_timeout  300s;
    }
}
NGINX_FULL

nginx -t && systemctl reload nginx
success "Nginx با WebSocket proxy پیکربندی شد"

# ─── مرحله ۷: به‌روزرسانی V2Ray Config ─────────────────────────────
info "افزودن inbound های WS به V2Ray ..."

python3 - <<PYEOF
import json, sys

config_path = "${V2RAY_CONFIG}"
with open(config_path, "r") as f:
    config = json.load(f)

inbounds = config.setdefault("inbounds", [])

# حذف inbound های قدیمی WS اگر وجود دارند
inbounds[:] = [ib for ib in inbounds if ib.get("tag") not in ("vless-ws-in", "vmess-ws-in")]

# VLESS + WebSocket (داخلی — فقط localhost)
inbounds.append({
    "tag": "vless-ws-in",
    "port": ${VLESS_WS_PORT},
    "listen": "127.0.0.1",
    "protocol": "vless",
    "settings": {
        "clients": [],
        "decryption": "none"
    },
    "streamSettings": {
        "network": "ws",
        "security": "none",
        "wsSettings": {
            "path": "${WS_VLESS_PATH}",
            "headers": {}
        }
    },
    "sniffing": {
        "enabled": True,
        "destOverride": ["http", "tls", "quic"]
    }
})

# VMess + WebSocket (داخلی — فقط localhost)
inbounds.append({
    "tag": "vmess-ws-in",
    "port": ${VMESS_WS_PORT},
    "listen": "127.0.0.1",
    "protocol": "vmess",
    "settings": {
        "clients": []
    },
    "streamSettings": {
        "network": "ws",
        "security": "none",
        "wsSettings": {
            "path": "${WS_VMESS_PATH}",
            "headers": {}
        }
    },
    "sniffing": {
        "enabled": True,
        "destOverride": ["http", "tls", "quic"]
    }
})

with open(config_path, "w") as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

print("V2Ray config updated")
PYEOF

success "V2Ray config بروز شد"

# ─── مرحله ۸: ری‌استارت V2Ray ──────────────────────────────────────
info "ری‌استارت V2Ray ..."
systemctl restart v2ray 2>/dev/null || true
sleep 2
if systemctl is-active --quiet v2ray 2>/dev/null; then
    success "V2Ray در حال اجرا است"
else
    warn "V2Ray متوقف است — لطفاً سرویس را بررسی کنید"
fi

# ─── مرحله ۹: ذخیره تنظیمات ──────────────────────────────────────
mkdir -p "$(dirname "$PATHS_FILE")"
cat > "$PATHS_FILE" << CONF
STEALTH_DOMAIN=${DOMAIN}
STEALTH_VLESS_PATH=${WS_VLESS_PATH}
STEALTH_VMESS_PATH=${WS_VMESS_PATH}
STEALTH_VLESS_PORT=${VLESS_WS_PORT}
STEALTH_VMESS_PORT=${VMESS_WS_PORT}
STEALTH_SSL_CERT=${SSL_CERT}
STEALTH_SSL_KEY=${SSL_KEY}
CONF

chmod 600 "$PATHS_FILE"
success "تنظیمات در ${PATHS_FILE} ذخیره شدند"

# ─── خلاصه ─────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}══════════════════ نصب کامل شد ══════════════════${NC}"
echo ""
echo -e "  ${BOLD}دامنه:${NC}           https://${DOMAIN}"
echo -e "  ${BOLD}مسیر VLESS-WS:${NC}   ${DOMAIN}${WS_VLESS_PATH}"
echo -e "  ${BOLD}مسیر VMess-WS:${NC}   ${DOMAIN}${WS_VMESS_PATH}"
echo -e "  ${BOLD}تنظیمات:${NC}         ${PATHS_FILE}"
echo ""
echo -e "  ${YELLOW}⚡ بعد از نصب، پنل مدیریت را ری‌استارت کنید تا لینک‌های${NC}"
echo -e "  ${YELLOW}   stealth برای هر کاربر تولید شوند.${NC}"
echo ""
echo -e "  ${CYAN}متغیرهای محیطی مورد نیاز پنل:${NC}"
echo -e "  STEALTH_DOMAIN=${DOMAIN}"
echo -e "  STEALTH_VLESS_PATH=${WS_VLESS_PATH}"
echo -e "  STEALTH_VMESS_PATH=${WS_VMESS_PATH}"
echo ""
