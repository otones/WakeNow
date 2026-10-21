"""主题令牌与 QSS。

所有取色值严格对齐 ui-design.html 的设计令牌，浅色 / 深色各一套。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from string import Template

from PySide6.QtGui import QColor, QFont

# ---------------------------------------------------------------- 原始令牌
_RAW = {
    "light": {
        "bg": "#FFFFFF",
        "bg_alt": "#F6F7F9",
        "surface_hi": "#EFF2F6",
        "surface_sunk": "#FAFBFC",
        "txt": "#111418",
        "txt2": "#5B6472",
        "txt3": "#98A1AF",
        "accent": "#0E7CE6",
        "accent2": "#00B4D8",
        "grad1": "#1478E8",
        "grad2": "#00B4D8",
        "online": "#0FA05C",
        "offline": "#96A0AE",
        "waking": "#C9820A",
        "danger": "#D93F3F",
        "row_dim": 0.45,
        "alpha": {
            "hairline": (16, 24, 40, 19),
            "border": (16, 24, 40, 28),
            "border_hi": (16, 24, 40, 51),
            "accent_soft": (14, 124, 230, 26),
            "online_soft": (15, 160, 92, 36),
            "waking_soft": (201, 130, 10, 26),
            "danger_soft": (217, 63, 63, 23),
            "hover": (16, 24, 40, 12),
        },
        "chrome_top": "#FDFDFE",
        "chrome_bottom": "#F8F9FB",
        "overlay": (12, 16, 22, 107),
    },
    "dark": {
        "bg": "#1B1F25",
        "bg_alt": "#191D22",
        "surface_hi": "#2C323B",
        "surface_sunk": "#20242A",
        "txt": "#E8ECF2",
        "txt2": "#9BA4B2",
        "txt3": "#6E7788",
        "accent": "#4A9DFF",
        "accent2": "#12CDBE",
        "grad1": "#2E8DFF",
        "grad2": "#12CDBE",
        "online": "#37D07E",
        "offline": "#69707E",
        "waking": "#F0B24A",
        "danger": "#FF6B6B",
        "row_dim": 0.42,
        "alpha": {
            "hairline": (255, 255, 255, 17),
            "border": (255, 255, 255, 26),
            "border_hi": (255, 255, 255, 48),
            "accent_soft": (74, 157, 255, 38),
            "online_soft": (55, 208, 126, 38),
            "waking_soft": (240, 178, 74, 28),
            "danger_soft": (255, 107, 107, 31),
            "hover": (255, 255, 255, 14),
        },
        "chrome_top": "#1F242B",
        "chrome_bottom": "#1B1F25",
        "overlay": (0, 0, 0, 140),
    },
}


def _blend(a: QColor, b: QColor, t: float) -> QColor:
    """a 向 b 混合 t（0~1），保留 a 的 alpha。"""
    t = max(0.0, min(1.0, t))
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        a.alpha(),
    )


@dataclass(frozen=True)
class Palette:
    name: str
    _d: dict
    _a: dict

    # --- 基础取色
    def c(self, key: str) -> QColor:
        return QColor(self._d[key])

    def h(self, key: str) -> str:
        return self._d[key]

    def a(self, key: str) -> QColor:
        r, g, b, al = self._a[key]
        return QColor(r, g, b, al)

    def rgba(self, key: str, alpha: int | None = None) -> str:
        r, g, b, al = self._a[key]
        al = al if alpha is None else alpha
        return f"rgba({r},{g},{b},{al})"

    def hex_alpha(self, key: str, alpha: int) -> str:
        """把调色板里的实色转成 #RRGGBBAA 字符串（供 QSS 用）。"""
        c = self.c(key)
        return f"#{c.red():02X}{c.green():02X}{c.blue():02X}{alpha:02X}"

    # --- 派生
    def blend_on_bg(self, key: str, amount: float) -> QColor:
        """把颜色按 amount 混向背景（模拟不透明度压暗）。"""
        return _blend(self.c(key), self.c("bg"), 1.0 - amount)

    def is_dark(self) -> bool:
        return self.name == "dark"


def palette(dark: bool) -> Palette:
    name = "dark" if dark else "light"
    raw = _RAW[name]
    return Palette(name=name, _d=raw, _a=raw["alpha"])


def resolve_dark(theme: str) -> bool:
    """把主题设置解析成「是否用深色」。

    theme: system | light | dark；system 跟随 Windows 设置。
    """
    if theme == "dark":
        return True
    if theme == "light":
        return False
    return system_prefers_dark()


def system_prefers_dark() -> bool:
    """读注册表判断系统深浅色，失败则按浅色。"""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        try:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(value) == 0
        finally:
            key.Close()
    except OSError:
        return False


def app_font() -> QFont:
    f = QFont()
    f.setFamilies(
        [
            "Segoe UI Variable Text",
            "Segoe UI",
            "Microsoft YaHei UI",
            "Microsoft YaHei",
            "system-ui",
        ]
    )
    f.setPixelSize(13)
    return f


