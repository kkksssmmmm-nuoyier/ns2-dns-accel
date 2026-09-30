#!/bin/bash
# 一键安装：launchd 系统服务（开机自启 + 崩溃自动拉起 + 防休眠）
set -e

LABEL="com.kasimu.ns2dns"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PY3="$(command -v python3)"

if [ -z "$PY3" ]; then
    echo "错误：找不到 python3，请先安装 Python 3"; exit 1
fi

# 取 Mac 局域网 IP（给 Switch 填 DNS 用）
LAN_IP="$(python3 - << 'EOF'
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(("223.5.5.5", 80))
    print(s.getsockname()[0])
except Exception:
    print("")
finally:
    s.close()
EOF
)"

if [ -z "$LAN_IP" ]; then
    echo "警告：无法获取局域网 IP，服务将监听全部接口"
    LAN_IP="0.0.0.0"
fi

cat > /tmp/${LABEL}.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>${LABEL}</string>
	<key>ProgramArguments</key>
	<array>
		<string>/usr/bin/caffeinate</string>
		<string>-is</string>
		<string>${PY3}</string>
		<string>${SCRIPT_DIR}/dns_accel.py</string>
		<string>53</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>KeepAlive</key>
	<true/>
	<key>StandardOutPath</key>
	<string>/tmp/ns2dns.log</string>
	<key>StandardErrorPath</key>
	<string>/tmp/ns2dns.log</string>
</dict>
</plist>
EOF

cp /tmp/${LABEL}.plist /Library/LaunchDaemons/${LABEL}.plist
chown root:wheel /Library/LaunchDaemons/${LABEL}.plist
chmod 644 /Library/LaunchDaemons/${LABEL}.plist
launchctl bootstrap system /Library/LaunchDaemons/${LABEL}.plist 2>/dev/null || true
launchctl enable system/${LABEL}
launchctl kickstart -k system/${LABEL}

sleep 2
echo ""
echo "✅ 安装完成，服务已启动"
echo ""
echo "👉 Switch 端设置：DNS → 手动 → 主 DNS 填  ${LAN_IP}"
echo "👉 实时日志：tail -f /tmp/ns2dns.log"
echo "👉 卸载：sudo bash ${SCRIPT_DIR}/uninstall.sh"
