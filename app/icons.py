"""内嵌 SVG 图标，与设计稿图标集一致（24 网格 / 1.6 线宽）。

关于 DPI：pixmap 必须按「屏幕真实缩放比 × 请求尺寸」渲染，并把该比例写回
devicePixelRatio，Qt 才会把它当成逻辑尺寸 size 的图来画。若比例写死（比如 2.0）
而屏幕是 125%，Qt 会在 17.5px 的物理区域里画 28px 的像素图，图标就会被裁掉边缘。
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# 描边型图标
_PATHS = {
    "search": '<circle cx="11" cy="11" r="6.6"/><path d="m20 20-3.6-3.6"/>',
    "plus": '<path d="M12 5.4v13.2M5.4 12h13.2"/>',
    "pencil": '<path d="M4.5 19.5h4L19 9l-4-4L4.5 15.5z"/><path d="m14.2 5.8 4 4"/>',
    "trash": '<path d="M4.5 7h15M9.5 7V4.8h5V7M6.6 7l.9 12.2h9l.9-12.2"/>',
    "check": '<path d="M5 12.6 9.4 17 19 7.2"/>',
    "info": '<circle cx="12" cy="12" r="8.6"/><path d="M12 11.2v5.4M12 7.8v.6"/>',
    "alert": '<path d="M12 3.4 2.8 19.6h18.4z"/><path d="M12 10v4.4M12 17.2v.6"/>',
    "close": '<path d="m6.6 6.6 10.8 10.8M17.4 6.6 6.6 17.4"/>',
    "min": '<path d="M5.5 12h13"/>',
    "chev": '<path d="m8 10 4 4 4-4"/>',
    "arrow": '<path d="M12 5.5v13M6.5 11 12 5.5 17.5 11"/>',
    "power": '<path d="M12 3.6v8.2"/><path d="M7.4 6.9a7.2 7.2 0 1 0 9.2 0"/>',
    "refresh": '<path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20.2 4.2v4.4h-4.4"/>',
    "wifi": '<path d="M4 9.4a12 12 0 0 1 16 0M7 13a8 8 0 0 1 10 0"/><path d="M12 17.4v.4"/>',
    "more": '<circle cx="5.2" cy="12" r="1.1" fill="currentColor" stroke="none"/>'
            '<circle cx="12" cy="12" r="1.1" fill="currentColor" stroke="none"/>'
            '<circle cx="18.8" cy="12" r="1.1" fill="currentColor" stroke="none"/>',
    "import": '<path d="M12 3.6v10.8M7.6 10.2 12 14.6l4.4-4.4"/>'
              '<path d="M4.6 16.4v2.2a1.8 1.8 0 0 0 1.8 1.8h11.2a1.8 1.8 0 0 0 1.8-1.8v-2.2"/>',
    "export": '<path d="M12 14.4V3.6M7.6 8 12 3.6 16.4 8"/>'
              '<path d="M4.6 16.4v2.2a1.8 1.8 0 0 0 1.8 1.8h11.2a1.8 1.8 0 0 0 1.8-1.8v-2.2"/>',
    "power2": '<path d="M12 3.6v8.2"/><path d="M7.4 6.9a7.2 7.2 0 1 0 9.2 0"/>',
    "tray": '<path d="M3.6 13.4h4.2l1.4 2.4h5.6l1.4-2.4h4.2"/>'
            '<path d="M5.8 4.8h12.4l2.8 8.2v4.4a1.8 1.8 0 0 1-1.8 1.8H4.8a1.8 1.8 0 0 1-1.8-1.8v-4.4z"/>',
    "info2": '<circle cx="12" cy="12" r="8.6"/><path d="M12 11.2v5.4M12 7.8v.6"/>',
    "palette": '<path d="M12 3.4a8.6 8.6 0 0 0 0 17.2c1.1 0 1.8-.8 1.8-1.8 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.1 0-1 .8-1.8 1.8-1.8h1.5a3.5 3.5 0 0 0 3.5-3.5c0-4.3-3.4-7.8-7.6-7.8z"/>'
               '<circle cx="7.6" cy="11.4" r="1.1" fill="currentColor" stroke="none"/>'
               '<circle cx="10.4" cy="7.6" r="1.1" fill="currentColor" stroke="none"/>'
               '<circle cx="15" cy="8.2" r="1.1" fill="currentColor" stroke="none"/>',
    "sun": '<circle cx="12" cy="12" r="4.2"/>'
           '<path d="M12 2.6v2.2M12 19.2v2.2M4.4 4.4l1.6 1.6M18 18l1.6 1.6M2.6 12h2.2M19.2 12h2.2M4.4 19.6 6 18M18 6l1.6-1.6"/>',
    "moon": '<path d="M20.4 14.2A8.6 8.6 0 1 1 9.8 3.6a6.8 6.8 0 0 0 10.6 10.6z"/>',
}

# 实心图标
_FILLED = {
    "bolt": '<path d="M13.4 2.2 5.1 13.5h6L10.7 21.8 19 10.5h-6z"/>',
}


def screen_ratio() -> float:
    """当前主屏缩放比；拿不到时按 1.0。"""
    app = QGuiApplication.instance()
    if app is None:
        return 1.0
    screen = app.primaryScreen()
    if screen is None:
        return 1.0
    ratio = float(screen.devicePixelRatio())
    return ratio if ratio > 0 else 1.0


def _svg(name: str, color: str, stroke: float) -> bytes:
    if name in _FILLED:
        body = _FILLED[name]
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'fill="{color}">{body}</svg>'
        ).encode()
    body = _PATHS[name]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    ).encode()


def pixmap(
    name: str,
    size: int | float,
    color: QColor | str,
    stroke: float = 1.6,
    ratio: float | None = None,
) -> QPixmap:
    """渲染一个逻辑尺寸为 size、按屏幕缩放比采样的 pixmap。"""
    if isinstance(color, QColor):
        if color.alpha() < 255:
            col = (
                f"rgba({color.red()},{color.green()},{color.blue()},"
                f"{color.alpha() / 255:.3f})"
            )
        else:
            col = color.name()
    else:
        col = color

    dpr = ratio if ratio and ratio > 0 else screen_ratio()
    renderer = QSvgRenderer(QByteArray(_svg(name, col, stroke)))

    px = QPixmap(max(1, round(size * dpr)), max(1, round(size * dpr)))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    return px


def app_icon() -> QIcon:
    """应用图标：优先用随程序分发的 ICO（多尺寸、带渐变底），保证任务栏清晰。

    注意不要优先用 sys.executable：PyInstaller 把 --icon 写进 exe 资源的是
    单尺寸压缩图，Windows 任务栏取小尺寸时会被缩得发虚甚至变小。
    所以优先加载 assets/wakenow.ico 里的全部尺寸。
    """
    import os
    import sys

    from .paths import app_dir

    result = QIcon()
    candidates = [os.path.join(app_dir(), "assets", "wakenow.ico")]
    if getattr(sys, "frozen", False):
        # 打包后资源解压在 _MEIPASS 下
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.insert(
                0, os.path.join(meipass, "assets", "wakenow.ico")
            )

    for path in candidates:
        if path and os.path.exists(path):
            loaded = QIcon(path)
            if loaded.isNull():
                continue
            for size in loaded.availableSizes():
                result.addPixmap(loaded.pixmap(size))
            if not result.isNull():
                return result

    # 兜底：自己画
    for s in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        result.addPixmap(pixmap("bolt", s, "#FFFFFF", ratio=1.0))
    return result


def icon(
    name: str,
    size: int,
    color: QColor | str,
    stroke: float = 1.6,
    ratio: float | None = None,
) -> QIcon:
    """构造 QIcon。

    同一图标按多档缩放比各备一张，交给 Qt 按目标设备挑选；
    这样在 100% / 125% / 150% / 200% 下都不会被拉伸或裁切。
    """
    base = ratio or screen_ratio()
    ratios = sorted({1.0, 1.25, 1.5, 2.0, 3.0, base})
    result = QIcon()
    for r in ratios:
        result.addPixmap(pixmap(name, size, color, stroke, ratio=r))
    return result

