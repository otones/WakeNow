"""在线探测：ICMP ping 与 TCP 端口连接的组合判定。

单独 ping 的问题是很多 Windows 机器开了防火墙禁 ICMP，实际关机与否
无法区分。这里加 TCP 兜底：只要目标机在监听探测端口，就说明它开着。
"""
from __future__ import annotations

import socket
import subprocess
import sys

from .models import PROBE_AUTO, PROBE_PING, PROBE_TCP, Machine

# Windows 下隐藏子进程窗口
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

DEFAULT_PROBE_TIMEOUT_MS = 800
DEFAULT_TCP_TIMEOUT_MS = 400


def ping_once(ip: str, timeout_ms: int = DEFAULT_PROBE_TIMEOUT_MS) -> bool:
    """单次 ping，通返回 True。"""
    if not ip:
        return False
    if sys.platform == "win32":
        cmd = ["ping", "-n", "1", "-w", str(timeout_ms), ip]
    else:
        cmd = ["ping", "-c", "1", "-W", str(max(1, timeout_ms // 1000)), ip]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_ms / 1000 + 1.5,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def tcp_once(ip: str, port: int, timeout_ms: int = DEFAULT_TCP_TIMEOUT_MS) -> bool:
    """尝试建立 TCP 连接。连上即认为目标机在线，立即断开。"""
    if not ip or not (0 < port < 65536):
        return False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_ms / 1000)
    try:
        return sock.connect_ex((ip, port)) == 0
    except OSError:
        return False
    finally:
        try:
            sock.close()
        except OSError:
            pass


# 用于识别「代理伪造连接」的对照端口：几乎不会有机器在监听它
_SENTINEL_PORT = 54321


def tcp_reachable(ip: str, port: int, timeout_ms: int = DEFAULT_TCP_TIMEOUT_MS) -> bool:
    """TCP 可达性判断，带「透明代理」干扰识别。

    本机若装了 Clash / Surge 这类 TUN 代理，任意地址任意端口的 connect 都会
    立刻成功（由代理伪造成立），此时单纯看 connect_ex() 会把所有机器判成在线。
    对策：同时连一个几乎不可能被监听的对照端口（54321），
      - 对照端口也「通」→ 说明是代理劫持，TCP 结果不可信，返回 False
      - 对照端口不通 → 目标端口通就是真通
    代价是每台机器多一个连接，对局域网探测可忽略。
    """
    if not ip or not (0 < port < 65536):
        return False
    if port == _SENTINEL_PORT:
        # 探测端口本身撞上对照端口时无法自检，退化为直接判断
        return tcp_once(ip, port, timeout_ms)

    if not tcp_once(ip, port, timeout_ms):
        return False
    # 目标端口连上了，验证一下是不是代理的假阳性
    if tcp_once(ip, _SENTINEL_PORT, timeout_ms):
        return False   # 代理环境，结果不可信
    return True


def probe(machine: Machine, ping_timeout_ms: int = DEFAULT_PROBE_TIMEOUT_MS) -> tuple[bool, str]:
    """按机器的探测方式判定是否在线。

    返回 (是否在线, 判定依据说明)。依据用于状态点 tooltip。
    """
    ip = machine.ip
    if not ip:
        return False, "未获取到 IP，无法探测"

    mode = machine.probe
    port = machine.probe_port

    if mode == PROBE_PING:
        online = ping_once(ip, ping_timeout_ms)
        return online, "ICMP ping 成功" if online else "ICMP ping 失败"

    if mode == PROBE_TCP:
        if not port:
            # 配置成「仅 TCP」却没填端口，退回 ping，免得永远判离线
            online = ping_once(ip, ping_timeout_ms)
            return online, "未设置探测端口，回退 ICMP " + ("成功" if online else "失败")
        online = tcp_reachable(ip, port)
        return online, f"TCP {port} 端口可达" if online else f"TCP {port} 端口不可达"

    # auto：ping 优先，失败再试 TCP
    if ping_once(ip, ping_timeout_ms):
        return True, "ICMP ping 成功"
    if port and tcp_reachable(ip, port):
        return True, f"TCP {port} 端口可达"
    if not port:
        return False, "ICMP ping 失败（未设置探测端口）"
    return False, f"ICMP 与 TCP {port} 均失败"
