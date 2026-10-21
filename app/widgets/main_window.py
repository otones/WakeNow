"""主窗口：无边框外壳 + 工具条 + 列表 + 底栏 + Toast 层。"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import (
    QPoint,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..icons import icon, pixmap
from ..models import (
    STATUS_LABEL,
    STATUS_OFFLINE,
    STATUS_ONLINE,
    STATUS_UNKNOWN,
    STATUS_WAKING,
    Machine,
)
from ..theme import Palette, build_qss
from .checkbox import CheckBox
from .dialogs import MachineDialog
from .machine_row import COL_STATUS, MONO, MachineRow, StatusDot
from .toast import ToastHost

WIN_W, WIN_H = 560, 420
CHROME_H = 40
TOOLBAR_H = 44
THEAD_H = 30
FOOTER_H = 52

# 最小宽度按底栏实测需求定：6 个按钮(577) + 间距(24) + 边距(28) = 629，
# 取 640 留余量，否则左右拖窄时底部按钮文字会被截断
MIN_W, MIN_H = 640, 340

RESIZE_MARGIN = 6   # 边缘拉伸判定宽度（无边框窗口需要自己实现）

WAKE_TIMEOUT_S = 180  # 唤醒中超过 3 分钟回退为离线


class EmptyState(QWidget):
    def __init__(self, pal: Palette, parent=None):
        super().__init__(parent)
        self._pal = pal
        self._float = 0.0
        self._dir = 1.0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.setSpacing(4)
        lay.setAlignment(Qt.AlignCenter)

        art = _EmptyArt(pal, self)
        art.setFixedSize(186, 132)
        lay.addWidget(art, 0, Qt.AlignHCenter)

        self.title = QLabel("还没有录入机器")
        self.title.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.title)

        self.sub = QLabel("添加一台机器，随时随地一键唤醒")
        self.sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.sub)

        self.btn = QPushButton("  添加机器")
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setFixedHeight(36)
        self.btn.setIcon(icon("bolt", 14, "#FFFFFF"))
        lay.addSpacing(12)
        lay.addWidget(self.btn, 0, Qt.AlignHCenter)
        self.apply_style()

    def apply_style(self) -> None:
        p = self._pal
        self.title.setStyleSheet(
            f"color:{p.h('txt')};font-size:14px;font-weight:600;background:transparent;"
        )
        self.sub.setStyleSheet(
            f"color:{p.h('txt3')};font-size:12px;background:transparent;"
        )
        self.btn.setStyleSheet(
            f"QPushButton{{padding:0 18px;border:0;border-radius:7px;color:#fff;"
            f"font-size:13px;font-weight:600;"
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 {p.h('grad1')},stop:1 {p.h('grad2')});}}"
        )

    def set_palette(self, pal: Palette) -> None:
        self._pal = pal
        self.apply_style()
        self.update()


class _EmptyArt(QWidget):
    """睡觉的显示器 + 月亮 + Zzz。"""

    def __init__(self, pal: Palette, parent=None):
        super().__init__(parent)
        self._pal = pal
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event):  # noqa: N802
        super().hideEvent(event)
        self._timer.stop()

    def _tick(self):
        self._phase = (self._phase + 0.016) % 1.0
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = self._pal
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        base = p.c("txt3")
        line = QColor(base.red(), base.green(), base.blue(), 46)
        fill_soft = QColor(base.red(), base.green(), base.blue(), 14)
        moon = QColor(base.red(), base.green(), base.blue(), 96)

        # 地面阴影
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(base.red(), base.green(), base.blue(), 18))
        painter.drawEllipse(QRectF(35, 108, 116, 15))

        # 显示器外框
        painter.setPen(QPen(line, 1.6))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(26, 30, 106, 68), 8, 8)

        # 屏幕内浅底
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill_soft)
        painter.drawRoundedRect(QRectF(34.5, 38.5, 89, 51), 5.5, 5.5)

        # 月牙：大圆挖掉偏移圆（用奇偶填充）
        painter.setBrush(moon)
        path = QPainterPath()
        path.addEllipse(QPointF(80, 64), 15, 15)
        cut = QPainterPath()
        cut.addEllipse(QPointF(91.5, 53.5), 15, 15)
        painter.drawPath(path.subtracted(cut))

        # 支架 + 底座
        painter.setPen(QPen(line, 1.6))
        painter.drawLine(79, 98, 79, 112)
        painter.drawLine(63, 116, 95, 116)

        # 屏幕角落小点
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(base.red(), base.green(), base.blue(), 60))
        painter.drawEllipse(QPointF(44, 50), 1.6, 1.6)

        # Zzz 飘动
        for x, y, size, delay in [
            (140, 62, 11, 0.0),
            (149, 46, 14, 0.35),
            (159, 28, 17, 0.7),
        ]:
            t = (self._phase + delay) % 1.0
            alpha = int(120 * max(0.0, 1.0 - abs(t - 0.25) * 3.2))
            if alpha <= 0:
                continue
            painter.setPen(QColor(base.red(), base.green(), base.blue(), alpha))
            font = painter.font()
            font.setPixelSize(size)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(QPointF(x, y - t * 8), "Z")


class Sorter:
    def __init__(self, key: str = "name", ascending: bool = True) -> None:
        self.key = key
        self.ascending = ascending

    def apply(self, machines: list[Machine]) -> list[Machine]:
        if not self.key:
            return list(machines)
        import locale

        def k(m: Machine):
            if self.key == "ip":
                try:
                    return tuple(int(x) for x in m.ip.split("."))
                except ValueError:
                    return (999, 999, 999, 999)
            return m.name

        return sorted(machines, key=k, reverse=not self.ascending)


class MainWindow(QWidget):
    hide_to_tray = Signal()

    # 边缘位标志
    EDGE_TOP = 1
    EDGE_BOTTOM = 2
    EDGE_LEFT = 4
    EDGE_RIGHT = 8

    def __init__(self, machines: list[Machine], store, pal: Palette) -> None:
        super().__init__()
        self._pal = pal
        self._machines = machines
        self._store = store
        self._selected: set[str] = set()
        self._rows: dict[str, MachineRow] = {}
        self._query = ""
        self._sorter = Sorter()
        self._wake_deadline: dict[str, float] = {}

        # 由 main.py 注入的外部能力（未注入时功能自动降级）
        self._minimize_to_tray: bool = True
        self._tray_available: bool = False
        self._autostart_getter = None
        self._autostart_setter = None
        self._settings_saver = None
        self._theme: str = "system"        # system | light | dark
        self._theme_changed = None         # 外部回调，用于持久化

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("WakeNow")
        self.resize(WIN_W, WIN_H)
        self.setMinimumSize(MIN_W, MIN_H)
        self.setMouseTracking(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._build_chrome(root)
        self._build_toolbar(root)
        self._build_table(root)
        self._build_footer(root)

        self.toast_host = ToastHost(self, pal)
        self.toast_host.setGeometry(self.rect())
        self.toast_host.raise_()

        self._rescan_timer = QTimer(self)
        self._rescan_timer.setInterval(1000)
        self._rescan_timer.timeout.connect(self._check_wake_timeouts)
        self._rescan_timer.start()

        # 定期重新发现 IP（DHCP 续约后地址会变）
        self._discover_timer = QTimer(self)
        self._discover_timer.setInterval(60_000)
        self._discover_timer.timeout.connect(lambda: self.request_discover())
        self._discover_timer.start()

        self.apply_palette(pal)
        self.rebuild_rows()
        self._update_stats()

    # ================================================================ 构建
    def _build_chrome(self, root: QVBoxLayout) -> None:
        bar = QWidget(self)
        bar.setObjectName("chrome")
        bar.setFixedHeight(CHROME_H)
        bar.setAttribute(Qt.WA_StyledBackground, True)

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 0, 0)
        lay.setSpacing(8)

        mark = QLabel(bar)
        mark.setFixedSize(22, 22)
        mark.setStyleSheet(
            f"border-radius:6px;background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 {self._pal.h('grad1')},stop:1 {self._pal.h('grad2')});"
        )
        self._mark_lbl = mark

        brand = QLabel("Wake<b>Now</b>", bar)
        brand.setObjectName("brand")
        brand.setTextFormat(Qt.RichText)

        lay.addWidget(mark, 0, Qt.AlignVCenter)
        lay.addWidget(brand, 0, Qt.AlignVCenter)
        lay.addStretch(1)

        self._btn_min = QPushButton(bar)
        self._btn_more = QPushButton(bar)
        self._btn_close = QPushButton(bar)

        # 「⋯」更多菜单：导入导出、开机自启、最小化到托盘
        self._btn_more.setFixedSize(38, CHROME_H)
        self._btn_more.setCursor(Qt.PointingHandCursor)
        self._btn_more.setToolTip("更多")
        self._btn_more.setIcon(icon("more", 16, self._pal.c("txt2"), 2.0))
        self._btn_more.setProperty("role", "chrome")
        self._btn_more.clicked.connect(self._show_more_menu)
        lay.addWidget(self._btn_more)

        for b, name, tip, size in (
            (self._btn_min, "min", "最小化", (14, 1.5)),
            (self._btn_close, "close", "关闭", (13, 1.5)),
        ):
            b.setFixedSize(44, CHROME_H)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tip)
            b.setIcon(icon(name, size[0], self._pal.c("txt2"), size[1]))
            b.setProperty("role", "chrome")
            lay.addWidget(b)
        self._btn_min.clicked.connect(self.showMinimized)
        self._btn_close.clicked.connect(self._on_close_clicked)

        self._chrome = bar
        self._chrome_lay = lay
        root.addWidget(bar)

    def _build_toolbar(self, root: QVBoxLayout) -> None:
        bar = QWidget(self)
        bar.setFixedHeight(TOOLBAR_H)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(12)

        self.search = QLineEdit(bar)
        self.search.setObjectName("search")
        self.search.setPlaceholderText("搜索机器…")
        self.search.setFixedHeight(30)
        self.search.textChanged.connect(self._on_search)

        # 放大镜用 QLineEdit 自带的 action 放左侧：由 Qt 负责垂直居中，
        # 不依赖手算坐标，任何 DPI 下都与文字基线对齐
        self._search_action = self.search.addAction(
            QIcon(pixmap("search", 15, self._pal.c("txt3"), 1.7)),
            QLineEdit.LeadingPosition,
        )
        self._search_action.setEnabled(False)   # 纯装饰，不可点击

        self.stats = QLabel("", bar)
        self.stats.setTextFormat(Qt.RichText)
        self.stats.setStyleSheet("background:transparent;")

        lay.addWidget(self.search, 1)
        lay.addWidget(self.stats, 0, Qt.AlignVCenter)

        self._toolbar = bar
        root.addWidget(bar)

    def _build_table(self, root: QVBoxLayout) -> None:
        head = QWidget(self)
        head.setFixedHeight(THEAD_H)
        head.setAttribute(Qt.WA_StyledBackground, True)
        head.setObjectName("thead")
        lay = QHBoxLayout(head)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(0)

        self.cb_all = CheckBox(self._pal, head)
        cb_wrap = QWidget(head)
        cb_wrap.setFixedWidth(46)
        cbl = QHBoxLayout(cb_wrap)
        cbl.setContentsMargins(0, 0, 0, 0)
        cbl.addWidget(self.cb_all, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.cb_all.clicked.connect(self._on_toggle_all)

        self._sort_name = self._make_sort_label("名称", "name", head)
        name_wrap = QWidget(head)
        nl = QHBoxLayout(name_wrap)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.addWidget(self._sort_name)
        nl.addStretch(1)

        self._sort_ip = self._make_sort_label("IP", "ip", head)
        self._sort_ip.setFixedWidth(132 - 8)

        st_label = QLabel("状态", head)
        st_label.setStyleSheet("background:transparent;")
        st_label.setFixedWidth(COL_STATUS)
        self._status_head = st_label

        lay.addWidget(cb_wrap, 0)
        lay.addWidget(name_wrap, 1)
        lay.addSpacing(8)
        lay.addWidget(self._sort_ip, 0)
        lay.addWidget(st_label, 0)

        root.addWidget(head)
        self._thead = head

        # 列表滚动区
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QScrollArea.NoFrame)

        self._list_host = QWidget()
        # 拉伸窗口后列表下方的空白必须与窗口同色，否则会露出一块异色
        self._list_host.setAutoFillBackground(True)
        self._list_lay = QVBoxLayout(self._list_host)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(0)
        self._list_lay.addStretch(1)
        self.scroll.setWidget(self._list_host)

        # 空状态 & 无搜索结果
        self.empty = EmptyState(self._pal, self)
        self.empty.btn.clicked.connect(self._on_add)

        self.no_result = QLabel("没有匹配的机器", self)
        self.no_result.setAlignment(Qt.AlignCenter)
        self.no_result.hide()

        root.addWidget(self.scroll, 1)
        root.addWidget(self.empty, 1)
        root.addWidget(self.no_result, 1)

    def _make_sort_label(self, text: str, key: str, parent: QWidget) -> QLabel:
        lab = QLabel(text, parent)
        lab.setCursor(Qt.PointingHandCursor)
        lab.setStyleSheet("background:transparent;")
        lab.mousePressEvent = lambda e, k=key: self._on_sort(k)  # type: ignore[method-assign]
        return lab

    def _build_footer(self, root: QVBoxLayout) -> None:
        bar = QWidget(self)
        bar.setFixedHeight(FOOTER_H)
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setObjectName("footer")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(4)

        def ghost(text: str, icon_name: str, slot, danger: bool = False) -> QPushButton:
            b = QPushButton(" " + text, bar)
            b.setObjectName("ghostDanger" if danger else "ghost")
            b.setCursor(Qt.PointingHandCursor)
            b.setIcon(icon(icon_name, 14, self._pal.c("txt2")))
            b.setIconSize(QSize(14, 14))
            b.clicked.connect(slot)
            b.setFixedHeight(30)
            # 按文字实际宽度锁死，避免窗口拖窄时被压缩掉字
            fm = b.fontMetrics()
            text_w = fm.horizontalAdvance(b.text()) + 28   # 图标 + 内边距
            b.setMinimumWidth(max(b.sizeHint().width(), text_w))
            lay.addWidget(b)
            return b

        self._btn_offline = ghost("全选离线", "power", self._on_select_offline)
        self._btn_scan = ghost("扫描内网", "search", self._on_scan_lan)
        self._btn_add = ghost("添加", "plus", self._on_add)
        self._btn_edit = ghost("编辑", "pencil", self._on_edit)
        self._btn_del = ghost("删除", "trash", self._on_delete, danger=True)

        lay.addStretch(1)

        self.wake_btn = QPushButton()
        self.wake_btn.setCursor(Qt.PointingHandCursor)
        self.wake_btn.setFixedHeight(36)
        self.wake_btn.setIcon(icon("bolt", 15, "#FFFFFF"))
        self.wake_btn.clicked.connect(self._on_wake)
        self.wake_btn.setEnabled(False)
        self.wake_btn.setMinimumWidth(150)   # 容纳「唤醒选中 (99)」
        lay.addWidget(self.wake_btn)

        self._footer = bar
        root.addWidget(bar)

        # 依据底栏实际需求推算最小宽度：硬编码数字在不同字体/DPI 下会失准，
        # 导致左右拖窄时按钮文字被截断。
        self._apply_footer_min_width()

    def _apply_footer_min_width(self) -> None:
        """按底栏各按钮的真实 sizeHint 设置窗口最小宽度。

        sizeHint 会随字体、DPI、QSS 内边距变化，硬编码数字必然在某种环境下失准，
        导致左右拖窄时按钮文字被压掉。这里每次调用都重新测量。
        """
        lay = self._footer.layout()
        if lay is None:
            return

        widgets = []
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if isinstance(w, QPushButton):
                widgets.append(w)
        if not widgets:
            return

        need = sum(max(w.minimumWidth(), w.sizeHint().width()) for w in widgets)
        m = lay.contentsMargins()
        required = need + lay.spacing() * max(0, lay.count() - 1) + m.left() + m.right()
        self.setMinimumWidth(max(MIN_W, required + 24))

    # ================================================================ 更多菜单
    def _show_more_menu(self) -> None:
        p = self._pal
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu{{background:{p.h('bg')};border:1px solid {p.rgba('border')};"
            f"border-radius:8px;padding:5px;}}"
            f"QMenu::item{{height:30px;padding:0 20px 0 10px;border-radius:6px;"
            f"color:{p.h('txt2')};font-size:12px;}}"
            f"QMenu::item:selected{{background:{p.h('surface_hi')};color:{p.h('txt')};}}"
            f"QMenu::item:disabled{{color:{p.h('txt3')};}}"
            f"QMenu::separator{{height:1px;background:{p.rgba('hairline')};margin:4px 6px;}}"
        )

        menu.addAction(icon("search", 14, p.c("txt2")), "扫描内网机器…")
        menu.addAction(icon("import", 14, p.c("txt2")), "导入机器列表…")
        menu.addAction(icon("export", 14, p.c("txt2")), "导出机器列表…")
        menu.addSeparator()

        act_auto = menu.addAction(icon("power2", 14, p.c("txt2")), "开机自启")
        act_auto.setCheckable(True)
        act_auto.setChecked(bool(self._autostart_getter and self._autostart_getter()))

        act_tray = menu.addAction(icon("tray", 14, p.c("txt2")), "关闭时最小化到托盘")
        act_tray.setCheckable(True)
        act_tray.setChecked(self._minimize_to_tray)

        # 主题子菜单
        theme_menu = menu.addMenu(icon("palette", 14, p.c("txt2")), "配色方案")
        theme_menu.setStyleSheet(menu.styleSheet())
        self._theme_actions = {}
        for key, label in (("system", "跟随系统"), ("light", "浅色"), ("dark", "深色")):
            act = theme_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(self._theme == key)
            self._theme_actions[key] = act

        menu.addSeparator()
        menu.addAction(icon("info2", 14, p.c("txt2")), "关于 WakeNow")

        chosen = menu.exec(self._btn_more.mapToGlobal(QPoint(0, CHROME_H)))
        if chosen is None:
            return

        # 主题项优先判断（文字可能与其它项重名）
        for key, act in getattr(self, "_theme_actions", {}).items():
            if chosen is act:
                self.set_theme(key)
                return

        text = chosen.text()
        if text.startswith("扫描"):
            self._on_scan_lan()
        elif text.startswith("导入"):
            self._on_import()
        elif text.startswith("导出"):
            self._on_export()
        elif text == "开机自启":
            if self._autostart_setter:
                self._autostart_setter(chosen.isChecked())
        elif text.startswith("关闭时最小化"):
            self._minimize_to_tray = chosen.isChecked()
            if self._settings_saver:
                self._settings_saver()
        elif text.startswith("关于"):
            self._show_about()

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "关于 WakeNow",
            "<b>WakeNow</b> 1.2<br><br>"
            "局域网唤醒（Wake-on-LAN）小工具。<br>"
            "唤醒只需 MAC，IP 可自动发现。",
        )

    # ================================================================ 扫描内网
    def _on_scan_lan(self) -> None:
        from .scan_dialog import ScanDialog

        dlg = ScanDialog(self._pal, self._machines, self)
        if dlg.exec() != ScanDialog.Accepted:
            return
        picked = dlg.selected_machines()
        if not picked:
            return

        known = {m.display_mac for m in self._machines}
        added = [m for m in picked if m.display_mac not in known]
        if not added:
            self.toast("info", "所选机器都已存在")
            return

        self._machines.extend(added)
        self._persist()
        self.rebuild_rows()
        skipped = len(picked) - len(added)
        msg = f"已添加 {len(added)} 台机器"
        if skipped:
            msg += f"，跳过 {skipped} 台重复"
        self.toast("success", msg)
        self.request_scan()

    # ================================================================ 导入导出
    def _on_export(self) -> None:
        from ..transfer import default_export_name, export_to_file

        if not self._machines:
            self.toast("info", "当前没有机器可导出")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出机器列表",
            os.path.join(os.path.expanduser("~"), default_export_name()),
            "JSON 文件 (*.json)",
        )
        if not path:
            return
        try:
            n = export_to_file(self._machines, path)
        except OSError as exc:
            self.toast("error", f"导出失败：{exc}")
            return
        self.toast("success", f"已导出 {n} 台机器")

    def _on_import(self) -> None:
        from ..transfer import ImportError_, load_from_file, plan_merge
        from .import_dialog import MODE_REPLACE, ImportDialog

        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入机器列表",
            os.path.expanduser("~"),
            "JSON 文件 (*.json)",
        )
        if not path:
            return

        try:
            result = load_from_file(path)
        except ImportError_ as exc:
            self.toast("error", str(exc))
            return

        if not result.machines:
            self.toast("error", "文件里没有可导入的机器")
            return

        plan = plan_merge(result.machines, self._machines)
        dlg = ImportDialog(
            self._pal,
            filename=os.path.basename(path),
            added=len(plan.added),
            existing=len(plan.existing),
            current_total=len(self._machines),
            skipped=len(result.skipped),
            parent=self,
        )
        if dlg.exec() != ImportDialog.Accepted:
            return

        if dlg.mode() == MODE_REPLACE:
            self._machines = list(result.machines)
            self._selected.clear()
            self._persist()
            self.rebuild_rows()
            self.toast("success", f"已导入 {len(result.machines)} 台机器（替换）")
        else:
            if not plan.added:
                self.toast("info", f"全部 {len(plan.existing)} 台已存在，未做更改")
                return
            self._machines.extend(plan.added)
            self._persist()
            self.rebuild_rows()
            msg = f"已导入 {len(plan.added)} 台"
            if plan.existing:
                msg += f"，跳过 {len(plan.existing)} 台重复"
            self.toast("success", msg)

        self.request_discover()
        self.request_scan()

    # ================================================================ 关闭行为
    def _on_close_clicked(self) -> None:
        """× 的语义：最小化到托盘（可配置）。"""
        if self._minimize_to_tray and self._tray_available:
            self.hide()
            self.hide_to_tray.emit()
        else:
            self.close()

    # ================================================================ 主题
    def apply_palette(self, pal: Palette) -> None:
        self._pal = pal
        # 主窗口自带一份 QSS（按自身主题），保证同一进程里能并存浅/深两种窗口；
        # 对话框是独立顶层窗口，需自行设置（见 MachineDialog）
        self.setStyleSheet(build_qss(pal))

        self._chrome.setStyleSheet(
            f"#chrome{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {pal.h('chrome_top')},stop:1 {pal.h('chrome_bottom')});"
            f"border-bottom:1px solid {pal.rgba('hairline')};"
            f"border-top-left-radius:8px;border-top-right-radius:8px;}}"
        )
        for b in (self._btn_min, self._btn_close):
            b.setStyleSheet(
                "QPushButton{background:transparent;border:0;}"
                f"QPushButton:hover{{background:{pal.h('surface_hi')};}}"
            )
        self._btn_close.setStyleSheet(
            "QPushButton{background:transparent;border:0;}"
            f"QPushButton:hover{{background:{pal.h('danger')};}}"
        )
        self._btn_close.setIcon(icon("close", 13, pal.c("txt2"), 1.5))

        brand = self._chrome.findChild(QLabel, "brand")
        if brand:
            brand.setStyleSheet(
                f"font-size:13px;font-weight:600;color:{pal.h('txt')};background:transparent;"
            )

        self._thead.setStyleSheet(
            f"#thead{{background:{pal.h('surface_sunk')};"
            f"border-bottom:1px solid {pal.rgba('border')};}}"
        )
        for lab in (self._sort_name, self._sort_ip, self._status_head):
            lab.setStyleSheet(
                f"color:{pal.h('txt3')};font-size:10px;font-weight:600;"
                "letter-spacing:0.05em;background:transparent;"
            )
        self._footer.setStyleSheet(
            f"#footer{{border-top:1px solid {pal.rgba('hairline')};"
            f"background:{pal.h('bg')};"
            f"border-bottom-left-radius:8px;border-bottom-right-radius:8px;}}"
        )
        self.no_result.setStyleSheet(
            f"color:{pal.h('txt3')};font-size:12px;background:transparent;"
        )

        # 列表容器保持透明，由主窗口 paintEvent 统一铺底色
        for w in (self._list_host, self.scroll.viewport()):
            w.setStyleSheet("background:transparent;")

        self._search_action.setIcon(
            QIcon(pixmap("search", 15, pal.c("txt3"), 1.7))
        )

        self._btn_offline.setIcon(icon("power", 14, pal.c("txt2")))
        self._btn_add.setIcon(icon("plus", 14, pal.c("txt2")))
        self._btn_edit.setIcon(icon("pencil", 14, pal.c("txt2")))
        self._btn_del.setIcon(icon("trash", 14, pal.c("txt2")))

        self.cb_all.set_palette(pal)
        self.empty.set_palette(pal)
        if hasattr(self, "toast_host"):
            self.toast_host.set_palette(pal)

        for row in self._rows.values():
            row.set_palette(pal)

        self._update_stats()
        self._update_wake_button()

        # QSS 应用后按钮的 sizeHint 才准确，此时重新校正最小宽度
        if hasattr(self, "_footer"):
            self._apply_footer_min_width()

    def switch_theme(self, dark: bool) -> None:
        """切换浅色 / 深色。QSS 与各处手绘颜色都会跟着刷新。"""
        from ..theme import palette as make_palette

        self.apply_palette(make_palette(dark))
        self._btn_more.setIcon(icon("more", 16, self._pal.c("txt2"), 2.0))
        self._btn_min.setIcon(icon("min", 14, self._pal.c("txt2"), 1.5))
        self.update()

    def set_theme(self, theme: str) -> None:
        """设置配色方案并立即生效（theme: system / light / dark）。"""
        from ..theme import resolve_dark

        self._theme = theme if theme in ("system", "light", "dark") else "system"
        self.switch_theme(resolve_dark(self._theme))
        if self._theme_changed:
            self._theme_changed(self._theme)

    # ================================================================ 数据
    def visible_machines(self) -> list[Machine]:
        kw = self._query.strip().lower()
        items = [
            m
            for m in self._machines
            if not kw
            or kw in m.name.lower()
            or kw in m.ip.lower()
            or kw in m.display_mac.lower()
        ]
        return self._sorter.apply(items)

    def rebuild_rows(self) -> None:
        # 清空
        for row in self._rows.values():
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        items = self.visible_machines()
        insert_at = self._list_lay.count() - 1  # 保留尾部 stretch

        for m in items:
            row = MachineRow(m, self._pal, self._list_host)
            row.toggled.connect(self._on_row_toggled)
            row.editRequested.connect(lambda mid: self._on_edit_id(mid))
            row.deleteRequested.connect(lambda mid: self._on_delete_id(mid))
            row.wakeRequested.connect(lambda mid: self._on_wake_id(mid))
            row.setContextMenuPolicy(Qt.CustomContextMenu)
            row.customContextMenuRequested.connect(
                lambda pos, r=row: self._show_context_menu(r, pos)
            )
            row.set_selected(m.id in self._selected)
            self._list_lay.insertWidget(insert_at, row)
            insert_at += 1
            self._rows[m.id] = row

        self._update_visibility()

    def _update_visibility(self) -> None:
        total = len(self._machines)
        shown = len(self.visible_machines())

        if total == 0:
            self.scroll.hide()
            self._thead.hide()
            self._toolbar.hide()          # 空状态不显示搜索与统计（对齐设计稿）
            self.empty.show()
            self.no_result.hide()
        elif shown == 0:
            self.scroll.hide()
            self._thead.hide()
            self._toolbar.show()
            self.empty.hide()
            self.no_result.show()
        else:
            self.empty.hide()
            self.no_result.hide()
            self._thead.show()
            self._toolbar.show()
            self.scroll.show()

        self.empty.btn.setEnabled(total == 0)
        self._update_select_all()
        self._update_stats()
        self._update_wake_button()

    # ================================================================ 交互
    def _on_search(self, text: str) -> None:
        self._query = text
        self.rebuild_rows()

    def _on_sort(self, key: str) -> None:
        if self._sorter.key == key:
            self._sorter.ascending = not self._sorter.ascending
        else:
            self._sorter.key = key
            self._sorter.ascending = True
        self.rebuild_rows()

    def _on_row_toggled(self, mid: str) -> None:
        if mid in self._selected:
            self._selected.discard(mid)
        else:
            self._selected.add(mid)
        row = self._rows.get(mid)
        if row:
            row.set_selected(mid in self._selected)
        self._update_select_all()
        self._update_wake_button()

    def _on_toggle_all(self) -> None:
        items = self.visible_machines()
        if not items:
            return
        all_on = all(m.id in self._selected for m in items)
        for m in items:
            if all_on:
                self._selected.discard(m.id)
            else:
                self._selected.add(m.id)
            row = self._rows.get(m.id)
            if row:
                row.set_selected(m.id in self._selected)
        self._update_select_all()
        self._update_wake_button()

    def _update_select_all(self) -> None:
        items = self.visible_machines()
        if not items:
            self.cb_all.set_state(CheckBox.STATE_OFF, animated=False)
            return
        n = sum(1 for m in items if m.id in self._selected)
        if n == 0:
            self.cb_all.set_state(CheckBox.STATE_OFF, animated=False)
        elif n == len(items):
            self.cb_all.set_state(CheckBox.STATE_ON, animated=False)
        else:
            self.cb_all.set_state(CheckBox.STATE_MIXED, animated=False)

    def _update_stats(self) -> None:
        p = self._pal
        counts = {STATUS_ONLINE: 0, STATUS_OFFLINE: 0, STATUS_WAKING: 0, STATUS_UNKNOWN: 0}
        for m in self._machines:
            counts[m.status if m.status in counts else STATUS_UNKNOWN] += 1

        def part(color: QColor, n: int, text: str) -> str:
            return (
                f'<span style="color:{color.name()};">●</span>'
                f'<span style="color:{p.h("txt2")};"> {n} {text}</span>'
            )

        sep = f'<span style="color:{p.h("txt3")};"> · </span>'
        parts = [
            part(p.c("online"), counts[STATUS_ONLINE], "在线"),
            part(p.c("offline"), counts[STATUS_OFFLINE], "离线"),
        ]
        if counts[STATUS_WAKING]:
            parts.append(part(p.c("waking"), counts[STATUS_WAKING], "唤醒中"))
        if counts[STATUS_UNKNOWN]:
            parts.append(part(p.c("txt3"), counts[STATUS_UNKNOWN], "未知"))

        self.stats.setText(
            f'<span style="font-size:11px;white-space:nowrap;">'
            + sep.join(parts)
            + "</span>"
        )

    def _update_wake_button(self) -> None:
        p = self._pal
        n = len(self._selected)
        total = sum(
            1 for m in self._machines if m.id in self._selected and m.status != STATUS_ONLINE
        )
        label = f"  唤醒选中 ({n})" if n else "  唤醒选中 (0)"
        self.wake_btn.setText(label)
        self.wake_btn.setEnabled(n > 0)

        if n > 0:
            self.wake_btn.setStyleSheet(
                f"QPushButton{{padding:0 16px;border:0;border-radius:7px;color:#fff;"
                f"font-size:13px;font-weight:600;"
                f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
                f"stop:0 {p.h('grad1')},stop:1 {p.h('grad2')});}}"
            )
            self.wake_btn.setIcon(icon("bolt", 15, "#FFFFFF"))
        else:
            bg = p.h("surface_hi") if not p.is_dark() else "#2A3038"
            self.wake_btn.setStyleSheet(
                f"QPushButton{{padding:0 16px;border:1px solid {p.rgba('border')};"
                f"border-radius:7px;color:{p.h('txt3')};font-size:13px;font-weight:600;"
                f"background:{bg};}}"
            )
            self.wake_btn.setIcon(icon("bolt", 15, p.c("txt3")))

    # ================================================================ 机器增删改
    def _on_add(self) -> None:
        dlg = MachineDialog(self._pal, None, self)
        if dlg.exec() == MachineDialog.Accepted:
            data = dlg.result_data()
            m = Machine(
                name=data["name"],
                mac=data["mac"],
                ip=data["ip"],
                broadcast=data["broadcast"],
                port=data["port"],
                probe=data["probe"],
                probe_port=data["probe_port"],
                status=STATUS_UNKNOWN,
            )
            self._machines.append(m)
            self._persist()
            self.rebuild_rows()
            self.toast("success", f"已添加「{m.name}」")
            if not m.ip:
                self.toast("info", "正在自动发现 IP…")
            self.request_discover()
            self.request_scan()

    def _current_single(self) -> Machine | None:
        picked = [m for m in self._machines if m.id in self._selected]
        if len(picked) != 1:
            self.toast(
                "error",
                "请先选择一台机器" if not picked else "一次只能编辑或删除一台机器",
            )
            return None
        return picked[0]

    def _on_edit(self) -> None:
        m = self._current_single()
        if m:
            self._edit_machine(m)

    def _on_edit_id(self, mid: str) -> None:
        m = self._find(mid)
        if m:
            self._edit_machine(m)

    def _edit_machine(self, m: Machine) -> None:
        dlg = MachineDialog(self._pal, m, self)
        if dlg.exec() == MachineDialog.Accepted:
            data = dlg.result_data()
            m.name = data["name"]
            m.mac = data["mac"]
            # 用户手填 IP 时取消「自动发现」标记；留空则交回自动发现
            m.ip = data["ip"]
            m.discovered = False
            m.broadcast = data["broadcast"]
            m.port = data["port"]
            m.probe = data["probe"]
            m.probe_port = data["probe_port"]
            m.probe_detail = ""   # 探测参数变了，清掉旧依据
            self._persist()
            self.rebuild_rows()
            self.toast("success", f"已保存「{m.name}」")
            self.request_discover()
            self.request_scan()

    def _on_delete(self) -> None:
        m = self._current_single()
        if m:
            self._delete_machine(m)

    def _on_delete_id(self, mid: str) -> None:
        m = self._find(mid)
        if m:
            self._delete_machine(m)

    def _delete_machine(self, m: Machine) -> None:
        self._machines = [x for x in self._machines if x.id != m.id]
        self._selected.discard(m.id)
        self._persist()
        self.rebuild_rows()
        self.toast("success", f"已删除「{m.name}」")
        self.request_scan()

    def _find(self, mid: str) -> Machine | None:
        for m in self._machines:
            if m.id == mid:
                return m
        return None

    def _persist(self) -> None:
        try:
            self._store.save(self._machines)
        except OSError as exc:
            self.toast("error", f"保存失败：{exc}")

    # ================================================================ 唤醒
    def _on_select_offline(self) -> None:
        n = 0
        for m in self.visible_machines():
            if m.status == STATUS_OFFLINE and m.id not in self._selected:
                self._selected.add(m.id)
                n += 1
                row = self._rows.get(m.id)
                if row:
                    row.set_selected(True)
        self._update_select_all()
        self._update_wake_button()
        if n:
            self.toast("info", f"已勾选 {n} 台离线机器")
        else:
            self.toast("info", "没有可勾选的离线机器")

    def _on_wake(self) -> None:
        picked = [m for m in self._machines if m.id in self._selected]
        if not picked:
            self.toast("error", "请先选择要唤醒的机器")
            return
        online = [m for m in picked if m.status == STATUS_ONLINE]
        targets = [m for m in picked if m.status != STATUS_ONLINE]

        if online:
            self.toast("info", f"{len(online)} 台已在线，已跳过")
        if not targets:
            self.toast("info", "所选机器均已在线，无需唤醒")
            return

        from ..wol import send_magic_packet
        from ..discover import local_ipv4

        local = local_ipv4()
        sent, failed = 0, []
        for m in targets:
            try:
                send_magic_packet(m, local_ip=local)
                m.status = STATUS_WAKING
                self._wake_deadline[m.id] = time.monotonic() + WAKE_TIMEOUT_S
                sent += 1
            except OSError:
                failed.append(m.name)

        if sent:
            self.toast("success", f"已向 {sent} 台机器发送唤醒包")
        for name in failed:
            self.toast("error", f"「{name}」发送失败，请检查网络连接")

        self._refresh_rows()
        # 唤醒后机器会开机上线，正是抓取真实 IP 的最好时机
        self.request_discover()
        self.request_scan()

    def _on_wake_id(self, mid: str) -> None:
        m = self._find(mid)
        if not m:
            return
        if m.status == STATUS_ONLINE:
            self.toast("info", f"「{m.name}」已在线")
            return
        from ..wol import send_magic_packet
        from ..discover import local_ipv4

        try:
            send_magic_packet(m, local_ip=local_ipv4())
            m.status = STATUS_WAKING
            self._wake_deadline[m.id] = time.monotonic() + WAKE_TIMEOUT_S
            self.toast("success", "已向 1 台机器发送唤醒包")
        except OSError:
            self.toast("error", f"「{m.name}」发送失败，请检查网络连接")
        self._refresh_rows()
        self.request_discover()
        self.request_scan()

    # ================================================================ 监控回调
    def on_scan(self, result: dict) -> None:
        changed = False
        for mid, payload in result.items():
            m = self._find(mid)
            if not m:
                continue
            online, detail = payload if isinstance(payload, tuple) else (bool(payload), "")
            if detail:
                m.probe_detail = detail

            if online:
                new_status = STATUS_ONLINE
                self._wake_deadline.pop(mid, None)
            elif m.status == STATUS_WAKING:
                new_status = STATUS_WAKING   # 仍等待，超时后回离线
            else:
                new_status = STATUS_OFFLINE
            if m.status != new_status:
                m.status = new_status
                changed = True

        if changed:
            self._refresh_statuses()
        else:
            # 状态没变但判定依据可能更新了，刷新 tooltip
            self._refresh_tooltips()

    def _refresh_statuses(self) -> None:
        for m in self._machines:
            row = self._rows.get(m.id)
            if row:
                row.machine = m
                row.apply_style()
        self._update_stats()
        self._update_wake_button()

    def _check_wake_timeouts(self) -> None:
        now = time.monotonic()
        expired = [mid for mid, dl in self._wake_deadline.items() if now > dl]
        if not expired:
            return
        for mid in expired:
            self._wake_deadline.pop(mid, None)
            m = self._find(mid)
            if m and m.status == STATUS_WAKING:
                m.status = STATUS_OFFLINE
        self._refresh_statuses()

    def request_scan(self) -> None:
        """通知外部监控立即扫一轮。"""
        if self._scan_requester is not None:
            self._scan_requester()

    _scan_requester = None

    def set_scan_requester(self, fn) -> None:
        self._scan_requester = fn

    def request_discover(self, force: dict[str, str] | None = None) -> None:
        """请求后台做一次 MAC → IP 发现。

        force: {mac: ip}，来自刚刚唤醒成功的 UDP 发送目标，比 ARP 更权威。
        """
        if self._discover_requester is not None:
            self._discover_requester(force)

    _discover_requester = None

    def set_discover_requester(self, fn) -> None:
        self._discover_requester = fn

    def on_discovered(self, result: dict) -> None:
        """接收后台发现的 IP：只更新「没有 IP」或「自动发现」的机器。

        发现到的 IP 会立即落盘：机器关机后它的 ARP 表项会消失，下次就发现不到了，
        只有把「上次已知 IP」存下来，关机时才能判定为离线而不是未知。
        """
        changed = False
        for mid, ip in result.items():
            m = self._find(mid)
            if not m or m.ip == ip:
                continue
            if m.ip and not m.discovered:
                continue   # 用户手填的 IP 不覆盖
            m.ip = ip
            m.discovered = True
            changed = True
        if changed:
            self._persist()
            self._refresh_rows()
            self.request_scan()

    def _refresh_rows(self) -> None:
        for m in self._machines:
            row = self._rows.get(m.id)
            if row:
                row.update_machine(m)
        self._update_stats()

    def _refresh_tooltips(self) -> None:
        for m in self._machines:
            row = self._rows.get(m.id)
            if row:
                row.refresh_tooltip()

    def scan_targets(self) -> list[tuple[str, object]]:
        return [(m.id, m) for m in self._machines if m.has_ip]

    def discover_targets(self) -> list[tuple[str, str]]:
        """需要发现 IP 的机器：没有 IP，或 IP 是自动发现来的。"""
        return [(m.id, m.mac) for m in self._machines if (not m.ip or m.discovered)]

    def known_ips(self) -> list[str]:
        return [m.ip for m in self._machines if m.has_ip]

    # ================================================================ 右键菜单
    def _show_context_menu(self, row: MachineRow, pos: QPoint) -> None:
        p = self._pal
        m = row.machine
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu{{background:{p.h('bg')};border:1px solid {p.rgba('border')};"
            f"border-radius:8px;padding:5px;}}"
            f"QMenu::item{{height:30px;padding:0 18px 0 10px;border-radius:6px;"
            f"color:{p.h('txt2')};font-size:12px;}}"
            f"QMenu::item:selected{{background:{p.h('surface_hi')};color:{p.h('txt')};}}"
            f"QMenu::separator{{height:1px;background:{p.rgba('hairline')};margin:4px 6px;}}"
        )
        a_wake = menu.addAction(icon("bolt", 14, p.c("txt2")), "唤醒")
        if m.status == STATUS_ONLINE:
            a_wake.setEnabled(False)
            a_wake.setText("唤醒（已在线）")
        menu.addAction(icon("pencil", 14, p.c("txt2")), "编辑")
        menu.addSeparator()
        a_del = menu.addAction(icon("trash", 14, p.c("txt2")), "删除")

        chosen = menu.exec(row.mapToGlobal(pos))
        if chosen is None:
            return
        text = chosen.text()
        if text.startswith("唤醒"):
            self._on_wake_id(m.id)
        elif text == "编辑":
            self._edit_machine(m)
        elif text == "删除":
            self._delete_machine(m)

    # ================================================================ Toast
    def toast(self, kind: str, text: str) -> None:
        self.toast_host.show_toast(kind, text)

    # ================================================================ 窗口行为
    def paintEvent(self, event) -> None:  # noqa: N802
        """绘制带 8px 圆角的不透明窗口底面（配合 TranslucentBackground）。"""
        p = self._pal
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 8, 8)
        painter.fillPath(path, p.c("bg"))
        painter.setPen(QPen(p.a("border_hi"), 1))
        painter.drawPath(path)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if hasattr(self, "toast_host"):
            self.toast_host.setGeometry(self.rect())
            self.toast_host.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "toast_host"):
            self.toast_host.setGeometry(self.rect())
            self.toast_host.raise_()

    # --- 无边框：拖动 + 边缘拉伸
    def _edge_at(self, pos: QPoint) -> int:
        """判断鼠标落在哪条边（用于拉伸）。返回 EDGE_* 位组合，0 表示内部。"""
        m = RESIZE_MARGIN
        r = self.rect()
        x, y = pos.x(), pos.y()
        edge = 0
        if x <= m:
            edge |= self.EDGE_LEFT
        elif x >= r.width() - m:
            edge |= self.EDGE_RIGHT
        if y <= m:
            edge |= self.EDGE_TOP
        elif y >= r.height() - m:
            edge |= self.EDGE_BOTTOM
        return edge

    @staticmethod
    def _cursor_for_edge(edge: int):
        if edge in (8 | 2, 4 | 1):      # 左上/右下
            return Qt.SizeFDiagCursor
        if edge in (8 | 1, 4 | 2):      # 右上/左下
            return Qt.SizeBDiagCursor
        if edge & (8 | 4):              # 左右
            return Qt.SizeHorCursor
        if edge & (2 | 1):              # 上下
            return Qt.SizeVerCursor
        return Qt.ArrowCursor

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            edge = self._edge_at(event.position().toPoint())
            if edge:
                self._resize_edge = edge
                self._resize_origin = event.globalPosition().toPoint()
                self._resize_geo = self.geometry()
                self._drag_offset = None
                event.accept()
                return
            if event.position().y() < CHROME_H:
                self._drag_offset = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
            else:
                self._drag_offset = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        # 正在拉伸
        if getattr(self, "_resize_edge", 0):
            delta = event.globalPosition().toPoint() - self._resize_origin
            geo = self._resize_geo
            min_w = self.minimumWidth()
            min_h = self.minimumHeight()
            x, y, w, h = geo.x(), geo.y(), geo.width(), geo.height()

            if self._resize_edge & self.EDGE_LEFT:
                new_w = max(min_w, w - delta.x())
                x = geo.x() + (w - new_w)
                w = new_w
            if self._resize_edge & self.EDGE_RIGHT:
                w = max(min_w, w + delta.x())
            if self._resize_edge & self.EDGE_TOP:
                new_h = max(min_h, h - delta.y())
                y = geo.y() + (h - new_h)
                h = new_h
            if self._resize_edge & self.EDGE_BOTTOM:
                h = max(min_h, h + delta.y())

            self.setGeometry(x, y, w, h)
            event.accept()
            return

        # 拖动窗口
        if getattr(self, "_drag_offset", None) is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            super().mouseMoveEvent(event)
            return

        # 悬停时更新光标
        if not event.buttons():
            self.setCursor(self._cursor_for_edge(self._edge_at(event.position().toPoint())))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_offset = None
        self._resize_edge = 0
        self.unsetCursor()
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if not getattr(self, "_resize_edge", 0):
            self.unsetCursor()
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_F2:
            self._on_edit()
        elif event.key() == Qt.Key_Delete:
            self._on_delete()
        elif event.key() == Qt.Key_A and event.modifiers() & Qt.ControlModifier:
            self._on_toggle_all()
        elif event.key() == Qt.Key_F5:
            self.request_scan()
        else:
            super().keyPressEvent(event)
