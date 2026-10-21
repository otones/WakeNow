"""机器列表导入导出。

导出带版本头；导入同时兼容「带版本头的文件」和「裸数组」（即直接拿
machines.json 导入）。导入不静默覆盖，而是交回调用方让用户选策略。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime

from .models import Machine, is_mac, normalize_mac

EXPORT_VERSION = 2
DEFAULT_SUFFIX = ".json"


class ImportError_(Exception):
    """导入失败（文件不可读、格式非法等）。"""


@dataclass
class ImportResult:
    machines: list[Machine] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)   # 被跳过的原因描述
    used_machines_key: bool = True                     # 是否带版本头


@dataclass
class MergePlan:
    added: list[Machine] = field(default_factory=list)
    existing: list[Machine] = field(default_factory=list)   # MAC 已存在，将跳过


# ---------------------------------------------------------------- 导出
def export_payload(machines: list[Machine]) -> dict:
    return {
        "app": "WakeNow",
        "version": EXPORT_VERSION,
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "machines": [m.to_json() for m in machines],
    }


def export_to_file(machines: list[Machine], path: str) -> int:
    """写入文件，返回导出的机器数。"""
    payload = export_payload(machines)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return len(machines)


def default_export_name() -> str:
    return f"wakenow-machines-{datetime.now().strftime('%Y%m%d')}{DEFAULT_SUFFIX}"


# ---------------------------------------------------------------- 导入
def _extract_items(raw) -> tuple[list, bool]:
    """从解析后的 JSON 里取出机器数组。

    返回 (items, used_machines_key)。
    """
    if isinstance(raw, list):
        return raw, False
    if isinstance(raw, dict):
        items = raw.get("machines")
        if isinstance(items, list):
            return items, True
        raise ImportError_("文件里没有 machines 字段")
    raise ImportError_("文件格式不正确：应为数组或包含 machines 的对象")


def load_from_file(path: str) -> ImportResult:
    """解析导入文件，做逐条校验。非法条目计入 skipped。"""
    try:
        # utf-8-sig 容忍 BOM
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
    except json.JSONDecodeError as exc:
        raise ImportError_(f"不是合法的 JSON：{exc}") from exc
    except OSError as exc:
        raise ImportError_(f"无法读取文件：{exc}") from exc

    items, used_key = _extract_items(raw)

    result = ImportResult(used_machines_key=used_key)
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            result.skipped.append(f"第 {idx + 1} 条不是对象")
            continue
        name = str(item.get("name", "")).strip()
        mac = normalize_mac(str(item.get("mac", "")))
        if not name:
            result.skipped.append(f"第 {idx + 1} 条缺少名称")
            continue
        if not is_mac(mac):
            result.skipped.append(f"第 {idx + 1} 条 MAC 非法")
            continue
        result.machines.append(Machine.from_json(item))
    return result


# ---------------------------------------------------------------- 合并
def plan_merge(
    incoming: list[Machine], existing: list[Machine]
) -> MergePlan:
    """按 MAC 去重：已有 MAC 的跳过，其余作为新增。"""
    known = {m.display_mac for m in existing}
    plan = MergePlan()
    seen: set[str] = set()
    for m in incoming:
        mac = m.display_mac
        if mac in known or mac in seen:
            plan.existing.append(m)
            continue
        seen.add(mac)
        plan.added.append(m)
    return plan


def safe_filename(name: str) -> str:
    """去掉 Windows 文件名非法字符。"""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip() or "export"
