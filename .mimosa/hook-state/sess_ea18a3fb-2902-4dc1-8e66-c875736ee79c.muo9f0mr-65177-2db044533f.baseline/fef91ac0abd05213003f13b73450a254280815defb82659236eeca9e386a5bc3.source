#!/usr/bin/env python3
"""
NS2 DNS 加速：拦截任天堂 CDN/商店域名，多上游解析 + 实测延迟择优；
其余域名原样转发。零依赖，单文件。
用法: sudo python3 dns_accel.py [端口，默认 53]
"""

import ipaddress
import socket
import struct
import sys
import threading
import time

LISTEN_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 53


def lan_ip() -> str:
    """取 en0 的局域网 IP（服务只需暴露给同网段的 Switch 用）"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))  # 不发包，只为路由选择
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "0.0.0.0"
# 拦截这些后缀的域名（下载/商店内容分发）
INTERCEPT_SUFFIXES = (
    ".cdn.nintendo.net",
    ".shop.nintendo.net",
    "cdn.nintendo.net",
    "shop.nintendo.net",
)
# 上游 DNS：国内 + 海外混合，候选来源越多调度越好
UPSTREAMS = ["223.5.5.5", "119.29.29.29", "8.8.8.8", "1.1.1.1"]
FORWARD_PRIMARY = "223.5.5.5"
FORWARD_FALLBACK = ["119.29.29.29", "8.8.8.8"]
RECHECK_INTERVAL = 600   # 最优节点复测周期（秒）
ANSWER_TTL = 60          # 返回给 Switch 的 TTL

cache = {}  # domain -> {"ip": str, "measured": float, "expire": float}
cache_lock = threading.Lock()


def log(msg):
    print(time.strftime("[%H:%M:%S]"), msg, flush=True)


def is_public_ip(s: str) -> bool:
    """只允许公网 IP 进入测速/应答，拒绝内网环回等保留地址。"""
    try:
        ip = ipaddress.ip_address(s)
        return not (ip.is_private or ip.is_loopback or ip.is_reserved
                    or ip.is_link_local or ip.is_multicast or ip.is_unspecified)
    except ValueError:
        return False


# ---------- DNS 报文基础 ----------

def parse_question(data: bytes):
    """返回 (qname, qtype, question_end_offset) 或 None"""
    if len(data) < 12:
        return None
    if struct.unpack("!H", data[4:6])[0] < 1:  # qdcount
        return None
    i = 12
    labels = []
    while i < len(data):
        l = data[i]
        if l == 0:
            i += 1
            break
        if l & 0xC0:
            return None  # question 里不该有指针
        labels.append(data[i + 1:i + 1 + l])
        i += 1 + l
    if i + 4 > len(data):
        return None
    qtype = struct.unpack("!H", data[i:i + 2])[0]
    return (".".join(p.decode("latin1") for p in labels).lower(), qtype, i + 4)


def query_upstream(data: bytes, server: str, timeout: float = 1.2):
    """把原始查询转发给上游，返回原始应答字节"""
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        s.sendto(data, (server, 53))
        resp, _ = s.recvfrom(4096)
        return resp
    except Exception:
        return None
    finally:
        if s:
            try:
                s.close()
            except Exception:
                pass


def extract_a_records(resp: bytes):
    """从应答里抽出 A 记录 IP 列表"""
    ips = []
    try:
        i = 12
        while i < len(resp):
            l = resp[i]
            if l == 0:
                i += 1
                break
            if l & 0xC0:
                i += 2
                break
            i += 1 + l
        i += 4  # qtype + qclass
        ancount = struct.unpack("!H", resp[6:8])[0]
        for _ in range(ancount):
            l = resp[i]
            if l & 0xC0 == 0xC0:
                i += 2
            else:
                while resp[i] != 0:
                    i += 1 + resp[i]
                i += 1
            rtype, _rclass, _ttl, rdlen = struct.unpack("!HHIH", resp[i:i + 10])
            i += 10
            if rtype == 1 and rdlen == 4:
                ips.append(".".join(str(b) for b in resp[i:i + 4]))
            i += rdlen
    except Exception:
        pass
    return ips


def build_response(query: bytes, answer_ips, rcode=0):
    """基于原始 query 构造应答；answer_ips 为空则返回空应答（NOERROR）"""
    qid = query[:2]
    flags = struct.pack("!H", 0x8180 | rcode)  # QR|RD|RA
    qdcount = struct.pack("!H", 1)
    parsed = parse_question(query)
    q_end = parsed[2]
    question = query[12:q_end]
    ancount = len(answer_ips) if answer_ips else 0
    head = qid + flags + qdcount + struct.pack("!H", ancount) + b"\x00\x00\x00\x00"
    body = question
    for ip in (answer_ips or []):
        rd = bytes(int(x) for x in ip.split("."))
        body += b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, ANSWER_TTL, 4) + rd
    return head + body


# ---------- 节点测速 ----------

def tcp_connect_ms(ip: str, port: int = 443, timeout: float = 0.8):
    """TCP 连接延迟（毫秒）；连不通返回 None"""
    if not is_public_ip(ip):
        return None
    s = None
    try:
        t0 = time.monotonic()
        s = socket.create_connection((ip, port), timeout=timeout)
        return (time.monotonic() - t0) * 1000
    except Exception:
        return None
    finally:
        if s:
            try:
                s.close()
            except Exception:
                pass


def pick_best_ip(domain: str, probe_query: bytes):
    """多上游收集候选 → 并发测速 → 最优者；全部失败退回第一个候选"""
    candidates = []
    seen = set()
    results = [query_upstream(probe_query, up) for up in UPSTREAMS]
    for resp in results:
        if not resp:
            continue
        for ip in extract_a_records(resp):
            if ip not in seen and is_public_ip(ip):
                seen.add(ip)
                candidates.append(ip)
    if not candidates:
        return None, []
    latencies = {}
    threads = []

    def measure(ip):
        ms = tcp_connect_ms(ip)
        if ms is not None:
            latencies[ip] = ms

    for ip in candidates[:8]:
        t = threading.Thread(target=measure, args=(ip,), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    if latencies:
        best = min(latencies, key=latencies.get)
        detail = " ".join(f"{ip}={ms:.0f}ms" for ip, ms in
                          sorted(latencies.items(), key=lambda x: x[1])[:4])
        return best, [f"{domain} -> {best} ({detail})"]
    return candidates[0], [f"{domain} -> {candidates[0]} (全部测速失败，退回首选)"]


# ---------- 查询处理 ----------

def handle(data: bytes, addr, sock):
    parsed = parse_question(data)
    if not parsed:
        return
    domain, qtype, _ = parsed

    intercepted = domain.endswith(INTERCEPT_SUFFIXES)
    if intercepted:
        if qtype == 1:  # A 记录：查缓存/测速
            now = time.time()
            with cache_lock:
                hit = cache.get(domain)
                fresh = hit and hit["expire"] > now
            if not fresh:
                best, notes = pick_best_ip(domain, data)
                for n in notes:
                    log(n)
                if best:
                    with cache_lock:
                        cache[domain] = {
                            "ip": best,
                            "expire": now + RECHECK_INTERVAL,
                        }
                else:
                    resp = query_upstream(data, FORWARD_PRIMARY)
                    if resp:
                        sock.sendto(resp, addr)
                    return
            with cache_lock:
                ip = cache[domain]["ip"]
            sock.sendto(build_response(data, [ip]), addr)
        else:
            # AAAA 等类型给空应答，避免 IPv6 回退拖慢
            sock.sendto(build_response(data, []), addr)
        return

    # 其他域名：转发
    for up in [FORWARD_PRIMARY] + FORWARD_FALLBACK:
        resp = query_upstream(data, up)
        if resp:
            sock.sendto(resp, addr)
            return


def main():
    port = LISTEN_PORT
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bind_ip = lan_ip()
    try:
        sock.bind((bind_ip, port))
    except PermissionError:
        log(f"端口 {port} 需要管理员权限：sudo python3 dns_accel.py")
        sys.exit(1)
    log(f"NS2 DNS 加速已启动，监听 {bind_ip}:{port}（仅局域网接口）")
    log(f"拦截域名后缀: {', '.join(sorted(set(INTERCEPT_SUFFIXES)))}")
    while True:
        try:
            data, addr = sock.recvfrom(4096)
            threading.Thread(target=handle, args=(data, addr, sock), daemon=True).start()
        except Exception as e:
            log(f"主循环异常: {e}")


if __name__ == "__main__":
    main()
