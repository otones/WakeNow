"""自绘复选框：18px / 圆角 5 / 勾选回弹动画 / 支持混合态。"""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    Property,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton

from ..theme import Palette


class CheckBox(QAbstractButton):
    STATE_OFF = 0
    STATE_ON = 1
    STATE_MIXED = 2

    def __init__(self, pal: Palette, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(18, 18)
        self.setFocusPolicy(Qt.NoFocus)
        self._pal = pal
        self._state = self.STATE_OFF
        self._mark = 0.0          # 勾选绘制进度 0~1
        self._hover = False

        self._anim = QPropertyAnimation(self, b"mark", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutBack)

    # --- 动画属性
    def get_mark(self) -> float:
        return self._mark

    def set_mark(self, v: float) -> None:
        self._mark = v
        self.update()

    mark = Property(float, get_mark, set_mark)

    # --- 状态
    def set_state(self, state: int, animated: bool = True) -> None:
        if state == self._state:
            return
        self._state = state
        target = 1.0 if state == self.STATE_ON else 0.0
        if animated and state != self.STATE_MIXED:
            self._anim.stop()
            self._anim.setStartValue(self._mark)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self.set_mark(target)
        self.update()

    def state(self) -> int:
        return self._state

    def set_palette(self, pal: Palette) -> None:
        self._pal = pal
        self.update()

    # --- 交互
    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = self._pal
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = QRectF(1.25, 1.25, 15.5, 15.5)
        radius = 5.0

        checked = self._state in (self.STATE_ON, self.STATE_MIXED)
        accent = p.c("accent")
        if self._state == self.STATE_MIXED:
            fill = accent
        elif checked:
            fill = accent
        else:
            fill = p.c("bg")

        if self._hover and not checked:
            border = accent
        else:
            border = p.a("border_hi")

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, fill)

        if not checked:
            painter.setPen(QPen(border, 1.5))
            painter.drawPath(path)

        # 勾
        if self._state == self.STATE_ON and self._mark > 0.01:
            painter.setPen(
                QPen(QColor("#FFFFFF"), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            )
            painter.setRenderHint(QPainter.Antialiasing, True)
            # 以底部中点为中心做缩放回弹
            painter.translate(10, 10)
            painter.scale(self._mark, self._mark)
            painter.translate(-10, -10)
            painter.drawPolyline(
                [QPointF(5.2, 9.3), QPointF(8.6, 12.7), QPointF(14.6, 6.3)]
            )
        # 混合态横线
        elif self._state == self.STATE_MIXED:
            painter.setPen(QPen(QColor("#FFFFFF"), 2.0, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(5, 10, 13, 10)
