"""机器添加 / 编辑对话框。380 宽，字段校验与设计稿一致。"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..icons import icon, pixmap
from ..models import (
    PROBE_AUTO,
    PROBE_CHOICES,
    PROBE_LABEL,
    PROBE_PING,
    Machine,
    is_mac,
    normalize_mac,
    validate_field,
)
from ..theme import Palette, build_qss

FIELDS = [
    ("name", "名称", "例如：书房主机", True, False),
    ("mac", "MAC", "AA:BB:CC:DD:EE:FF", True, True),
    ("ip", "IP", "留空则自动发现（推荐）", False, True),
    ("broadcast", "广播地址", "留空则按 IP 自动推算", False, True),
    ("port", "端口", "9", False, True),
    ("probe_port", "探测端口", "445", False, True),
]


class ProbeCombo(QComboBox):
    """带自绘箭头的下拉框。

    QSS 的 ::down-arrow 在 Qt 里不认 CSS 三角写法（会变成小方块），
    这里直接画一个 chevron，任何主题与 DPI 下都稳定。
    """

    def __init__(self, pal: Palette, parent=None) -> None:
        super().__init__(parent)
        self._pal = pal
        self.setObjectName("field")
        self.setFixedHeight(32)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(self._pal.c("txt3"), 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        cx = self.width() - 16
        cy = self.height() / 2
        painter.drawLine(QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2))
        painter.drawLine(QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2))
        painter.end()


class FieldRow(QWidget):
    def __init__(
        self,
        key: str,
        label: str,
        placeholder: str,
        required: bool,
        pal: Palette,
        mono: bool,
        label_width: int = 64,
    ):
        super().__init__()
        self.key = key
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        text = label + ('<span style="color:%s"> *</span>' % pal.h("danger") if required else "")
        lab = QLabel(text)
        lab.setTextFormat(Qt.RichText)
        lab.setFixedWidth(label_width)
        # 左对齐：所有标签从同一竖线起始，中文标签字数不同时左边缘也整齐
        lab.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        lab.setStyleSheet(f"color:{pal.h('txt2')};font-size:12px;background:transparent;")
        self.label = lab

        self.edit = QLineEdit()
        self.edit.setObjectName("field")
        self.edit.setPlaceholderText(placeholder)
        self.edit.setProperty("bad", "false")
        if not mono:
            self.edit.setStyleSheet(
                self.edit.styleSheet() + "font-family:'Segoe UI','Microsoft YaHei UI',sans-serif;"
            )

        # 垂直居中对齐到输入框，而不是贴行顶（贴顶会让标签高于框）
        lay.addWidget(lab, 0, Qt.AlignVCenter)
        lay.addWidget(self.edit, 1)


class MachineDialog(QDialog):
    """返回 (name, ip, mac, broadcast, port)。"""

    def __init__(self, pal: Palette, machine: Machine | None = None, parent=None):
        super().__init__(parent)
        self._pal = pal
        self._machine = machine
        self._mode = "edit" if machine else "add"

        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedWidth(380)

        # 对话框是独立顶层窗口，不继承父窗口样式表，必须自己挂一份
        self.setStyleSheet(build_qss(pal))

        self._build()
        if machine:
            self._fill(machine)

    # ---------------------------------------------------------------- UI
    def _measure_label_width(self, pal: Palette) -> int:
        """按最长标签（含必填星号）实测像素宽度，作为统一列宽。"""
        from PySide6.QtGui import QFont, QFontMetrics

        f = QFont(self.font())
        f.setPixelSize(12)          # 标签字号，与 FieldRow 的 QSS 一致
        fm = QFontMetrics(f)
        widest = 0
        for _key, label, _ph, req, _mono in FIELDS:
            text = label + (" *" if req else "")
            widest = max(widest, fm.horizontalAdvance(text))
        return max(56, widest + 6)

    def _build(self) -> None:
        p = self._pal
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QWidget()
        card.setObjectName("card")
        card.setStyleSheet(
            f"#card{{background:{p.h('bg')};border:1px solid {p.rgba('border')};"
            f"border-radius:8px;}}"
        )
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(44)
        shadow.setOffset(0, 14)
        shadow.setColor(Qt.black if p.is_dark() else p.c("txt"))
        if p.is_dark():
            shadow.setColor(Qt.black)
        else:
            c = p.c("txt")
            c.setAlpha(90)
            shadow.setColor(c)
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)

        root = QVBoxLayout(card)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 头部
        head = QWidget()
        head_lay = QHBoxLayout(head)
        head_lay.setContentsMargins(16, 14, 12, 10)
        title = QLabel("编辑机器" if self._mode == "edit" else "添加机器")
        title.setStyleSheet(
            f"color:{p.h('txt')};font-size:14px;font-weight:600;background:transparent;"
        )
        close = QPushButton()
        close.setFixedSize(26, 26)
        close.setCursor(Qt.PointingHandCursor)
        close.setIcon(icon("close", 13, p.c("txt3"), 1.7))
        close.setStyleSheet(
            "QPushButton{background:transparent;border:0;border-radius:6px;}"
            f"QPushButton:hover{{background:{p.h('surface_hi')};}}"
        )
        close.clicked.connect(self.reject)
        head_lay.addWidget(title)
        head_lay.addStretch(1)
        head_lay.addWidget(close)
        root.addWidget(head)

        # 表单
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(16, 2, 16, 4)
        body_lay.setSpacing(9)

        self.fields: dict[str, FieldRow] = {}
        self.errors: dict[str, QLabel] = {}

        # 标签列宽按最长标签实测，避免各行左边缘参差
        label_w = self._measure_label_width(p)
        self._label_width = label_w

        for key, label, ph, req, mono in FIELDS:
            wrap = QWidget()
            wl = QVBoxLayout(wrap)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.setSpacing(3)

            row = FieldRow(key, label, ph, req, p, mono, label_width=label_w)
            err = QLabel("")
            err.setStyleSheet(
                f"color:{p.h('danger')};font-size:10px;background:transparent;"
            )
            # 错误文字与输入框左边缘对齐：标签宽 + 间距
            err.setContentsMargins(label_w + 10, 0, 0, 0)
            err.hide()

            row.edit.textChanged.connect(lambda _t, k=key: self._on_changed(k))
            row.edit.returnPressed.connect(self._save)

            wl.addWidget(row)
            wl.addWidget(err)
            body_lay.addWidget(wrap)
            self.fields[key] = row
            self.errors[key] = err

            # 「探测端口」后面紧跟「探测方式」下拉框
            if key == "port":
                body_lay.addWidget(self._make_probe_row(label_w, p))
            if key == "probe_port":
                # 探测端口依赖探测方式：仅 ping 时置灰
                self._probe_port_row = row

        root.addWidget(body)

        # 底部
        foot = QWidget()
        foot_lay = QHBoxLayout(foot)
        foot_lay.setContentsMargins(16, 14, 16, 16)
        foot_lay.setSpacing(8)
        foot_lay.addStretch(1)

        cancel = QPushButton("取消")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setFixedHeight(32)
        cancel.setStyleSheet(
            f"QPushButton{{padding:0 14px;border:1px solid {p.rgba('border')};border-radius:6px;"
            f"background:transparent;color:{p.h('txt2')};font-size:12px;}}"
            f"QPushButton:hover{{background:{p.h('surface_hi')};color:{p.h('txt')};}}"
        )
        cancel.clicked.connect(self.reject)

        save = QPushButton("保存")
        save.setCursor(Qt.PointingHandCursor)
        save.setFixedHeight(32)
        save.setDefault(True)
        save.setStyleSheet(
            f"QPushButton{{padding:0 18px;border:0;border-radius:6px;color:#fff;font-size:12px;"
            f"font-weight:600;background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 {p.h('grad1')},stop:1 {p.h('grad2')});}}"
            "QPushButton:hover{padding:0 18px;}"
        )
        save.clicked.connect(self._save)

        foot_lay.addWidget(cancel)
        foot_lay.addWidget(save)
        root.addWidget(foot)

        self._first_edit = self.fields[FIELDS[0][0]].edit

    # ---------------------------------------------------------------- 探测方式
    def _make_probe_row(self, label_width: int, p: Palette) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        lab = QLabel("探测方式")
        lab.setFixedWidth(label_width)
        lab.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        lab.setStyleSheet(
            f"color:{p.h('txt2')};font-size:12px;background:transparent;"
        )

        self.probe_combo = ProbeCombo(p)
        for key in PROBE_CHOICES:
            self.probe_combo.addItem(PROBE_LABEL[key], key)
        self.probe_combo.currentIndexChanged.connect(self._on_probe_mode_changed)

        lay.addWidget(lab, 0, Qt.AlignVCenter)
        lay.addWidget(self.probe_combo, 1)
        return wrap

    def _on_probe_mode_changed(self) -> None:
        """仅 ping 时探测端口无意义，置灰。"""
        mode = self.probe_combo.currentData()
        enabled = mode != PROBE_PING
        row = getattr(self, "_probe_port_row", None)
        if row is not None:
            row.edit.setEnabled(enabled)
            row.label.setEnabled(enabled)

    # ---------------------------------------------------------------- 数据
    def _fill(self, m: Machine) -> None:
        self.fields["name"].edit.setText(m.name)
        self.fields["ip"].edit.setText(m.ip)
        self.fields["mac"].edit.setText(m.display_mac)
        self.fields["broadcast"].edit.setText(m.broadcast)
        self.fields["port"].edit.setText(str(m.port))
        self.fields["probe_port"].edit.setText(
            str(m.probe_port) if m.probe_port else ""
        )
        idx = self.probe_combo.findData(m.probe)
        if idx >= 0:
            self.probe_combo.setCurrentIndex(idx)
        self._on_probe_mode_changed()

    def _on_changed(self, key: str) -> None:
        # MAC 自动格式化：去掉非法字符、大写、每两位补冒号
        if key == "mac":
            edit = self.fields["mac"].edit
            raw = "".join(ch for ch in edit.text() if ch in "0123456789abcdefABCDEF")[:12].upper()
            formatted = ":".join(raw[i:i + 2] for i in range(0, len(raw), 2))
            if edit.text() != formatted:
                edit.blockSignals(True)
                edit.setText(formatted)
                edit.setCursorPosition(len(formatted))
                edit.blockSignals(False)
        if self.errors[key].isVisible():
            self._validate_field(key)

    def _validate_field(self, key: str) -> bool:
        value = self.fields[key].edit.text()
        msg = validate_field(key, value)
        err = self.errors[key]
        if msg:
            err.setText(msg)
            err.show()
            self.fields[key].edit.setProperty("bad", "true")
            self._repolish(self.fields[key].edit)
            return False
        err.hide()
        self.fields[key].edit.setProperty("bad", "false")
        self._repolish(self.fields[key].edit)
        return True

    @staticmethod
    def _repolish(widget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _save(self) -> None:
        ok = True
        first_bad = None
        for key in self.fields:
            valid = self._validate_field(key)
            if not valid:
                ok = False
                if first_bad is None:
                    first_bad = self.fields[key].edit
        if not ok:
            if first_bad is not None:
                first_bad.setFocus()
            self._shake()
            return
        self.accept()

    def _shake(self) -> None:
        from PySide6.QtCore import QPoint, QPropertyAnimation

        start = self.pos()
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(220)
        anim.setStartValue(start)
        for i, dx in enumerate([-7, 6, -4, 3, 0]):
            anim.setKeyValueAt((i + 1) / 5.0, start + QPoint(dx, 0))
        anim.start()
        self._shake_anim = anim

    def result_data(self) -> dict:
        port_text = self.fields["port"].edit.text().strip()
        probe_port_text = self.fields["probe_port"].edit.text().strip()
        probe_port = int(probe_port_text) if probe_port_text.isdigit() else 0
        if not (0 < probe_port < 65536):
            probe_port = 0
        return {
            "name": self.fields["name"].edit.text().strip(),
            "ip": self.fields["ip"].edit.text().strip(),
            "mac": normalize_mac(self.fields["mac"].edit.text()),
            "broadcast": self.fields["broadcast"].edit.text().strip(),
            "port": int(port_text) if port_text.isdigit() else 9,
            "probe": self.probe_combo.currentData() or PROBE_AUTO,
            "probe_port": probe_port,
        }
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # 居中于父窗口
        parent = self.parentWidget()
        if parent is not None:
            geo = parent.geometry()
            self.move(
                geo.center().x() - self.width() // 2,
                geo.center().y() - self.height() // 2,
            )
        self._first_edit.setFocus()
        self._first_edit.selectAll()
