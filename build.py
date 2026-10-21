"""打包脚本：PyInstaller 单文件 exe。

用法：
    python build.py
产物：
    dist/WakeNow.exe
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "WakeNow"


def main() -> int:
    icon_path = os.path.join(ROOT, "assets", "wakenow.ico")
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        NAME,
        # 把 ICO 一起打进去：任务栏图标要从文件加载多尺寸版本，
        # 只靠 exe 内嵌资源在 125% 缩放下会变小发虚
        "--add-data",
        f"{icon_path};assets",
        # 只保留用得到的 Qt 模块，避免把 WebEngine 等整包塞进去
        "--exclude-module",
        "PySide6.QtWebEngineCore",
        "--exclude-module",
        "PySide6.QtWebEngineWidgets",
        "--exclude-module",
        "PySide6.QtWebEngineQuick",
        "--exclude-module",
        "PySide6.QtQml",
        "--exclude-module",
        "PySide6.QtQuick",
        "--exclude-module",
        "PySide6.QtQuickWidgets",
        "--exclude-module",
        "PySide6.QtPdf",
        "--exclude-module",
        "PySide6.QtPdfWidgets",
        "--exclude-module",
        "PySide6.Qt3DCore",
        "--exclude-module",
        "PySide6.QtMultimedia",
        "--exclude-module",
        "tkinter",
        "--exclude-module",
        "unittest",
        "--exclude-module",
        "pydoc",
        "--paths",
        ROOT,
        "--hidden-import",
        "PySide6.QtSvg",
        os.path.join(ROOT, "main.py"),
    ]
    if os.path.exists(icon_path):
        args += ["--icon", icon_path]

    print("running:", " ".join(args))
    result = subprocess.run(args, cwd=ROOT)
    if result.returncode != 0:
        print("打包失败")
        return result.returncode

    exe = os.path.join(ROOT, "dist", f"{NAME}.exe")
    if not os.path.exists(exe):
        print("未找到产物", exe)
        return 1
    print(f"\n完成：{exe}")
    print(f"体积：{os.path.getsize(exe) / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
