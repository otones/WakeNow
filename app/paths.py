"""路径工具：数据文件、资源目录在源码运行与 PyInstaller 打包后都可用。"""
from __future__ import annotations

import os
import sys


def app_dir() -> str:
    """exe（打包后）或项目根目录（开发时）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_file(name: str = "machines.json") -> str:
    return os.path.join(app_dir(), name)


def settings_file() -> str:
    """本机偏好设置，与机器列表分开存放。"""
    return os.path.join(app_dir(), "settings.json")
