"""局域网扫描：找出网内存活的机器，供用户勾选后批量保存。

做法：
1. 确定要扫的 /24 网段（排除代理 TUN、Tailscale、WSL、link-local 等虚拟网卡）
2. 向网段内每个地址发一个空 UDP 包 / 快速 TCP 探测，逼出 ARP 表项
3. 读 arp -a，拿到 IP ↔ MAC 对应关系
4. 用 TCP 探测确认存活（ARP 有缓存，可能包含已下线机器的残留）
5. 尝试反查主机名，便于识别
"""
from __future__ import annotations

import ipaddress
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from .discover import arp_table
from .models import is_ip, normalize_mac
from .probe import tcp_reachable

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# 需要排除的虚拟/隧道网段
_VIRTUAL_NETS = [
    ipaddress.ip_network(n)
    for n in (
        "198.18.0.0/15",   # Clash / Meta 等 TUN 代理的 fake-ip
        "100.64.0.0/10",   # Tailscale / CGNAT
        "169.254.0.0/16",  # link-local
        "127.0.0.0/8",
        "224.0.0.0/4",
        "240.0.0.0/4",
    )
]

# 常见虚拟网卡名关键字（WSL / Hyper-V / VMware / VirtualBox）
_VIRTUAL_HINTS = ("vethernet", "hyper-v", "vmware", "virtualbox", "wsl", "loopback")


@dataclass
class Found:
    ip: str
    mac: str
    hostname: str = ""
    alive: bool = False
    already_known: bool = False

    @property
    def label(self) -> str:
        return self.hostname or self.ip


@dataclass
class ScanReport:
    prefixes: list[str] = field(default_factory=list)
    found: list[Found] = field(default_factory=list)
    skipped_virtual: list[str] = field(default_factory=list)
    error: str = ""


# ---------------------------------------------------------------- 网段识别
def local_ipv4_list() -> list[str]:
    """本机所有 IPv4 地址（不只主网卡）。"""
    ips: set[str] = set()
    try:
        _h, _a, addrs = socket.gethostbyname_ex(socket.gethostname())
        ips.update(a for a in addrs if is_ip(a))
    except OSError:
        pass
    # 补一条默认出口地址（上面拿不到时兜底）
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(ips)


def is_virtual_ip(ip: str) -> bool:
    if not is_ip(ip):
        return True
    addr = ipaddress.ip_address(ip)
    if any(addr in net for net in _VIRTUAL_NETS):
        return True
    return not addr.is_private


