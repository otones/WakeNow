"""列表行：复选框 + 名称/MAC + IP + 状态点。44px 行高。"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..models import (
    STATUS_LABEL,
    STATUS_OFFLINE,
    STATUS_ONLINE,
    STATUS_UNKNOWN,
    STATUS_WAKING,
    Machine,
)
from ..theme import Palette
from .checkbox import CheckBox

ROW_HEIGHT = 44
COL_CB = 46
COL_IP = 132
COL_STATUS = 118
PAD = 14
MONO = '"Cascadia Mono","Consolas",monospace'


def _rgba(c: QColor, alpha: int) -> str:
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


class MachineRow(QWidget):
    toggled = Signal(str)          # machine id
    editRequested = Signal(str)
    deleteRequested = Signal(str)
    wakeRequested = Signal(str)

    def __init__(self, machine: Machine, pal: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.machine = machine
        self._pal = pal
        self._selected = False
        self._hover = False
        self._sweep = 0.0

        self.setFixedHeight(ROW_HEIGHT)
        self.setContextMenuPolicy(Qt.CustomContextMenu)

        self.cb = CheckBox(pal, self)
        self.cb.clicked.connect(lambda: self.toggled.emit(self.machine.id))

        self.name = QLabel(machine.name, self)
        self.mac = QLabel(machine.display_mac, self)
        self.ip = QLabel("", self)
        self.status_text = QLabel("", self)
        self.status_dot = StatusDot(pal, self)

        cb_wrap = QWidget(self)
        cb_wrap.setFixedWidth(COL_CB)
        cbl = QHBoxLayout(cb_wrap)
        cbl.setContentsMargins(0, 0, 0, 0)
        cbl.addWidget(self.cb, 0, Qt.AlignLeft | Qt.AlignVCenter)

        name_col = QWidget(self)
        nl = QVBoxLayout(name_col)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(1)
        nl.addWidget(self.name)
        nl.addWidget(self.mac)
        nl.setAlignment(Qt.AlignVCenter)

        st_wrap = QWidget(self)
        st_wrap.setFixedWidth(COL_STATUS)
        sl = QHBoxLayout(st_wrap)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)
        sl.addWidget(self.status_dot, 0, Qt.AlignVCenter)
        sl.addWidget(self.status_text, 0, Qt.AlignVCenter)
        sl.addStretch(1)

        self.ip.setFixedWidth(COL_IP - 8)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(PAD, 0, PAD, 0)
        lay.setSpacing(0)
        lay.addWidget(cb_wrap, 0)
        lay.addWidget(name_col, 1)
        lay.addSpacing(8)
        lay.addWidget(self.ip, 0, Qt.AlignVCenter)
        lay.addWidget(st_wrap, 0, Qt.AlignVCenter)

        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

        self._sync_ip()
        self.apply_style()

    # ------------------------------------------------------------ 主题 / 状态
    def set_palette(self, pal: Palette) -> None:
        self._pal = pal
        self.cb.set_palette(pal)
        self.status_dot.set_palette(pal)
        self.apply_style()

    def update_machine(self, machine: Machine) -> None:
        self.machine = machine
        self.name.setText(machine.name)
        self.mac.setText(machine.display_mac)
        self._sync_ip()
        self.apply_style()

    def _sync_ip(self) -> None:
        m = self.machine
        p = self._pal
        if m.has_ip:
            self.ip.setText(m.ip)
            self.ip.setToolTip(
                "由 ARP 自动发现（IP 变化会自动跟随）" if m.discovered else ""
            )
        else:
            self.ip.setText("自动发现")
            self.ip.setToolTip("无法探测在线状态：未获取到 IP")

    def apply_style(self) -> None:
        p = self._pal
        key = self.machine.status
        dimmed = key in (STATUS_OFFLINE,) or key not in (STATUS_ONLINE, STATUS_WAKING)
        alpha_txt = 115 if dimmed else 255

        self.name.setStyleSheet(
            f"font-size:13px;font-weight:500;color:{_rgba(p.c('txt'), alpha_txt)};"
            "background:transparent;letter-spacing:0.005em;"
        )
        self.mac.setStyleSheet(
            f"font-size:10px;color:{_rgba(p.c('txt3'), alpha_txt)};background:transparent;"
            f"font-family:{MONO};letter-spacing:0.06em;"
        )
        self.ip.setStyleSheet(
            f"font-size:12px;color:{_rgba(p.c('txt2'), alpha_txt)};background:transparent;"
            f"font-family:{MONO};"
        )

        if key == STATUS_ONLINE:
            self.status_text.setText("在线")
            self.status_text.setStyleSheet(
                f"font-size:12px;color:{p.h('txt')};font-weight:500;background:transparent;"
            )
        elif key == STATUS_WAKING:
            self.status_text.setText("唤醒中")
            self.status_text.setStyleSheet(
                f"font-size:12px;color:{p.h('waking')};font-weight:500;background:transparent;"
            )
        elif key == STATUS_UNKNOWN and not self.machine.has_ip:
            self.status_text.setText("未知")
            self.status_text.setToolTip("未获取到 IP，无法探测在线状态")
            self.status_text.setStyleSheet(
                f"font-size:12px;color:{_rgba(p.c('txt2'), alpha_txt)};background:transparent;"
            )
        else:
            self.status_text.setText(STATUS_LABEL.get(key, "离线"))
            self.status_text.setStyleSheet(
                f"font-size:12px;color:{_rgba(p.c('txt2'), alpha_txt)};background:transparent;"
            )

        self.status_dot.set_status(key)
        self.refresh_tooltip()
        if key == STATUS_WAKING:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self._sweep = 0.0
        self.update()

    def refresh_tooltip(self) -> None:
        """状态点/状态文字上显示判定依据。"""
        m = self.machine
        detail = getattr(m, "probe_detail", "") or ""
        if m.status == STATUS_UNKNOWN and not m.has_ip:
            text = "未获取到 IP，无法探测在线状态"
        elif m.status == STATUS_WAKING:
            text = "正在唤醒，等待开机…"
        elif detail:
            text = detail
        elif m.status == STATUS_ONLINE:
            text = "在线"
        else:
            text = "离线"
        self.status_text.setToolTip(text)
        self.status_dot.setToolTip(text)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.cb.set_state(CheckBox.STATE_ON if selected else CheckBox.STATE_OFF)
        self.update()

    def is_selected(self) -> bool:
        return self._selected

    # ------------------------------------------------------------ 动画
    def _tick(self) -> None:
        self._sweep = (self._sweep + 0.012) % 1.0
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.editRequested.emit(self.machine.id)
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        p = self._pal
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        r = self.rect()

        # 先铺不透明底色，避免半透明叠加露出黑色
        painter.fillRect(r, p.c("bg"))

        bg: QColor | None = None
        if self._selected:
            soft = p.a("accent_soft")
            if self._hover:
                hi = p.c("surface_hi")
                bg = QColor(
                    round(soft.red() * 0.55 + hi.red() * 0.45),
                    round(soft.green() * 0.55 + hi.green() * 0.45),
                    round(soft.blue() * 0.55 + hi.blue() * 0.45),
                    min(255, soft.alpha() + 22),
                )
            else:
                bg = soft
        elif self.machine.status == STATUS_WAKING:
            bg = p.a("waking_soft")
            if self._hover:
                c = bg
                bg = QColor(c.red(), c.green(), c.blue(), min(255, c.alpha() + 14))
        elif self._hover:
            bg = p.a("hover")

        if bg is not None:
            painter.fillRect(r, bg)

        # 唤醒中扫光
        if self.machine.status == STATUS_WAKING:
            w = float(r.width())
            x0 = -w + self._sweep * 2.2 * w
            grad = QLinearGradient(QPointF(x0, 0), QPointF(x0 + w, 0))
            peak = QColor(255, 255, 255, 26 if p.is_dark() else 40)
            grad.setColorAt(0.0, QColor(255, 255, 255, 0))
            grad.setColorAt(0.5, peak)
            grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillRect(r, grad)

        painter.setPen(QPen(p.a("hairline"), 1))
        painter.drawLine(0, r.height() - 1, r.width(), r.height() - 1)


class StatusDot(QWidget):
    """8px 状态点：在线带光晕、唤醒中脉冲、离线降透明。"""

    def __init__(self, pal: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pal = pal
        self._status = STATUS_OFFLINE
        self._phase = 0.0
        self.setFixedSize(14, 14)
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def set_status(self, status: str) -> None:
        self._status = status
        if status == STATUS_WAKING:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self._phase = 0.0
        self.update()

    def set_palette(self, pal: Palette) -> None:
        self._pal = pal
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.028) % 1.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = self._pal
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        cx, cy, r = 7.0, 7.0, 4.0

        if self._status == STATUS_ONLINE:
            color = p.c("online")
            painter.setPen(Qt.NoPen)
            painter.setBrush(p.a("online_soft"))
            painter.drawEllipse(QPointF(cx, cy), 7.0, 7.0)
        elif self._status == STATUS_WAKING:
            color = p.c("waking")
            t = self._phase
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), int(70 * (1 - t))))
            painter.drawEllipse(QPointF(cx, cy), r + 3.4 * t, r + 3.4 * t)
        else:
            color = QColor(p.c("offline"))
            color.setAlpha(150)

        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(cx, cy), r, r)
