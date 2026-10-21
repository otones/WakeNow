"""开机自启：读写 HKCU 的 Run 键（不需要管理员权限）。

两个必须处理的细节：
1. 路径含空格时必须加引号，否则开机启动会失败
2. 不能只写不读——用户可能在任务管理器禁用了、或 exe 被移动过，
   所以每次都要回读并比对当前路径
"""
from __future__ import annotations

import os
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "WakeNow"
ARG_MINIMIZED = "--minimized"


def _command_line() -> str:
    """构造写入注册表的启动命令。"""
    if getattr(sys, "frozen", False):
        exe = sys.executable
        return f'"{exe}" {ARG_MINIMIZED}'
    # 源码运行：python 解释器 + 入口脚本
    python = sys.executable
    entry = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py"
    )
    return f'"{python}" "{entry}" {ARG_MINIMIZED}'


def is_supported() -> bool:
    return sys.platform == "win32"


def _open_key(write: bool):
    import winreg

    return winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        RUN_KEY,
        0,
        winreg.KEY_SET_VALUE if write else winreg.KEY_READ,
    )


def current_value() -> str | None:
    """读取注册表里现有的自启命令；不存在返回 None。"""
    if not is_supported():
        return None
    try:
        import winreg

        with _open_key(write=False) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return str(value)
    except OSError:
        return None


def is_enabled() -> bool:
    """是否已启用，且指向当前这个程序。

    路径不一致（比如 exe 被移动过）视为「未启用」，避免界面显示已开启
    实际开机却启动不了的错觉。
    """
    value = current_value()
    if not value:
        return False
    return _normalize(value) == _normalize(_command_line())


def stored_path_differs() -> bool:
    """注册表里有自启项，但指向的不是当前程序（需要提示更新）。"""
    value = current_value()
    if not value:
        return False
    return _normalize(value) != _normalize(_command_line())


def _normalize(cmd: str) -> str:
    """比较时忽略大小写与引号差异。"""
    return cmd.strip().strip('"').lower().replace('"', "")


def enable() -> bool:
    """启用自启，返回是否成功。"""
    if not is_supported():
        return False
    try:
        import winreg

        with _open_key(write=True) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command_line())
        return True
    except OSError:
        return False


def disable() -> bool:
    if not is_supported():
        return False
    try:
        import winreg

        with _open_key(write=True) as key:
            winreg.DeleteValue(key, VALUE_NAME)
        return True
    except FileNotFoundError:
        return True          # 本来就没有，视为成功
    except OSError:
        return False


def set_enabled(enabled: bool) -> bool:
    return enable() if enabled else disable()
