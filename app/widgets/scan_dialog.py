"""局域网扫描对话框：选择网段 → 扫描 → 勾选设备 → 保存为机器。"""
from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..icons import icon
from ..models import DEFAULT_PROBE_PORT, PROBE_AUTO, Machine, normalize_mac
from ..scanner import Found, prefix_from_network, quick_prefixes, scan
from ..theme import Palette, build_qss
from .checkbox import CheckBox


# ================================================================ 扫描线程
class _ScanWorker(QObject):
    progress = Signal(str)
    found = Signal(object)      # Found，逐台实时回调
    finished = Signal(object)   # ScanReport

    def __init__(self) -> None:
        super().__init__()
        self._job: tuple[list[str], str] | None = None
        self._cancelled = False

    def set_job(self, prefixes: list[str], network: str = "") -> None:
        self._cancelled = False
        self._job = (list(prefixes), network)

    def request_stop(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        job, self._job = self._job, None
        if job is None:
            return
        prefixes, network = job
        try:
            report = scan(
                prefixes,
                verify=True,
                on_progress=lambda m, **k: self.progress.emit(m),
                should_stop=lambda: self._cancelled,
                on_found=lambda f: self.found.emit(f),
            )
        except Exception as exc:
            from ..scanner import ScanReport

            report = ScanReport(prefixes=prefixes, error=f"扫描出错：{exc}")
        if not self._cancelled:
            self.finished.emit(report)


class Scanner(QObject):
    """扫描器的线程外壳，保证界面不卡。"""

    progress = Signal(str)
    found = Signal(object)
    finished = Signal(object)
    _trigger = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread = QThread()
        self._worker = _ScanWorker()
        self._worker.moveToThread(self._thread)
        self._worker.progress.connect(self.progress)
        self._worker.found.connect(self.found)
        self._worker.finished.connect(self.finished)
        self._trigger.connect(self._worker.run)
        self._thread.start()

    def start(self, prefixes: list[str], network: str = "") -> None:
        self._worker.set_job(prefixes, network)
        self._trigger.emit()

    def stop(self) -> None:
        """停止扫描：先请求 worker 中断，再退出线程。

        直接 quit() 无法打断正在阻塞的扫描，必须等它自己看到标志位退出。
        """
        self._worker.request_stop()
        self._thread.quit()
        if not self._thread.wait(6000):
            # 还在跑（网络超时较长），再等等，避免析构时崩溃
            self._thread.wait(4000)


# ================================================================ 列表行
class _ScanRow(QWidget):
    toggled = Signal(str)   # ip

    def __init__(self, found: Found, pal: Palette, parent=None) -> None:
        super().__init__(parent)
        self.found = found
        self._pal = pal
        self._selected = False
        self._hover = False
        self.setFixedHeight(42)
        self.setAttribute(Qt.WA_Hover, True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(10)

        self.cb = CheckBox(pal, self)
        self.cb.clicked.connect(lambda: self.toggled.emit(found.ip))

        self.name = QLabel(found.hostname or "（未知设备）")
        self.meta = QLabel(f"{found.ip}　{found.mac}")
        self.meta.setStyleSheet("font-size:10px;")

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        col.addWidget(self.name)
        col.addWidget(self.meta)

        self.status = QLabel("")
        self.status.setFixedWidth(52)
        self.status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        lay.addWidget(self.cb, 0, Qt.AlignVCenter)
        lay.addLayout(col, 1)
        lay.addWidget(self.status, 0, Qt.AlignVCenter)

        self.apply_style()

    def apply_style(self) -> None:
        p = self._pal
        # 文字内容也要跟着 found 同步（主机名是后补的）
        self.name.setText(self.found.hostname or "（未知设备）")
        self.meta.setText(f"{self.found.ip}　{self.found.mac}")
        dim = not self.found.alive
        name_color = p.h("txt") if not dim else p.h("txt3")
        self.name.setStyleSheet(
            f"font-size:12.5px;font-weight:500;color:{name_color};background:transparent;"
        )
        self.meta.setStyleSheet(
            f"font-size:10px;color:{p.h('txt3')};background:transparent;"
            f"font-family:'Cascadia Mono','Consolas',monospace;"
        )
        if self.found.already_known:
            self.status.setText("已添加")
            self.status.setStyleSheet(
                f"font-size:10.5px;color:{p.h('txt3')};background:transparent;"
            )
        elif dim:
            self.status.setText("离线")
            self.status.setStyleSheet(
                f"font-size:10.5px;color:{p.h('txt3')};background:transparent;"
            )
        else:
            self.status.setText("在线")
            self.status.setStyleSheet(
                f"font-size:10.5px;color:{p.h('online')};background:transparent;"
            )

    def set_selected(self, on: bool) -> None:
        self._selected = on
        self.cb.set_state(CheckBox.STATE_ON if on else CheckBox.STATE_OFF)
        self.update()

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
        painter.fillRect(self.rect(), p.c("bg"))

        if self._selected:
            painter.fillRect(self.rect(), p.a("accent_soft"))
        elif self._hover:
            painter.fillRect(self.rect(), p.a("hover"))

        painter.setPen(QPen(p.a("hairline"), 1))
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


# ================================================================ 对话框
class ScanDialog(QDialog):
    """扫描结果选择器。accept 后用 selected_machines() 取结果。"""

    def __init__(self, pal: Palette, existing: list[Machine], parent=None) -> None:
        super().__init__(parent)
        self._pal = pal
        self._existing = existing
        self._existing_macs = {m.display_mac for m in existing}
        self._rows: dict[str, _ScanRow] = {}
        self._selected: set[str] = set()
        self._scanning = False
        self._alive_count = 0

        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedSize(520, 560)
        self.setStyleSheet(build_qss(pal))

        # 用快速版本填默认网段（1ms），完整网段识别放到扫描线程里做，
        # 否则要等 route/PowerShell 几百毫秒到几秒，弹窗迟迟不出现
        self._usable = quick_prefixes()
        self._skipped: list[str] = []

        self._scanner = Scanner(self)
        self._scanner.progress.connect(self._on_progress)
        self._scanner.found.connect(self._on_found)
        self._scanner.finished.connect(self._on_finished)

        self._build()
        self._pending_scan = True

    def showEvent(self, event) -> None:  # noqa: N802
        """窗口真正显示后再启动扫描：保证用户先看到界面，而不是卡着等扫描。"""
        super().showEvent(event)
        if self._pending_scan:
            self._pending_scan = False
            # 两段：先让本帧画完，再开扫
            QTimer.singleShot(30, self._start_scan)

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
        hl.setContentsMargins(16, 14, 12, 8)
        title = QLabel("扫描内网机器")
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

        # 网段选择栏
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 0, 16, 10)
        bl.setSpacing(8)

        self.network_edit = QLineEdit()
        self.network_edit.setObjectName("field")
        self.network_edit.setPlaceholderText("例如 192.168.2")
        default_net = self._usable[0] if self._usable else "192.168.1"
        self.network_edit.setText(default_net)
        self.network_edit.setFixedHeight(30)
        self.network_edit.returnPressed.connect(self._start_scan)

        self.btn_scan = QPushButton("开始扫描")
        self.btn_scan.setCursor(Qt.PointingHandCursor)
        self.btn_scan.setFixedHeight(30)
        self.btn_scan.clicked.connect(self._start_scan)
        self.btn_scan.setStyleSheet(
            "QPushButton{padding:0 14px;border:0;border-radius:6px;color:#fff;"
            "font-size:12px;font-weight:600;"
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 {p.h('grad1')},stop:1 {p.h('grad2')});}}"
            "QPushButton:disabled{background:" + p.h("surface_hi") + ";color:" + p.h("txt3") + ";}"
        )

        bl.addWidget(QLabel("网段"), 0)
        bl.addWidget(self.network_edit, 1)
        bl.addWidget(self.btn_scan, 0)
        root.addWidget(bar)

        # 进度/提示
        self.hint = QLabel("准备扫描…")
        self.hint.setStyleSheet(
            f"color:{p.h('txt3')};font-size:11.5px;background:transparent;"
        )
        self.hint.setContentsMargins(16, 0, 16, 8)
        root.addWidget(self.hint)

        # 结果列表
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            f"QScrollArea{{border-top:1px solid {p.rgba('hairline')};"
            f"border-bottom:1px solid {p.rgba('hairline')};background:transparent;}}"
        )
        host = QWidget()
        self.list_lay = QVBoxLayout(host)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(0)
        self.list_lay.addStretch(1)
        self.scroll.setWidget(host)
        root.addWidget(self.scroll, 1)

        # 底部
        foot = QWidget()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(16, 10, 16, 14)
        fl.setSpacing(8)

        self.btn_all = QPushButton("全选在线")
        self.btn_all.setCursor(Qt.PointingHandCursor)
        self.btn_all.setFixedHeight(30)
        self.btn_all.setStyleSheet(self._ghost_style())
        self.btn_all.clicked.connect(self._toggle_all)

        self.summary = QLabel("")
        self.summary.setStyleSheet(
            f"color:{p.h('txt2')};font-size:11.5px;background:transparent;"
        )

        self.btn_save = QPushButton("保存选中")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setFixedHeight(32)
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self.accept)
        self.btn_save.setStyleSheet(
            "QPushButton{padding:0 18px;border:0;border-radius:7px;color:#fff;"
            "font-size:12.5px;font-weight:600;"
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 {p.h('grad1')},stop:1 {p.h('grad2')});}}"
            f"QPushButton:disabled{{background:{p.h('surface_hi')};"
            f"color:{p.h('txt3')};}}"
        )

        fl.addWidget(self.btn_all)
        fl.addStretch(1)
        fl.addWidget(self.summary)
        fl.addWidget(self.btn_save)
        root.addWidget(foot)

    def _ghost_style(self) -> str:
        p = self._pal
        return (
            f"QPushButton{{padding:0 12px;border:1px solid {p.rgba('border')};"
            f"border-radius:6px;background:transparent;color:{p.h('txt2')};"
            f"font-size:12px;}}"
            f"QPushButton:hover{{background:{p.h('surface_hi')};color:{p.h('txt')};}}"
            f"QPushButton:disabled{{color:{p.h('txt3')};}}"
        )

    # ---------------------------------------------------------------- 扫描
    def _start_scan(self) -> None:
        if self._scanning:
            return
        network = prefix_from_network(self.network_edit.text())
        if not network:
            self.hint.setText("网段格式不正确，应为 192.168.2 这样的前三段")
            return

        self._scanning = True
        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("扫描中…")
        self.hint.setText("正在扫描，约需 10–30 秒…")
        self._clear_rows()
        self._selected.clear()
        self._update_footer()
        self._scanner.start([network], network)

    def _on_progress(self, msg: str) -> None:
        # 进度只更新「正在做什么」，不覆盖已发现计数
        if "验证" in msg and self._rows:
            self.hint.setText(
                f"已发现 {len(self._rows)} 台"
                f"（{self._alive_count} 台在线），继续扫描中…"
            )
        else:
            self.hint.setText(msg)

    def _on_found(self, item) -> None:
        """扫描线程每确认一台就回调一次，立即插到列表里。

        同一 IP 会回调两次：先验证存活，后补主机名。
        第二次不能新建行，而是把新信息合并进原对象——否则行内引用会指向旧对象。
        """
        row = self._rows.get(item.ip)
        if row is None:
            item.already_known = item.mac in self._existing_macs
            row = _ScanRow(item, self._pal)
            row.toggled.connect(self._on_row_toggled)
            self._insert_row_sorted(row, item.ip)
            self._rows[item.ip] = row
        else:
            # 就地更新原对象，保证行内引用始终有效
            old = row.found
            old.alive = item.alive
            old.mac = item.mac
            if item.hostname:
                old.hostname = item.hostname
            old.already_known = old.mac in self._existing_macs
            row.found = old
            row.apply_style()

        # 在线数每次按实际状态重算，避免同一台被回调多次时重复计数
        self._alive_count = sum(1 for r in self._rows.values() if r.found.alive)
        if self._scanning:
            self.hint.setText(
                f"已发现 {len(self._rows)} 台"
                f"（{self._alive_count} 台在线），继续扫描中…"
            )

    def _insert_row_sorted(self, row: _ScanRow, ip: str) -> None:
        """按 IP 数值顺序找插入位置。"""
        key = tuple(int(x) for x in ip.split("."))
        target = self.list_lay.count() - 1   # 跳过尾部 stretch
        for i in range(self.list_lay.count() - 1):
            w = self.list_lay.itemAt(i).widget()
            if w is None or not isinstance(w, _ScanRow):
                continue
            other = tuple(int(x) for x in w.found.ip.split("."))
            if key < other:
                target = i
                break
        self.list_lay.insertWidget(target, row)

    def _on_finished(self, report) -> None:
        self._scanning = False
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("重新扫描")

        if report.error:
            self.hint.setText(report.error)
            self._update_footer()
            return

        total = len(self._rows)
        alive = sum(1 for r in self._rows.values() if r.found.alive)
        self.hint.setText(
            f"发现 {total} 台设备（{alive} 台在线）"
            f"　已扫描 {', '.join(p + '.0/24' for p in report.prefixes)}"
        )
        self._update_footer()

    def _clear_rows(self) -> None:
        for row in self._rows.values():
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()
        self._alive_count = 0

    def _fill_rows(self, found: list[Found]) -> None:
        """批量填充（测试与回放用）；正常扫描走 _on_found 实时插入。"""
        for f in found:
            row = _ScanRow(f, self._pal)
            row.toggled.connect(self._on_row_toggled)
            self._insert_row_sorted(row, f.ip)
            self._rows[f.ip] = row
        self._alive_count = sum(1 for r in self._rows.values() if r.found.alive)

    def _on_row_toggled(self, ip: str) -> None:
        row = self._rows.get(ip)
        if row is None:
            return
        if ip in self._selected:
            self._selected.discard(ip)
            row.set_selected(False)
        else:
            self._selected.add(ip)
            row.set_selected(True)
        self._update_footer()

    def _toggle_all(self) -> None:
        candidates = [
            ip
            for ip, row in self._rows.items()
            if row.found.alive and not row.found.already_known
        ]
        all_selected = all(ip in self._selected for ip in candidates) if candidates else False
        for ip in candidates:
            if all_selected:
                self._selected.discard(ip)
                self._rows[ip].set_selected(False)
            else:
                self._selected.add(ip)
                self._rows[ip].set_selected(True)
        self._update_footer()

    def _update_footer(self) -> None:
        n = len(self._selected)
        self.btn_save.setEnabled(n > 0)
        self.summary.setText(f"已选 {n} 台" if n else "请勾选要保存的机器")

    # ---------------------------------------------------------------- 结果
    def selected_machines(self) -> list[Machine]:
        out: list[Machine] = []
        for ip in sorted(
            self._selected, key=lambda s: tuple(int(x) for x in s.split("."))
        ):
            row = self._rows.get(ip)
            if row is None:
                continue
            f = row.found
            out.append(
                Machine(
                    name=f.hostname or f.ip,
                    mac=f.mac,
                    ip=f.ip,
                    probe=PROBE_AUTO,
                    probe_port=DEFAULT_PROBE_PORT,
                )
            )
        return out

    def closeEvent(self, event) -> None:  # noqa: N802
        self._scanner.stop()
        super().closeEvent(event)

    def done(self, result: int) -> None:  # noqa: N802
        # 点「保存」/「取消」/「×」都会走 done，这里统一收线程，
        # 否则对话框析构时线程仍在跑会崩
        self._scanner.stop()
        super().done(result)
