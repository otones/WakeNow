"""生成应用图标 assets/wakenow.ico（多尺寸）。

用法：python tools/make_icon.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)

    # 圆角渐变底
    radius = size * 0.22
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, QColor("#1478E8"))
    grad.setColorAt(1.0, QColor("#00B4D8"))
    p.fillPath(path, grad)

    # 闪电
    s = size
    bolt = QPainterPath()
    pts = [
        (0.58, 0.14), (0.30, 0.55), (0.48, 0.55),
        (0.42, 0.86), (0.70, 0.44), (0.52, 0.44),
    ]
    bolt.moveTo(pts[0][0] * s, pts[0][1] * s)
    for x, y in pts[1:]:
        bolt.lineTo(x * s, y * s)
    bolt.closeSubpath()
    p.fillPath(bolt, QColor("#FFFFFF"))
    p.end()
    return img


def main() -> int:
    app = QApplication.instance() or QApplication([])
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    os.makedirs(out_dir, exist_ok=True)

    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [render(s) for s in sizes]

    # 以最大的作为主图，Qt 会按需缩放；再手工拼多尺寸 ICO 更稳妥
    ico_path = os.path.join(out_dir, "wakenow.ico")
    _write_ico(images, sizes, ico_path)
    print("wrote", ico_path, os.path.getsize(ico_path), "bytes")

    # 顺手存一张 PNG 供文档/README 用
    images[-1].save(os.path.join(out_dir, "wakenow.png"))
    return 0


def _write_ico(images: list[QImage], sizes: list[int], path: str) -> None:
    """手写 ICO：多尺寸 PNG 压缩条目。"""
    import struct

    entries = []
    for img in images:
        from PySide6.QtCore import QBuffer, QByteArray

        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QBuffer.WriteOnly)
        img.save(buf, "PNG")
        buf.close()
        entries.append(bytes(ba))

    count = len(entries)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    dirs = b""
    for size, data in zip(sizes, entries):
        w = 0 if size >= 256 else size
        h = 0 if size >= 256 else size
        dirs += struct.pack(
            "<BBBBHHII", w, h, 0, 0, 1, 32, len(data), offset
        )
        offset += len(data)

    with open(path, "wb") as f:
        f.write(header + dirs + b"".join(entries))


if __name__ == "__main__":
    sys.exit(main())
