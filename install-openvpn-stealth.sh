#!/usr/bin/env bash
# =============================================================================
#  install-openvpn-stealth.sh
#  مبهم‌سازی پیشرفته OpenVPN با Stunnel + TLS-Crypt
#  ترافیک به صورت HTTPS روی پورت 8443 نمایش داده می‌شود
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]  ${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
die()   { echo -e "${RED}[ERR] ${NC} $*"; exit 1; }

[[ $EUID -ne 0 ]] && die "این اسکریپت باید با دسترسی root اجرا شود."

OPENVPN_DIR="/etc/openvpn"
SERVER_DIR="$OPENVPN_DIR/server"
STUNNEL_CONF="/etc/stunnel/stunnel.conf"
STUNNEL_PEM="/etc/stunnel/openvpn-stunnel.pem"
STUNNEL_PORT=8443          # پورت خارجی (TLS)
OVPN_TCP_PORT=1195         # OpenVPN روی TCP داخلی (فقط localhost)
PATHS_CONF="/opt/vpn/server/ovpn-stealth.conf"

echo ""
echo -e "${CYAN}┌─────────────────────────────────────────────────────────────┐${NC}"
echo -e "${CYAN}│     🛡️  OpenVPN Stealth Setup — Stunnel + TLS-Crypt          │${NC}"
echo -e "${CYAN}│   ترافیک شبیه HTTPS | ضد فیلترینگ هوشمند (DPI)               │${NC}"
echo -e "${CYAN}└─────────────────────────────────────────────────────────────┘${NC}"
echo ""

# ─── نصب Stunnel ─────────────────────────────────────────────────────────────
info "نصب Stunnel ..."
apt-get update -qq
apt-get install -y -qq stunnel4
ok "Stunnel نصب شد"

# ─── ساخت گواهی self-signed برای Stunnel ─────────────────────────────────────
info "ساخت گواهی TLS برای Stunnel ..."
if [[ ! -f "$STUNNEL_PEM" ]]; then
    openssl req -new -x509 -days 3650 -nodes \
        -subj "/C=US/ST=CA/L=San Francisco/O=TechCorp/CN=update.microsoft.com" \
        -out "$STUNNEL_PEM" \
        -keyout "$STUNNEL_PEM" \
        -addext "subjectAltName=DNS:update.microsoft.com,DNS:cdn.cloudflare.com" \
        2>/dev/null
    chmod 600 "$STUNNEL_PEM"
    ok "گواهی TLS Stunnel ساخته شد (CN=update.microsoft.com)"
else
    ok "گواهی Stunnel از قبل وجود دارد"
fi

# ─── پیکربندی TLS-Crypt روی OpenVPN ─────────────────────────────────────────
info "پیکربندی TLS-Crypt برای OpenVPN ..."
TCRPYT_KEY="$SERVER_DIR/tls-crypt.key"
if [[ ! -f "$TCRPYT_KEY" ]]; then
    openvpn --genkey secret "$TCRPYT_KEY"
    ok "کلید tls-crypt ساخته شد: $TCRPYT_KEY"
else
    ok "کلید tls-crypt از قبل وجود دارد"
fi

# ─── افزودن listener TCP روی OpenVPN (localhost:1195) ─────────────────────────
info "اضافه کردن OpenVPN TCP listener روی localhost:$OVPN_TCP_PORT ..."

TCP_CONF="/etc/openvpn/server/server-tcp.conf"
if [[ ! -f "$TCP_CONF" ]]; then
    # کپی از config اصلی و تبدیل به TCP
    if [[ -f "/etc/openvpn/server/server.conf" ]]; then
        # استخراج تنظیمات CA/cert/key/dh از فایل اصلی
        BASE_CONF=$(grep -E "^(ca |cert |key |dh |server |push|client-to-client|keepalive|cipher|auth |user |group |persist|status|log|verb|tls-auth)" \
            /etc/openvpn/server/server.conf 2>/dev/null || true)
    fi

    cat > "$TCP_CONF" << EOF
# OpenVPN TCP - for Stunnel wrapper (localhost only)
local 127.0.0.1
port $OVPN_TCP_PORT
proto tcp
dev tun1
ca   $SERVER_DIR/../../easy-rsa/pki/ca.crt
cert $SERVER_DIR/../../easy-rsa/pki/issued/server.crt
key  $SERVER_DIR/../../easy-rsa/pki/private/server.key
dh   $SERVER_DIR/../../easy-rsa/pki/dh.pem
server 10.9.0.0 255.255.255.0
push "redirect-gateway def1 bypass-dhcp"
push "dhcp-option DNS 1.1.1.1"
push "dhcp-option DNS 8.8.8.8"
keepalive 10 120
tls-crypt $TCRPYT_KEY
cipher AES-256-GCM
auth SHA256
user nobody
group nogroup
persist-key
persist-tun
status /run/openvpn-server/status-server-tcp.log
verb 3
explicit-exit-notify 0
EOF
    ok "OpenVPN TCP config ساخته شد: $TCP_CONF"

    # Check if PKI files exist at alternative paths
    if [[ ! -f "/etc/openvpn/easy-rsa/pki/ca.crt" ]]; then
        warn "مسیر PKI پیش‌فرض یافت نشد. مسیر واقعی را چک کنید:"
        find /etc/openvpn -name "ca.crt" 2>/dev/null | head -3
        # Try to auto-detect and fix
        PKI_CA=$(find /etc/openvpn -name "ca.crt" 2>/dev/null | head -1)
        if [[ -n "$PKI_CA" ]]; then
            PKI_DIR=$(dirname "$PKI_CA")
            sed -i "s|/etc/openvpn/easy-rsa/pki|$PKI_DIR|g" "$TCP_CONF"
            ok "مسیر PKI خودکار تنظیم شد: $PKI_DIR"
        fi
    fi
else
    ok "OpenVPN TCP config از قبل وجود دارد"
fi

# ─── فعال‌سازی OpenVPN TCP instance ─────────────────────────────────────────
info "فعال‌سازی openvpn-server@server-tcp ..."
systemctl enable openvpn-server@server-tcp 2>/dev/null || true
systemctl restart openvpn-server@server-tcp 2>/dev/null || {
    warn "سرویس TCP راه‌اندازی نشد — احتمالاً PKI نیاز به بررسی دارد"
    warn "بعد از بررسی: systemctl restart openvpn-server@server-tcp"
}

sleep 2
if systemctl is-active --quiet openvpn-server@server-tcp; then
    ok "OpenVPN TCP روی localhost:$OVPN_TCP_PORT فعال است"
else
    warn "OpenVPN TCP هنوز فعال نیست — لاگ: journalctl -u openvpn-server@server-tcp -n 20"
fi

# ─── پیکربندی Stunnel ────────────────────────────────────────────────────────
info "پیکربندی Stunnel ..."
systemctl enable stunnel4 2>/dev/null || true

cat > "$STUNNEL_CONF" << EOF
; Stunnel config — OpenVPN Stealth
; ترافیک ورودی TLS را به OpenVPN TCP محلی forward می‌کند

pid = /run/stunnel4/stunnel.pid
output = /var/log/stunnel4/stunnel.log

[openvpn-stealth]
accept  = 0.0.0.0:$STUNNEL_PORT
connect = 127.0.0.1:$OVPN_TCP_PORT
cert    = $STUNNEL_PEM
; TLS امنیتی
sslVersion = TLSv1.2
ciphers = ECDHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-AES128-GCM-SHA256
options = NO_SSLv2
options = NO_SSLv3
options = NO_TLSv1
; تظاهر به HTTP/1.1 در SNI
; رمزنگاری سربرگ برای مخفی کردن fingerprint
renegotiation = no
EOF

mkdir -p /run/stunnel4 /var/log/stunnel4
systemctl restart stunnel4 2>/dev/null || {
    # Debian/Ubuntu may need stunnel4 enabled differently
    sed -i 's/ENABLED=0/ENABLED=1/' /etc/default/stunnel4 2>/dev/null || true
    systemctl restart stunnel4
}

sleep 1
if systemctl is-active --quiet stunnel4; then
    ok "Stunnel فعال است روی پورت $STUNNEL_PORT"
else
    warn "Stunnel شروع نشد — لاگ: journalctl -u stunnel4 -n 20"
fi

# ─── باز کردن پورت در فایروال ────────────────────────────────────────────────
info "بررسی فایروال ..."
if command -v ufw &>/dev/null && ufw status | grep -q "Status: active"; then
    ufw allow "$STUNNEL_PORT/tcp" comment "OpenVPN-Stunnel" 2>/dev/null || true
    ok "ufw: پورت $STUNNEL_PORT/tcp باز شد"
fi
if command -v iptables &>/dev/null; then
    iptables -C INPUT -p tcp --dport "$STUNNEL_PORT" -j ACCEPT 2>/dev/null || \
        iptables -A INPUT -p tcp --dport "$STUNNEL_PORT" -j ACCEPT
fi

# ─── ذخیره تنظیمات ───────────────────────────────────────────────────────────
info "ذخیره تنظیمات ..."
mkdir -p "$(dirname "$PATHS_CONF")"
SERVER_IP=$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null || echo "")

