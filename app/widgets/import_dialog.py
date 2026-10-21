"""导入机器列表的策略选择对话框：合并 / 替换。"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..icons import icon
from ..theme import Palette, build_qss

MODE_MERGE = "merge"
MODE_REPLACE = "replace"


class RadioDot(QAbstractButton):
    """自绘单选钮：QSS 的 indicator 画不出真圆，这里直接画。"""

    def __init__(self, pal: Palette, text: str, parent=None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self._pal = pal
        self.setFixedHeight(26)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = self._pal
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # 圆
        d = 15.0
        top = (self.height() - d) / 2
        circle = QRectF(1.0, top, d, d)
        checked = self.isChecked()

        if checked:
            painter.setPen(Qt.NoPen)
            painter.setBrush(p.c("accent"))
            painter.drawEllipse(circle)
            # 内白点
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawEllipse(
                QPointF(circle.center().x(), circle.center().y()), 3.0, 3.0
            )
        else:
            painter.setPen(QPen(p.a("border_hi"), 1.5))
            painter.setBrush(p.c("bg"))
            painter.drawEllipse(circle)

        # 文字
        painter.setPen(QPen(p.c("txt")))
        font = painter.font()
        font.setPixelSize(12)
        painter.setFont(font)
        text_left = d + 10
        painter.drawText(
            QRectF(text_left, 0, self.width() - text_left, self.height()),
            int(Qt.AlignLeft | Qt.AlignVCenter),
            self.text(),
        )
        painter.end()

    def sizeHint(self):  # noqa: N802
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QFontMetrics

        fm = QFontMetrics(self.font())
        return QSize(25 + fm.horizontalAdvance(self.text()) + 8, 26)


class ImportDialog(QDialog):
    """展示导入概要与两种策略，返回选择结果。"""

    def __init__(
        self,
        pal: Palette,
        *,
        filename: str,
        added: int,
        existing: int,
        current_total: int,
        skipped: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._pal = pal
        self._added = added
        self._existing = existing
        self._current_total = current_total
        self._skipped = skipped
        self._filename = filename

        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedWidth(400)
        self.setStyleSheet(build_qss(pal))

        self._build()

    # ---------------------------------------------------------------- UI
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
        outer.addWidget(card)

        root = QVBoxLayout(card)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 头部
        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(16, 14, 12, 10)
        title = QLabel("导入机器列表")
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
        hl.addWidget(title)
        hl.addStretch(1)
        hl.addWidget(close)
        root.addWidget(head)

        # 概要
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 2, 16, 12)
        bl.setSpacing(8)

        file_lbl = QLabel(f"文件：{self._filename}")
        file_lbl.setStyleSheet(
            f"color:{p.h('txt2')};font-size:12px;background:transparent;"
        )
        file_lbl.setWordWrap(True)
        bl.addWidget(file_lbl)

        total_lbl = QLabel(f"共 {self._added + self._existing} 台机器")
        total_lbl.setStyleSheet(
            f"color:{p.h('txt')};font-size:13px;font-weight:500;background:transparent;"
        )
        bl.addWidget(total_lbl)

        if self._skipped:
            skip_lbl = QLabel(f"已跳过 {self._skipped} 条无效数据")
            skip_lbl.setStyleSheet(
                f"color:{p.h('danger')};font-size:11px;background:transparent;"
            )
            bl.addWidget(skip_lbl)

        bl.addSpacing(4)

        # 策略
        self.rb_merge = RadioDot(
            p, f"合并（推荐）　新增 {self._added} 台，已存在 {self._existing} 台"
        )
        self.rb_replace = RadioDot(
            p, f"替换　清空现有 {self._current_total} 台，只用文件内容"
        )

        self._group = QButtonGroup(self)
        self._group.addButton(self.rb_merge)
        self._group.addButton(self.rb_replace)
        self._group.setExclusive(True)

        bl.addWidget(self.rb_merge)
        bl.addWidget(self.rb_replace)

        self.rb_merge.setChecked(True)

        if self._added == 0:
            hint = QLabel("文件里的机器都已存在，合并不会产生变化。")
            hint.setStyleSheet(
                f"color:{p.h('txt3')};font-size:11px;background:transparent;"
            )
            hint.setWordWrap(True)
            bl.addWidget(hint)
            self.rb_replace.setChecked(True)

        root.addWidget(body)

        # 底部
        foot = QWidget()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(16, 12, 16, 16)
        fl.setSpacing(8)
        fl.addStretch(1)

        cancel = QPushButton("取消")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setFixedHeight(32)
        cancel.setStyleSheet(
            f"QPushButton{{padding:0 14px;border:1px solid {p.rgba('border')};"
            f"border-radius:6px;background:transparent;color:{p.h('txt2')};"
            f"font-size:12px;}}"
            f"QPushButton:hover{{background:{p.h('surface_hi')};color:{p.h('txt')};}}"
        )
        cancel.clicked.connect(self.reject)

        ok = QPushButton("导入")
        ok.setCursor(Qt.PointingHandCursor)
        ok.setFixedHeight(32)
        ok.setDefault(True)
        ok.setStyleSheet(
            "QPushButton{padding:0 18px;border:0;border-radius:6px;color:#fff;"
            "font-size:12px;font-weight:600;"
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 {p.h('grad1')},stop:1 {p.h('grad2')});}}"
        )
        ok.clicked.connect(self.accept)

        fl.addWidget(cancel)
        fl.addWidget(ok)
        root.addWidget(foot)

    # ---------------------------------------------------------------- 结果
    def mode(self) -> str:
        return MODE_MERGE if self.rb_merge.isChecked() else MODE_REPLACE
