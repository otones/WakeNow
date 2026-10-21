"""MAC → IP 自动发现。

WOL 只需要 MAC：魔术包是二层广播帧，与 IP 无关。IP 在本工具里唯一用途是
ping 探测在线状态。而 DHCP 分配的 IP 会变，所以不应当要求用户手填。

做法：向本网段各地址发送一个空 UDP 包，逼迫系统为每个地址做 ARP 解析，
再读 `arp -a` 得到 MAC→IP 映射。ARP 是二层协议，目标机只要开机就会应答，
即使它开了防火墙禁 ping 也一样。这样 IP 变了能自动跟到。
"""
from __future__ import annotations

import re
import socket
import subprocess
import sys
import time

from .models import is_ip, normalize_mac

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# 例：192.168.2.10   00-11-22-33-44-55   动态
_ARP_LINE = re.compile(
    r"(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5})"
)


def local_ipv4() -> str | None:
    """本机主网卡 IPv4。UDP connect 不发包，离线也能用。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            return ip if is_ip(ip) and not ip.startswith("127.") else None
    except OSError:
        return None


def subnet_prefixes(candidate_ips: list[str]) -> list[str]:
    """需要扫描的 /24 前缀：本机网段 + 所有已知机器 IP 所在网段。"""
    prefixes: list[str] = []
    for ip in ([local_ipv4()] + list(candidate_ips)):
        if ip and is_ip(ip):
            prefix = ip.rsplit(".", 1)[0]
            if prefix not in prefixes:
                prefixes.append(prefix)
    return prefixes


def arp_table() -> dict[str, str]:
    """读系统 ARP 缓存，返回 {归一化 MAC: IP}。"""
    try:
        proc = subprocess.run(
            ["arp", "-a"],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    table: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        m = _ARP_LINE.search(line)
        if not m:
            continue
        ip, raw_mac = m.group(1), m.group(2)
        if not is_ip(ip):
            continue
        # 跳过广播 / 组播地址
        if ip.endswith(".255") or ip.endswith(".0") or ip.startswith("224.") or ip.startswith("239."):
            continue
        table[normalize_mac(raw_mac)] = ip
    return table


def sweep(prefixes: list[str], port: int = 9, timeout_s: float = 0.4) -> None:
    """向各网段 .1~.254 发空包，逼出 ARP 表项。"""
    if not prefixes:
        return
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for prefix in prefixes:
            for host in range(1, 255):
                try:
                    sock.sendto(b"\x00", (f"{prefix}.{host}", port))
                except OSError:
                    pass
    time.sleep(timeout_s)


def discover(macs: list[str], candidate_ips: list[str]) -> dict[str, str]:
    """给一批 MAC 找当前 IP，返回 {归一化 MAC: IP}（找不到的不在结果里）。"""
    wanted = {normalize_mac(m) for m in macs if m}
    if not wanted:
        return {}

    prefixes = subnet_prefixes(candidate_ips)
    table = arp_table()
    # 只要还有 MAC 没找到就扫一遍（不能等「全部」都找不到才扫，
    # 否则缓存里有部分条目时，其余机器永远发现不了）
    if any(mac not in table for mac in wanted):
        sweep(prefixes)
        table = arp_table()
    return {mac: table[mac] for mac in wanted if mac in table}
