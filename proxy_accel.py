#!/usr/bin/env python3
"""
NS2 加速代理（CONNECT 模式）：验证"Switch 代理设置"通道。
Switch 网络设置 → 代理服务器 → 填本机 IP:8888。
对每个 CONNECT 目标：多上游解析 → TCP 实测择优 → 双向转发。
高端口无需 root。零依赖。
"""

import ipaddress
import select
import socket
import struct
import sys
import threading
import time

LISTEN_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8888
UPSTREAMS = ["223.5.5.5", "119.29.29.29", "8.8.8.8", "1.1.1.1"]
RECHECK_INTERVAL = 600

ip_cache = {}  # host -> {"ip": str, "expire": float}
cache_lock = threading.Lock()


def log(msg):
    print(time.strftime("[%H:%M:%S]"), msg, flush=True)


def is_public_ip(s: str) -> bool:
    try:
        ip = ipaddress.ip_address(s)
        return not (ip.is_private or ip.is_loopback or ip.is_reserved
                    or ip.is_link_local or ip.is_multicast or ip.is_unspecified)
    except ValueError:
        return False


def query_dns_a(host: str, server: str, timeout: float = 1.2):
    """原始 DNS A 查询，返回 IP 列表"""
    tid = int(time.time() * 1000) & 0xFFFF
    q = struct.pack("!HHHHHH", tid, 0x0100, 1, 0, 0, 0)
    for part in host.split("."):
        q += bytes([len(part)]) + part.encode()
    q += b"\x00" + struct.pack("!HH", 1, 1)
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        s.sendto(q, (server, 53))
        resp, _ = s.recvfrom(4096)
    except Exception:
        return []
    finally:
        if s:
            try:
                s.close()
            except Exception:
                pass
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
        i += 4
        ancount = struct.unpack("!H", resp[6:8])[0]
        for _ in range(ancount):
            l = resp[i]
            if l & 0xC0 == 0xC0:
                i += 2
            else:
                while resp[i] != 0:
                    i += 1 + resp[i]
                i += 1
            rtype, _rc, _ttl, rdlen = struct.unpack("!HHIH", resp[i:i + 10])
            i += 10
            if rtype == 1 and rdlen == 4:
                ips.append(".".join(str(b) for b in resp[i:i + 4]))
            i += rdlen
    except Exception:
        pass
    return ips


def tcp_connect_ms(ip: str, port: int, timeout: float = 0.8):
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


def best_ip_for(host: str, port: int):
    """解析 + 择优；失败退回系统解析"""
    now = time.time()
    with cache_lock:
        hit = ip_cache.get(host)
        if hit and hit["expire"] > now:
            return hit["ip"]

    candidates, seen = [], set()
    for up in UPSTREAMS:
        for ip in query_dns_a(host, up):
            if ip not in seen and is_public_ip(ip):
                seen.add(ip)
                candidates.append(ip)
        if len(candidates) >= 8:
            break
    if not candidates:
        try:
            candidates = [ai[4][0] for ai in socket.getaddrinfo(host, port, socket.AF_INET)]
        except Exception:
            return None

    latencies = {}
    threads = []

    def measure(ip):
        ms = tcp_connect_ms(ip, port)
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
                          sorted(latencies.items(), key=lambda x: x[1])[:3])
        log(f"{host}:{port} -> {best} ({detail})")
    else:
        best = candidates[0]
        log(f"{host}:{port} -> {best} (测速全失败，退回首选)")
    with cache_lock:
        ip_cache[host] = {"ip": best, "expire": now + RECHECK_INTERVAL}
    return best


def splice(a: socket.socket, b: socket.socket):
    """双向转发直到任一侧关闭"""
    sockets = [a, b]
    try:
        while True:
            r, _, _ = select.select(sockets, [], [], 60)
            if not r:
                break
            for s in r:
                peer = b if s is a else a
                data = s.recv(65536)
                if not data:
                    return
                peer.sendall(data)
    except Exception:
        pass
    finally:
        for s in (a, b):
            try:
                s.close()
            except Exception:
                pass


def handle(client: socket.socket, addr):
    try:
        client.settimeout(8)
        req = b""
        while b"\r\n\r\n" not in req and len(req) < 8192:
            chunk = client.recv(4096)
            if not chunk:
                return
            req += chunk
        line = req.split(b"\r\n", 1)[0].decode("latin1", "replace")
        parts = line.split()
        if len(parts) < 2 or parts[0].upper() != "CONNECT":
            log(f"非 CONNECT 请求，忽略: {line[:60]}")
            client.close()
            return
        host, _, port_s = parts[1].rpartition(":")
        port = int(port_s) if port_s.isdigit() else 443

        ip = best_ip_for(host, port)
        if not ip:
            client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            client.close()
            return
        upstream = socket.create_connection((ip, port), timeout=5)
        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        client.settimeout(None)
        log(f"[{addr[0]}] 隧道建立 {host}:{port}")
        splice(client, upstream)
    except Exception as e:
        log(f"处理异常 {addr[0]}: {e}")
        try:
            client.close()
        except Exception:
            pass


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "0.0.0.0"


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bind_ip = lan_ip()
    srv.bind((bind_ip, LISTEN_PORT))
    srv.listen(16)
    log(f"NS2 加速代理已启动 {bind_ip}:{LISTEN_PORT}")
    log("Switch 端：网络设置 → 代理服务器 → 开启 → 服务器填上面的 IP，端口填上面的端口")
    while True:
        try:
            client, addr = srv.accept()
            threading.Thread(target=handle, args=(client, addr), daemon=True).start()
        except Exception as e:
            log(f"accept 异常: {e}")


if __name__ == "__main__":
    main()
