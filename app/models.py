"""数据模型：机器实体、字段校验、JSON 持久化。"""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

# ---------------------------------------------------------------- 状态常量
STATUS_ONLINE = "online"
STATUS_OFFLINE = "offline"
STATUS_WAKING = "waking"
STATUS_UNKNOWN = "unknown"

STATUS_LABEL = {
    STATUS_ONLINE: "在线",
    STATUS_OFFLINE: "离线",
    STATUS_WAKING: "唤醒中",
    STATUS_UNKNOWN: "检测中",
}

# ---------------------------------------------------------------- 探测方式
PROBE_AUTO = "auto"     # ping 优先，失败再用 TCP（推荐）
PROBE_PING = "ping"     # 只看 ICMP
PROBE_TCP = "tcp"       # 只看 TCP 端口

PROBE_LABEL = {
    PROBE_AUTO: "自动（ping + TCP）",
    PROBE_PING: "仅 ping",
    PROBE_TCP: "仅 TCP",
}
PROBE_CHOICES = [PROBE_AUTO, PROBE_PING, PROBE_TCP]
DEFAULT_PROBE_PORT = 445   # Windows 默认监听 SMB，命中率最高


# ---------------------------------------------------------------- 校验
_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")
_MAC_ANY_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")


def is_ip(value: str) -> bool:
    v = (value or "").strip()
    if not _IP_RE.match(v):
        return False
    return all(0 <= int(part) <= 255 for part in v.split("."))


def normalize_mac(value: str) -> str:
    """接受任意分隔/大小写，输出 AA:BB:CC:DD:EE:FF。"""
    raw = re.sub(r"[^0-9A-Fa-f]", "", value or "").upper()
    if len(raw) != 12:
        return (value or "").strip()
    return ":".join(raw[i:i + 2] for i in range(0, 12, 2))


def is_mac(value: str) -> bool:
    return bool(_MAC_RE.match(normalize_mac(value)))


def default_broadcast(ip: str, *, local_ip: str | None = None) -> str:
    """/24 广播地址推算。

    优先按机器自身 IP 推算；没有 IP 时用本机网段（调用方传入 local_ip）；
    都拿不到则退回受限广播 255.255.255.255。
    """
    for candidate in (ip, local_ip or ""):
        if is_ip(candidate):
            return candidate.rsplit(".", 1)[0] + ".255"
    return "255.255.255.255"


def validate_field(key: str, value: str) -> str:
    """返回空串表示通过，否则返回错误文案（与设计稿一致）。

    只有「名称」和「MAC」必填：唤醒只需要 MAC，IP 仅用于探测在线状态，
    而 DHCP 分配的 IP 会变，不该强制填写。
    """
    v = (value or "").strip()
    if key == "name":
        return "" if v else "请输入机器名称"
    if key == "ip":
        # 选填：留空表示「自动发现」
        return "" if (not v or is_ip(v)) else "IP 格式不正确，例如 192.168.2.10"
    if key == "mac":
        if not v:
            return "请输入 MAC 地址"
        return "" if is_mac(v) else "MAC 需为 12 位十六进制，例如 AA:BB:CC:DD:EE:FF"
    if key == "broadcast":
        return "" if (not v or is_ip(v)) else "广播地址格式不正确"
    if key == "port":
        return "" if (not v or (v.isdigit() and 0 < int(v) < 65536)) else "端口需为 1–65535"
    return ""


# ---------------------------------------------------------------- 实体
@dataclass
class Machine:
    name: str
    mac: str
    ip: str = ""            # 可选：留空表示自动发现
    broadcast: str = ""
    port: int = 9                      # WOL 端口（UDP）
    probe: str = PROBE_AUTO            # 探测方式：auto / ping / tcp
    probe_port: int = DEFAULT_PROBE_PORT   # TCP 探测端口，0 表示不探测
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status: str = STATUS_UNKNOWN
    discovered: bool = False   # 当前 IP 是否为自动发现所得
    probe_detail: str = ""     # 最近一次判定依据（供 tooltip）

    # --- 派生属性
    @property
    def has_ip(self) -> bool:
        return is_ip(self.ip)

    @property
    def probe_port_or_none(self) -> int:
        """有效探测端口；0 / 非法值返回 0 表示不探测。"""
        return self.probe_port if 0 < self.probe_port < 65536 else 0

    def broadcast_addr(self, local_ip: str | None = None) -> str:
        return self.broadcast.strip() or default_broadcast(self.ip, local_ip=local_ip)

    @property
    def display_mac(self) -> str:
        return normalize_mac(self.mac)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "mac": self.display_mac,
            "ip": self.ip,
            "broadcast": self.broadcast,
            "port": self.port,
            "probe": self.probe,
            "probe_port": self.probe_port,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "Machine":
        port = raw.get("port", 9)
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = 9
        ip = str(raw.get("ip", "")).strip()

        probe = str(raw.get("probe", PROBE_AUTO)).strip()
        if probe not in PROBE_CHOICES:
            probe = PROBE_AUTO

        probe_port_raw = raw.get("probe_port", DEFAULT_PROBE_PORT)
        try:
            probe_port = int(probe_port_raw)
        except (TypeError, ValueError):
            probe_port = DEFAULT_PROBE_PORT
        if not (0 <= probe_port < 65536):
            probe_port = DEFAULT_PROBE_PORT

        return cls(
            name=str(raw.get("name", "")).strip(),
            mac=normalize_mac(str(raw.get("mac", ""))),
            ip=ip if is_ip(ip) else "",
            broadcast=str(raw.get("broadcast", "")).strip(),
            port=port if 0 < port < 65536 else 9,
            probe=probe,
            probe_port=probe_port,
            id=str(raw.get("id") or uuid.uuid4().hex[:8]),
        )


# ---------------------------------------------------------------- 存储
class MachineStore:
    """machines.json 的读写。损坏时备份原文件并以空列表启动。"""

    def __init__(self, path: str) -> None:
        self.path = path
        self.load_warning: str | None = None

    def load(self) -> list[Machine]:
        self.load_warning = None
        if not os.path.exists(self.path):
            return []
        try:
            # utf-8-sig：兼容记事本等编辑器写入的 BOM
            with open(self.path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("根节点必须是数组")
            machines = [Machine.from_json(x) for x in data if isinstance(x, dict)]
            # 丢弃缺关键字段的脏数据（名称 + MAC 必需，IP 可空）
            return [m for m in machines if m.name and is_mac(m.mac)]
        except Exception as exc:  # 损坏 / 编码错误 / 非法 JSON
            backup = self.path + ".bak"
            try:
                shutil.copy2(self.path, backup)
            except OSError:
                backup = ""
            self.load_warning = (
                f"配置文件无法读取（{exc}），已备份为 {os.path.basename(backup) or '备份文件'}，"
                "本次以空列表启动。"
            )
            return []

    def save(self, machines: Iterable[Machine]) -> None:
        payload = [m.to_json() for m in machines]
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)  # 原子替换，避免写坏