def _prefixes_with_gateway() -> list[str]:
    """通过默认路由查网卡地址——有默认网关的才是真实局域网。

    用 `route print` 而非 PowerShell：后者启动一次要 5 秒左右，
    会把界面卡住。route 是系统原生小工具，通常 0.5 秒内返回。
    """
    if sys.platform != "win32":
        return []
    try:
        proc = subprocess.run(
            ["route", "print", "-4"],
            capture_output=True, text=True, timeout=5,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    out: list[str] = []
    in_ipv4 = False
    for line in proc.stdout.splitlines():
        s = line.strip()
        # IPv4 路由表段以 "IPv4 路由表" / "IPv4 Route Table" 开头
        if "路由表" in s or "Route Table" in s:
            in_ipv4 = True
            continue
        if not in_ipv4:
            continue
        if not s.startswith("0.0.0.0"):
            continue
        parts = s.split()
        if len(parts) < 4:
            continue
        iface_ip = parts[3]
        if is_ip(iface_ip) and not is_virtual_ip(iface_ip):
            prefix = iface_ip.rsplit(".", 1)[0]
            if prefix not in out:
                out.append(prefix)
    return out


def quick_prefixes() -> list[str]:
    """不查路由表的快速版本，供弹窗立即使用（约 20ms）。

    只按本地 IP 猜测，可能有 WSL 等误判，但不阻塞界面；
    调用方可在后台用 candidate_prefixes() 再精修。
    """
    ranked: list[tuple[int, str]] = []

    def add(prefix: str, score: int) -> None:
        if all(prefix != p for _s, p in ranked):
            ranked.append((score, prefix))

    for ip in local_ipv4_list():
        if is_virtual_ip(ip):
            continue
        prefix = ip.rsplit(".", 1)[0]
        if prefix.startswith("192.168."):
            add(prefix, 0)
        elif prefix.startswith("10."):
            add(prefix, 1)
        else:
            add(prefix, 2)
    ranked.sort()
    return [p for _s, p in ranked]


def candidate_prefixes() -> tuple[list[str], list[str]]:
    """返回 (可用 /24 前缀, 被排除的 IP)，按可信度排序。"""
    skipped: list[str] = []
    ranked: list[tuple[int, str]] = []

    def add(prefix: str, score: int) -> None:
        if all(prefix != p for _s, p in ranked):
            ranked.append((score, prefix))

    # 1. 有默认网关的网卡最可信
    for prefix in _prefixes_with_gateway():
        add(prefix, 0)

    # 2. 其余私网地址（排除虚拟网段）作为备选
    for ip in local_ipv4_list():
        if is_virtual_ip(ip):
            skipped.append(ip)
            continue
        prefix = ip.rsplit(".", 1)[0]
        if prefix.startswith("192.168."):
            score = 1
        elif prefix.startswith("10."):
            score = 2
        else:
            score = 3   # 172.16/12 多为 WSL / Hyper-V
        add(prefix, score)

    ranked.sort()
    return [p for _s, p in ranked], skipped


def prefix_from_network(network: str) -> str:
    """把 192.168.2.0/24 或 192.168.2 规整成 192.168.2。"""
    network = network.strip()
    if "/" in network:
        try:
            net = ipaddress.ip_network(network, strict=False)
            if net.num_addresses == 256:
                return str(net.network_address).rsplit(".", 1)[0]
        except ValueError:
            return ""
    parts = network.split(".")
    if len(parts) == 3 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return network
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return ".".join(parts[:3])
    return ""


# ---------------------------------------------------------------- 探测
def _tcp_open(ip: str, port: int, timeout: float) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        return sock.connect_ex((ip, port)) == 0
    except OSError:
        return False
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _ping(ip: str, timeout_ms: int = 400) -> bool:
    cmd = (
        ["ping", "-n", "1", "-w", str(timeout_ms), ip]
        if sys.platform == "win32"
        else ["ping", "-c", "1", "-W", "1", ip]
    )
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_ms / 1000 + 1.5,
            creationflags=_NO_WINDOW,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _trigger_arp(prefix: str, probe_port: int = 445) -> None:
    """向网段内所有地址发 UDP 空包，逼出 ARP 缓存。"""
    port = probe_port if 0 < probe_port < 65536 else 9
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for host in range(1, 255):
            try:
                sock.sendto(b"\x00", (f"{prefix}.{host}", port))
            except OSError:
                pass


def _hostname(ip: str) -> str:
    try:
        name = socket.gethostbyaddr(ip)[0]
        return name.split(".")[0]
    except (OSError, socket.error):
        return ""


def scan(
    prefixes: list[str],
    *,
    verify: bool = True,
    probe_port: int = 445,
    on_progress=None,
    should_stop=None,
    on_found=None,
) -> ScanReport:
    """扫描指定 /24 网段，返回存活机器列表。

    verify=True 时会并发做 ping/TCP 确认，过滤掉 ARP 缓存里的残留条目。
    should_stop: 可选回调，返回 True 时尽快结束（用于取消扫描）。
    on_found: 可选回调，每确认一台设备回调一次，用于界面实时显示。
    """
    report = ScanReport(prefixes=list(prefixes))
    valid = [p for p in prefixes if prefix_from_network(p)]
    if not valid:
        report.error = "没有可扫描的网段"
        return report

    stopped = should_stop or (lambda: False)

    for p in valid:
        if stopped():
            return report
        _trigger_arp(p, probe_port)
    if on_progress:
        on_progress(f"已扫描 {', '.join(p + '.1–254' for p in valid)}")

    table = arp_table()
    entries = {
        ip: mac
        for mac, ip in table.items()
        if any(ip.startswith(f"{p}.") for p in valid)
    }

    if stopped():
        return report

    # 按 IP 排序后再验证，这样实时出现的顺序是从小到大，不会跳来跳去
    ordered = sorted(entries.items(), key=lambda kv: tuple(int(x) for x in kv[0].split(".")))

    found_items: list[Found] = []
    if verify and ordered:
        # 并发验证。并发数不能太高：每台都要起 ping 子进程，
        # 16 路并发时进程创建会互相拖慢，导致真实设备被误判离线。
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                pool.submit(_is_alive, ip, probe_port): (ip, mac)
                for ip, mac in ordered
            }
            done_count = 0
            for fut in as_completed(futures):
                ip, mac = futures[fut]
                try:
                    alive = bool(fut.result())
                except Exception:
                    alive = True
                item = Found(ip=ip, mac=normalize_mac(mac), alive=alive)
                found_items.append(item)
                done_count += 1
                if on_progress:
                    on_progress(
                        f"正在验证 {done_count}/{len(ordered)}…", keep=True
                    )
                if on_found:
                    on_found(item)
                if stopped():
                    for f in futures:
                        f.cancel()
                    break
    else:
        for ip, mac in ordered:
            item = Found(ip=ip, mac=normalize_mac(mac), alive=True)
            found_items.append(item)
            if on_found:
                on_found(item)

    if stopped():
        return report

    found_items.sort(key=lambda f: tuple(int(x) for x in f.ip.split(".")))

    # 主机名并发反查，查到一个补一个
    to_name = [f for f in found_items if f.alive]
    if to_name:
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(_hostname, f.ip): f for f in to_name}
            for fut in as_completed(futures):
                item = futures[fut]
                try:
                    item.hostname = fut.result()
                except Exception:
                    item.hostname = ""
                if on_found:
                    on_found(item)

    report.found = found_items
    if not found_items:
        report.error = "未发现任何设备，请确认与目标处于同一局域网"
    return report


def _is_alive(ip: str, probe_port: int) -> bool:
    """TCP 探测端口通，或 ping 通，任一即算在线。

    必须用 probe.tcp_reachable 而不是裸 connect：本机装 TUN 代理时，
    任意地址任意端口的 TCP 都会「连上」，会把不存在的主机判成在线。

    ping 超时给足 700ms：并发扫描时子进程启动有额外开销，
    350ms 会把真实在线但响应慢的设备误判为离线。
    """
    if probe_port and tcp_reachable(ip, probe_port, 0.3):
        return True
    return _ping(ip, 700)
