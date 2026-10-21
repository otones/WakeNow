"""开发用截图工具：渲染主窗口 / 对话框 / Toast，便于与设计稿比对。

用法：
    python tools/shot.py [输出目录]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.models import (
    STATUS_OFFLINE,
    STATUS_ONLINE,
    STATUS_UNKNOWN,
    STATUS_WAKING,
    Machine,
)
from app.theme import app_font, palette
from app.widgets.dialogs import MachineDialog
from app.widgets.main_window import MainWindow

DEMO = [
    ("书房主机", "192.168.2.10", "AA:BB:CC:11:22:01", STATUS_ONLINE),
    ("群晖 NAS", "192.168.2.20", "AA:BB:CC:11:22:02", STATUS_OFFLINE),
    ("客厅 PC", "192.168.2.30", "AA:BB:CC:11:22:03", STATUS_WAKING),
    ("工作站", "192.168.2.40", "AA:BB:CC:11:22:04", STATUS_OFFLINE),
    ("树莓派", "192.168.2.50", "AA:BB:CC:11:22:05", STATUS_ONLINE),
    ("影音主机", "192.168.2.60", "AA:BB:CC:11:22:06", STATUS_ONLINE),
]


class _NullStore:
    def save(self, machines):
        pass

    load_warning = None


def make_machines() -> list[Machine]:
    machines = [
        Machine(name=n, mac=m, ip=i, status=s, id=f"id{k}")
        for k, (n, i, m, s) in enumerate(DEMO)
    ]
    # 追加一台「自动发现 IP」与一台「尚未发现」的机器，覆盖新增状态
    auto = Machine(
        name="下载机", mac="AA:BB:CC:11:22:07", ip="192.168.2.70",
        status=STATUS_ONLINE, id="id6",
    )
    auto.discovered = True
    machines.append(auto)
    machines.append(
        Machine(name="备用机", mac="AA:BB:CC:11:22:08",
                status=STATUS_UNKNOWN, id="id7")
    )
    return machines


def build(dark: bool, machines: list[Machine]) -> MainWindow:
    win = MainWindow(machines, _NullStore(), palette(dark))  # type: ignore[arg-type]
    win.set_scan_requester(lambda: None)
    win.set_discover_requester(lambda force=None: None)
    # 用窗口自身的最小宽度，避免小于它导致底栏文字被压
    win.resize(max(560, win.minimumWidth()), 420)
    return win


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "shots"
    os.makedirs(out, exist_ok=True)

    app = QApplication(sys.argv)
    app.setFont(app_font())
    app.setWindowIcon(QIcon())

    # --- 主窗口 4 态
    for name, dark, empty in [
        ("light", False, False),
        ("dark", True, False),
        ("light-empty", False, True),
        ("dark-empty", True, True),
    ]:
        win = build(dark, [] if empty else make_machines())
        win.show()
        app.processEvents()
        if not empty:
            for mid in ("id1", "id3"):
                if mid in win._rows:
                    win._selected.add(mid)
                    win._rows[mid].set_selected(True)
            win._update_select_all()
            win._update_wake_button()
        app.processEvents()
        win.grab().save(os.path.join(out, f"{name}.png"))
        win.close()

    # --- 对话框
    for name, dark, with_error in [
        ("dialog", False, False),
        ("dialog-error", False, True),
    ]:
        win = build(dark, make_machines())
        win.show()
        app.processEvents()
        dlg = MachineDialog(palette(dark), None, win)
        if with_error:
            dlg.fields["ip"].edit.setText("192.168.2.300")
            dlg.fields["mac"].edit.setText("AA:BB:CC")
            dlg._save()
        dlg.show()
        app.processEvents()
        dlg.grab().save(os.path.join(out, f"{name}.png"))
        dlg.close()
        win.close()

    # --- Toast
    for name, dark, kind, text in [
        ("toast-success", False, "success", "已向 2 台机器发送唤醒包"),
        ("toast-info", False, "info", "1 台已在线，已跳过"),
        ("toast-error", True, "error", "发送失败，请检查网络连接"),
    ]:
        win = build(dark, make_machines())
        win.show()
        app.processEvents()
        win.toast(kind, text)
        # 等淡入动画（220ms）走完再截图
        deadline = 0
        while deadline < 40:
            app.processEvents()
            QApplication.instance().thread().msleep(10)
            deadline += 1
        win.grab().save(os.path.join(out, f"{name}.png"))
        win.close()

    print("saved to", os.path.abspath(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
