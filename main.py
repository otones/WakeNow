"""WakeNow 入口。"""
from __future__ import annotations

import os
import sys
import traceback

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from app import autostart, paths
from app.icons import app_icon
from app.models import MachineStore
from app.monitor import Discoverer, Monitor
from app.settings import Settings
from app.theme import app_font, palette, resolve_dark
from app.tray import Tray
from app.widgets.main_window import MainWindow


def _excepthook(exc_type, exc_value, exc_tb) -> None:
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    sys.stderr.write(text)
    try:
        QMessageBox.critical(
            None,
            "WakeNow 出错了",
            f"程序遇到未处理的错误：\n\n{exc_value}",
        )
    except Exception:
        pass


def main() -> int:
    # 单实例检查要尽早：第二个实例不该做任何初始化
    from app.single_instance import SingleInstance

    instance = SingleInstance()

    app = QApplication(sys.argv)
    app.setApplicationName("WakeNow")
    app.setApplicationDisplayName("WakeNow")
    app.setApplicationVersion("1.2.0")
    # 有托盘常驻，窗口全部隐藏时不能退出
    app.setQuitOnLastWindowClosed(False)
    app.setFont(app_font())
    sys.excepthook = _excepthook
    app.setWindowIcon(app_icon())

    if not instance.acquire():
        # 已有实例：唤起它，然后安静退出
        return 0

    settings = Settings.load(paths.settings_file())
    store = MachineStore(paths.data_file())
    machines = store.load()

    # 按用户设置决定配色（默认跟随系统）
    dark = resolve_dark(settings.theme)
    pal = palette(dark)

    win = MainWindow(machines, store, pal)
    win.setWindowIcon(app_icon())
    win._theme = settings.theme
    win._minimize_to_tray = settings.minimize_to_tray
    win._settings_saver = settings.save

    def _persist_theme(theme: str) -> None:
        settings.theme = theme
        settings.save()

    win._theme_changed = _persist_theme

    # ---------------------------------------------------------------- 托盘
    tray = None
    if Tray.is_available():
        tray = Tray(pal)
        win._tray_available = True
        tray.show()
        tray.show_requested.connect(lambda: _show_window())
        tray.refresh_requested.connect(lambda: _rescan())
        tray.wake_offline_requested.connect(lambda: _wake_all_offline())
        tray.quit_requested.connect(lambda: _real_quit())
        tray.autostart_toggled.connect(lambda on: _toggle_autostart(on))
        win.hide_to_tray.connect(lambda: _on_hidden_to_tray())
    else:
        # 托盘不可用：× 就是退出
        win._tray_available = False
        win._minimize_to_tray = False

    # ---------------------------------------------------------------- 自启
    def _autostart_state() -> bool:
        return autostart.is_enabled()

    def _toggle_autostart(enabled: bool) -> None:
        ok = autostart.set_enabled(enabled)
        if not ok:
            win.toast("error", "修改开机自启失败")
        else:
            win.toast(
                "success",
                "已开启开机自启" if enabled else "已关闭开机自启",
            )
        if tray is not None:
            tray.set_autostart(autostart.is_enabled())

    win._autostart_getter = _autostart_state
    win._autostart_setter = _toggle_autostart
    if tray is not None:
        tray.set_autostart(_autostart_state())

    # ---------------------------------------------------------------- 监控
    monitor = Monitor(interval_ms=settings.probe_interval_ms)
    monitor.set_targets(win.scan_targets())
    monitor.scanned.connect(win.on_scan)

    discoverer = Discoverer()
    discoverer.finished.connect(win.on_discovered)

    def _rescan() -> None:
        monitor.set_targets(win.scan_targets())
        monitor.scan_now()

    def _discover(_force=None) -> None:
        targets = win.discover_targets()
        if targets:
            discoverer.request(targets, win.known_ips())

    win.set_scan_requester(_rescan)
    win.set_discover_requester(_discover)
    monitor.start()

    # ================================================================ 窗口
    def _show_window() -> None:
        # 从托盘/隐藏状态恢复时，FramelessWindowHint 窗口需要先 show()，
        # 否则仅 showNormal() 可能不生效
        if not win.isVisible():
            win.show()
        win.setWindowState(
            (win.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive
        )
        win.showNormal()
        win.raise_()
        win.activateWindow()

    def _on_hidden_to_tray() -> None:
        if tray is not None and not settings.tray_hint_shown:
            tray.notify_once(
                "WakeNow 仍在运行",
                "已最小化到托盘。右键托盘图标可退出。",
            )
            settings.tray_hint_shown = True
            settings.save()

    def _wake_all_offline() -> None:
        win._on_select_offline()
        win._on_wake()

    def _real_quit() -> None:
        monitor.stop()
        discoverer.stop()
        instance.release()
        if tray is not None:
            tray.hide()
        app.quit()

    # 第二个实例请求唤起
    instance.activate_requested.connect(_show_window)

    QTimer.singleShot(300, lambda: _discover())

    # ---------------------------------------------------------------- 启动形态
    start_minimized = (
        settings.start_minimized or "--minimized" in sys.argv
    ) and tray is not None

    if start_minimized:
        _on_hidden_to_tray()
        if settings.tray_hint_shown:
            # 已提示过就不再打扰，仅静默驻留
            pass
    else:
        win.show()

    if store.load_warning:
        QTimer.singleShot(400, lambda: win.toast("error", store.load_warning))
    elif settings.tray_hint_shown is False and start_minimized:
        pass

    app.aboutToQuit.connect(lambda: (monitor.stop(), discoverer.stop()))

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