# ---------------------------------------------------------------- QSS
_QSS = Template(
    """
    QWidget {
        color: $txt;
        font-size: 13px;
    }

    /* ---------- 搜索框 ---------- */
    QLineEdit#search {
        height: 30px;
        border: 1px solid $border;
        border-radius: 6px;
        background: $sunk;
        padding-left: 8px;
        padding-right: 8px;
        font-size: 12px;
        selection-background-color: $accent;
        selection-color: #FFFFFF;
    }
    QLineEdit#search:focus {
        border-color: $accent;
        background: $bg;
    }

    /* ---------- 幽灵按钮 ---------- */
    QPushButton#ghost {
        height: 30px;
        padding: 0 10px;
        border: 1px solid transparent;
        border-radius: 6px;
        background: transparent;
        color: $txt2;
        font-size: 12px;
    }
    QPushButton#ghost:hover {
        background: $surface_hi;
        color: $txt;
        border-color: $border;
    }
    QPushButton#ghost:pressed {
        background: $hover;
    }
    QPushButton#ghostDanger {
        height: 30px;
        padding: 0 10px;
        border: 1px solid transparent;
        border-radius: 6px;
        background: transparent;
        color: $txt2;
        font-size: 12px;
    }
    QPushButton#ghostDanger:hover {
        background: $danger_soft;
        color: $danger;
        border-color: $danger_border;
    }

    /* ---------- 滚动区 ---------- */
    QScrollArea { border: 0; background: transparent; }
    QScrollArea > QWidget > QWidget { background: transparent; }
    QScrollBar:vertical {
        width: 9px;
        background: transparent;
        margin: 0;
    }
    QScrollBar::handle:vertical {
        background: $scroll;
        border-radius: 9px;
        min-height: 24px;
        margin: 0 3px 0 3px;
    }
    QScrollBar::handle:vertical:hover { background: $scroll_hover; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

    /* ---------- 对话框输入 ---------- */
    QLineEdit#field {
        height: 32px;
        padding: 0 10px;
        border: 1px solid $border;
        border-radius: 6px;
        background: $sunk;
        color: $txt;
        font-size: 12px;
        selection-background-color: $accent;
        selection-color: #FFFFFF;
    }
    QLineEdit#field:focus {
        border-color: $accent;
        background: $bg;
    }
    QLineEdit#field[bad="true"] {
        border-color: $danger;
    }

    /* ---------- 下拉框 ---------- */
    QComboBox#field {
        height: 32px;
        padding: 0 10px;
        border: 1px solid $border;
        border-radius: 6px;
        background: $sunk;
        color: $txt;
        font-size: 12px;
    }
    QComboBox#field:hover {
        border-color: $border_hi;
    }
    QComboBox#field:focus {
        border-color: $accent;
        background: $bg;
    }
    QComboBox#field::drop-down {
        width: 26px;
        border: 0;
        background: transparent;
    }
    QComboBox#field QAbstractItemView {
        background: $bg;
        border: 1px solid $border;
        border-radius: 6px;
        padding: 4px;
        outline: 0;
        selection-background-color: $surface_hi;
        selection-color: $txt;
        color: $txt;
    }
    QComboBox#field QAbstractItemView::item {
        height: 28px;
        padding-left: 8px;
        border-radius: 4px;
    }

    /* ---------- 菜单 ---------- */
    QMenu {
        background: $bg;
        border: 1px solid $border;
        border-radius: 8px;
        padding: 5px;
    }
    QMenu::item {
        height: 30px;
        padding: 0 14px 0 10px;
        border-radius: 6px;
        color: $txt2;
        font-size: 12px;
    }
    QMenu::item:selected {
        background: $surface_hi;
        color: $txt;
    }
    QMenu::separator {
        height: 1px;
        background: $hairline;
        margin: 4px 6px;
    }

    QToolTip {
        background: $bg;
        color: $txt;
        border: 1px solid $border;
        padding: 4px 8px;
    }
    """
)


def build_qss(p: Palette) -> str:
    return _QSS.substitute(
        txt=p.h("txt"),
        txt2=p.h("txt2"),
        txt3=p.h("txt3"),
        bg=p.h("bg"),
        sunk=p.h("surface_sunk"),
        surface_hi=p.h("surface_hi"),
        border=p.rgba("border"),
        border_hi=p.rgba("border_hi"),
        hairline=p.rgba("hairline"),
        hover=p.rgba("hover"),
        accent=p.h("accent"),
        online=p.h("online"),
        danger=p.h("danger"),
        danger_soft=p.rgba("danger_soft"),
        danger_border=p.hex_alpha("danger", 77),
        scroll=p.rgba("border_hi"),
        scroll_hover=p.h("txt3"),
    )
