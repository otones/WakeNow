"""Toast 轻提示：窗口内底部居中、向上堆叠、自动消失。"""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QTimer,
    Qt,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget

from ..icons import pixmap
from ..theme import Palette

KIND_COLORS = {
    "success": "online",
    "info": "accent",
    "error": "danger",
}
KIND_ICON = {"success": "check", "info": "info", "error": "alert"}


class Toast(QWidget):
    def __init__(self, kind: str, text: str, pal: Palette, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_StyledBackground, True)

        color = pal.c(KIND_COLORS[kind])
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 13, 8)
        lay.setSpacing(9)

        badge = QLabel()
        badge.setFixedSize(18, 18)
        badge.setPixmap(pixmap(KIND_ICON[kind], 11, "#FFFFFF", 2.6))
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            f"background:{color.name()};border-radius:9px;"
        )

        label = QLabel(text)
        label.setStyleSheet(f"color:{pal.h('txt')};font-size:12px;background:transparent;")

        lay.addWidget(badge, 0, Qt.AlignVCenter)
        lay.addWidget(label, 0, Qt.AlignVCenter)

        border = pal.rgba("border")
        if kind == "success":
            border = color.name() + "42"
        elif kind == "error":
            border = color.name() + "4D"
        self.setStyleSheet(
            f"background:{pal.h('bg')};border:1px solid {border};border-radius:8px;"
        )

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)

        self.adjustSize()


class ToastHost(QWidget):
    """Toast 层：跟随窗口尺寸变化，负责堆叠与生命周期。"""

    MAX_VISIBLE = 3

    def __init__(self, parent: QWidget, pal: Palette) -> None:
        super().__init__(parent)
        self._pal = pal
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._toasts: list[Toast] = []

    def set_palette(self, pal: Palette) -> None:
        self._pal = pal

    def show_toast(self, kind: str, text: str, duration_ms: int = 2600) -> None:
        toast = Toast(kind, text, self._pal, self)
        toast.adjustSize()
        self._toasts.append(toast)

        # 超出上限，最早的一条立即退场
        while len(self._toasts) > self.MAX_VISIBLE:
            self._dismiss(self._toasts[0], animated=False)

        toast.show()
        toast.raise_()
        self._relayout()

        eff = toast.graphicsEffect()
        assert isinstance(eff, QGraphicsOpacityEffect)
        anim = QPropertyAnimation(eff, b"opacity", toast)
        anim.setDuration(220)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        toast._anim = anim  # 防 GC

        QTimer.singleShot(duration_ms, lambda t=toast: self._dismiss(t, animated=True))

    def _dismiss(self, toast: Toast, animated: bool) -> None:
        if toast not in self._toasts:
            return
        self._toasts.remove(toast)
        if not animated:
            toast.hide()
            toast.deleteLater()
            self._relayout()
            return
        eff = toast.graphicsEffect()
        assert isinstance(eff, QGraphicsOpacityEffect)
        anim = QPropertyAnimation(eff, b"opacity", toast)
        anim.setDuration(220)
        anim.setStartValue(eff.opacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InCubic)
        anim.finished.connect(lambda t=toast: (t.hide(), t.deleteLater()))
        anim.start()
        toast._anim = anim
        self._relayout()

    def _relayout(self) -> None:
        """底部居中 + 向上堆叠，距底 60px。"""
        bottom = 60
        for toast in reversed(self._toasts):
            toast.adjustSize()
            w = toast.sizeHint().width()
            h = toast.sizeHint().height()
            toast.resize(w, h)
            x = (self.width() - w) // 2
            y = self.height() - bottom - h
            toast.move(max(0, x), max(0, y))
            bottom += h + 8

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()
