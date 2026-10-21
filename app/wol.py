"""Wake-on-LAN：魔术包构造与发送。"""
from __future__ import annotations

import socket

from .models import Machine, normalize_mac

MAGIC_HEADER = b"\xff" * 6


def build_magic_packet(mac: str) -> bytes:
    raw = bytes.fromhex(normalize_mac(mac).replace(":", ""))
    if len(raw) != 6:
        raise ValueError(f"非法的 MAC 地址：{mac}")
    return MAGIC_HEADER + raw * 16


def send_magic_packet(machine: Machine, *, retries: int = 2, local_ip: str | None = None) -> None:
    """向广播地址发送魔术包，失败抛 OSError。

    唤醒只依赖 MAC；IP 仅用于推断广播地址，没有 IP 时退回受限广播。
    """
    packet = build_magic_packet(machine.mac)
    addr = (machine.broadcast_addr(local_ip), machine.port)
    last: Exception | None = None
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # 多发几次提高丢包容错，WOL 包极小，代价可忽略
        for _ in range(max(1, retries)):
            try:
                sock.sendto(packet, addr)
            except OSError as exc:  # 网卡断开等
                last = exc
    if last is not None:
        raise last