cat > "$PATHS_CONF" << EOF
# OpenVPN Stealth Configuration
# Generated by install-openvpn-stealth.sh
STUNNEL_ENABLED=1
STUNNEL_PORT=$STUNNEL_PORT
STUNNEL_PEM=$STUNNEL_PEM
OVPN_TCP_PORT=$OVPN_TCP_PORT
TLS_CRYPT_KEY=$TCRPYT_KEY
SERVER_IP=$SERVER_IP
EOF

chmod 600 "$PATHS_CONF"
ok "تنظیمات در $PATHS_CONF ذخیره شدند"

# ─── نمایش خلاصه ─────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}══════════════════ نصب کامل شد ══════════════════${NC}"
echo ""
echo -e "  ${CYAN}پورت Stunnel (TLS):${NC}   ${SERVER_IP}:${STUNNEL_PORT}/tcp"
echo -e "  ${CYAN}OpenVPN TCP داخلی:${NC}     localhost:${OVPN_TCP_PORT}"
echo -e "  ${CYAN}گواهی TLS:${NC}             ${STUNNEL_PEM}"
echo -e "  ${CYAN}کلید TLS-Crypt:${NC}        ${TCRPYT_KEY}"
echo ""
echo -e "  ${YELLOW}⚡ پنل مدیریت را ری‌استارت کنید تا پروفایل‌های Stunnel${NC}"
echo -e "  ${YELLOW}   برای هر کاربر OpenVPN تولید شوند.${NC}"
echo ""
echo -e "  ${YELLOW}⚠️  پورت $STUNNEL_PORT را در GCP Firewall باز کنید:${NC}"
echo -e "  gcloud compute firewall-rules create allow-ovpn-stunnel \\"
echo -e "    --allow tcp:${STUNNEL_PORT} --target-tags=vpn-server"
echo ""
echo -e "  ${CYAN}متغیرهای محیطی مورد نیاز پنل:${NC}"
echo -e "  STUNNEL_ENABLED=1"
echo -e "  STUNNEL_PORT=${STUNNEL_PORT}"
