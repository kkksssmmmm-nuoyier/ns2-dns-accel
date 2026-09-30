#!/bin/bash
# 卸载 launchd 服务
LABEL="com.kasimu.ns2dns"

launchctl bootout system/${LABEL} 2>/dev/null || true
rm -f /Library/LaunchDaemons/${LABEL}.plist
pkill -f dns_accel.py 2>/dev/null || true

echo "✅ 已卸载（别忘了把 Switch 的 DNS 改回自动）"
