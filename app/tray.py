"""托盘图标：常驻、右键菜单、最小化提示。"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .icons import app_icon, icon
from .theme import Palette


class Tray(QObject):
    show_requested = Signal()
    wake_offline_requested = Signal()
    refresh_requested = Signal()
    autostart_toggled = Signal(bool)
    quit_requested = Signal()

    def __init__(self, pal: Palette, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pal = pal
        self._icon = QSystemTrayIcon(app_icon(), self)
        self._icon.setToolTip("WakeNow")
        self._menu = self._build_menu()
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._on_activated)
        self._hint_shown = False

    # ---------------------------------------------------------------- 可用性
    @staticmethod
    def is_available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    # ---------------------------------------------------------------- 菜单
    def _build_menu(self) -> QMenu:
        p = self._pal
        menu = QMenu()
        menu.setStyleSheet(
            f"QMenu{{background:{p.h('bg')};border:1px solid {p.rgba('border')};"
            f"border-radius:8px;padding:5px;}}"
            f"QMenu::item{{height:30px;padding:0 20px 0 10px;border-radius:6px;"
            f"color:{p.h('txt2')};font-size:12px;}}"
            f"QMenu::item:selected{{background:{p.h('surface_hi')};color:{p.h('txt')};}}"
            f"QMenu::separator{{height:1px;background:{p.rgba('hairline')};margin:4px 6px;}}"
        )

        act_show = QAction(icon("tray", 14, p.c("txt2")), "显示主窗口", menu)
        act_show.triggered.connect(self.show_requested.emit)
        menu.addAction(act_show)
        menu.addSeparator()

        act_wake = QAction(icon("bolt", 14, p.c("txt2")), "唤醒所有离线机器", menu)
        act_wake.triggered.connect(self.wake_offline_requested.emit)
        menu.addAction(act_wake)

        act_refresh = QAction(icon("refresh", 14, p.c("txt2")), "立即刷新状态", menu)
        act_refresh.triggered.connect(self.refresh_requested.emit)
        menu.addAction(act_refresh)
        menu.addSeparator()

        self._act_auto = QAction(icon("power2", 14, p.c("txt2")), "开机自启", menu)
        self._act_auto.setCheckable(True)
        self._act_auto.toggled.connect(self.autostart_toggled.emit)
        menu.addAction(self._act_auto)
        menu.addSeparator()

        act_quit = QAction(icon("close", 14, p.c("txt2")), "退出", menu)
        act_quit.triggered.connect(self.quit_requested.emit)
        menu.addAction(act_quit)

        self._act_show = act_show
        return menu

    # ---------------------------------------------------------------- 状态
    def show(self) -> None:
        self._icon.show()

    def hide(self) -> None:
        self._icon.hide()

    def set_autostart(self, enabled: bool) -> None:
        """同步勾选状态，但不触发 toggled 信号（避免回环调用）。"""
        self._act_auto.blockSignals(True)
        self._act_auto.setChecked(enabled)
        self._act_auto.blockSignals(False)

    # ---------------------------------------------------------------- 交互
    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,       # 单击
            QSystemTrayIcon.ActivationReason.DoubleClick,   # 双击
        ):
            self.show_requested.emit()

    def notify_once(self, title: str, text: str) -> None:
        """首次最小化到托盘时提示一次。"""
        if self._hint_shown:
            return
        self._hint_shown = True
        self._icon.showMessage(
            title, text, QSystemTrayIcon.MessageIcon.Information, 4000
        )

    def notify(self, title: str, text: str) -> None:
        self._icon.showMessage(
            title, text, QSystemTrayIcon.MessageIcon.Information, 3000
        )
