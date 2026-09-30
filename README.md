# NS2 DNS Accelerator

Mac 单文件 Nintendo Switch / Switch 2 下载加速器——零依赖、纯 Python、开机自启。

不搬运流量、不需要代理节点、完全免费：通过 DNS 层智能调度，把 eShop 下载指到实测最快的官方 CDN 节点。

## 原理

任天堂没有中国大陆服务器，下载全部走海外 CDN。Switch 下载前会通过 DNS "问路"，默认调度经常把国内用户指到很远的节点，导致下载极慢。

本工具在 Mac 上起一个 DNS 服务接管"问路"这一步：

```
Switch ──DNS询问──▶ Mac (dns_accel.py)
                      │ 1. 同时向 4 个上游 DNS（国内外）查询候选节点
                      │ 2. 对每个候选 IP 实测 TCP 443 连接延迟
                      │ 3. 把最快的那个返回给 Switch
                      ▼
              Switch 直连最快 CDN 节点下载
```

- 拦截域名：`*.cdn.nintendo.net`、`*.shop.nintendo.net`
- 其他所有域名原样转发（223.5.5.5 优先），Switch 正常上网不受影响
- 每 10 分钟自动复测，节点变慢自动换

## 安装

```bash
git clone https://github.com/<你的用户名>/ns2-dns-accel.git
cd ns2-dns-accel
sudo bash install.sh
```

安装为 launchd 系统服务（开机自启、崩溃自动拉起、防系统休眠），日志在 `/tmp/ns2dns.log`。

## Switch 端设置

1. 设置 → 互联网 → 当前 Wi-Fi → 更改设置
2. DNS 设置 → 手动
3. 主 DNS 填你 Mac 的局域网 IP（安装脚本会打印出来）
4. 保存重连，去 eShop 下载测试

建议在路由器上给 Mac 绑定静态 IP（DHCP 保留地址），一劳永逸。

## 卸载

```bash
sudo bash uninstall.sh
```

## 常见问题

**Q: 下载没变快？**
DNS 调度只治"被指错路"。如果你家宽带到所有海外节点都慢（国际出口整体拥堵），四个候选全是慢的，提升有限——那是线路瓶颈，需要的是代理/专线方案，不是本工具的适用范围。

**Q: 会影响 Mac 或其他设备上网吗？**
不会。服务只监听局域网接口，只应答发到 Mac 53 端口的查询；Mac 自己的 DNS 设置不用改。

**Q: 安全性？**
- 只对任天堂域名做择优，其余查询透明转发，不解析、不记录
- 测速目标仅限公网 IP（自动排除内网/环回/保留地址）
- 不搬运任何流量，Switch 与 CDN 之间仍是直连

**Q: 能给 PS5 / Xbox 用吗？**
可以，把 `INTERCEPT_SUFFIXES` 里加上对应域名后缀（如 `.playstation.net`）即可，原理完全相同。

## 环境要求

- macOS（在 Apple Silicon + Python 3.14 验证，理论上支持任意 Python 3.8+）
- Mac 与 Switch 在同一局域网
- Mac 保持开机（服务自带 caffeinate 防休眠）

## License

[MIT](LICENSE)
