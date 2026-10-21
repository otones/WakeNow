"""本机偏好设置：settings.json。

与 machines.json 分开存放——前者是本机偏好（不该跟着导出走），
后者是用户数据（要导入导出）。
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

DEFAULT_INTERVAL_MS = 3000


@dataclass
class Settings:
    minimize_to_tray: bool = True       # 点 × 隐藏到托盘
    tray_hint_shown: bool = False       # 是否已提示过「已最小化到托盘」
    start_minimized: bool = False       # 开机自启时最小化启动
    probe_interval_ms: int = DEFAULT_INTERVAL_MS
    theme: str = "system"               # system | light | dark（预留）

    # 非持久化字段
    _path: str = field(default="", repr=False, compare=False)

    # ------------------------------------------------------------ 读写
    @classmethod
    def load(cls, path: str) -> "Settings":
        obj = cls()
        obj._path = path
        if not os.path.exists(path):
            return obj
        try:
            # utf-8-sig：容忍编辑器写入的 BOM
            with open(path, "r", encoding="utf-8-sig") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                return obj
        except Exception:
            # 配置损坏不该影响启动，静默用默认值
            return obj

        if isinstance(raw.get("minimize_to_tray"), bool):
            obj.minimize_to_tray = raw["minimize_to_tray"]
        if isinstance(raw.get("tray_hint_shown"), bool):
            obj.tray_hint_shown = raw["tray_hint_shown"]
        if isinstance(raw.get("start_minimized"), bool):
            obj.start_minimized = raw["start_minimized"]
        if isinstance(raw.get("theme"), str) and raw["theme"] in (
            "system",
            "light",
            "dark",
        ):
            obj.theme = raw["theme"]
        interval = raw.get("probe_interval_ms")
        if isinstance(interval, int) and 800 <= interval <= 60000:
            obj.probe_interval_ms = interval
        return obj

    def to_dict(self) -> dict:
        return {
            "minimize_to_tray": self.minimize_to_tray,
            "tray_hint_shown": self.tray_hint_shown,
            "start_minimized": self.start_minimized,
            "probe_interval_ms": self.probe_interval_ms,
            "theme": self.theme,
        }

    def save(self) -> None:
        if not self._path:
            return
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except OSError:
            # 设置存不下来不算致命错误，忽略
            pass
