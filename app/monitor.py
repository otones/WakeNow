"""后台探测：在线状态（ping / TCP）与 MAC → IP 发现（ARP）。

两个独立线程：
- Monitor     每 N 秒并发探测一轮，回传 {id: (是否在线, 依据说明)}
- Discoverer  按需做 ARP 扫描，回传 {id: 当前 IP}
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QThread, Signal, Slot

from .probe import DEFAULT_PROBE_TIMEOUT_MS, ping_once, probe, tcp_once

__all__ = [
    "Monitor",
    "Discoverer",
    "ping_once",
    "tcp_once",
    "DEFAULT_PROBE_TIMEOUT_MS",
]

# Windows 下隐藏子进程窗口
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


# ================================================================ 在线探测
class _PingWorker(QObject):
    """常驻 worker：每 interval 秒探测一轮，结果用 dict{id: (bool, str)} 回传。"""

    scanned = Signal(dict)

    def __init__(self, interval_ms: int = 3000, timeout_ms: int = DEFAULT_PROBE_TIMEOUT_MS) -> None:
        super().__init__()
        self._interval = interval_ms
        self._timeout = timeout_ms
        self._targets: list = []      # [(id, Machine)]
        self._stop = False
        self._burst = False
        self._pool = ThreadPoolExecutor(max_workers=12, thread_name_prefix="probe")

    def set_targets(self, targets: list) -> None:
        self._targets = list(targets)

    def request_stop(self) -> None:
        self._stop = True

    def request_burst(self) -> None:
        self._burst = True

    def run(self) -> None:
        while not self._stop:
            targets = list(self._targets)
            if targets:
                futures = {
                    mid: self._pool.submit(probe, m, self._timeout)
                    for mid, m in targets
                }
                result: dict[str, tuple[bool, str]] = {}
                for mid, fut in futures.items():
                    try:
                        result[mid] = fut.result(timeout=self._timeout / 1000 + 3)
                    except Exception:
                        result[mid] = (False, "探测异常")
                if not self._stop:
                    self.scanned.emit(result)
            self._sleep()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _sleep(self) -> None:
        waited = 0
        while waited < self._interval and not self._stop and not self._burst:
            QThread.msleep(100)
            waited += 100
        self._burst = False


class Monitor(QObject):
    """在线状态监控门面。"""

    scanned = Signal(dict)   # {machine_id: (online_bool, detail_str)}

    def __init__(self, parent: QObject | None = None, interval_ms: int = 3000) -> None:
        super().__init__(parent)
        self._thread = QThread()
        self._worker = _PingWorker(interval_ms=interval_ms)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.scanned.connect(self.scanned)

    def start(self) -> None:
        if not self._thread.isRunning():
            self._thread.start()

    def stop(self) -> None:
        self._worker.request_stop()
        self._thread.quit()
        self._thread.wait(2500)

    def set_targets(self, targets: list) -> None:
        """targets: [(machine_id, Machine)]；无 IP 的机器由调用方过滤。"""
        self._worker.set_targets(targets)

    def set_interval(self, ms: int) -> None:
        self._worker._interval = max(800, ms)

    def scan_now(self) -> None:
        self._worker.request_burst()


# ================================================================ IP 发现
class _DiscoverWorker(QObject):
    """跑一次 ARP 扫描：MAC → 当前 IP。"""

    finished = Signal(dict)   # {machine_id: ip}

    def __init__(self) -> None:
        super().__init__()
        self._job: tuple[list[tuple[str, str]], list[str]] | None = None

    def set_job(
        self,
        targets: list[tuple[str, str]],      # [(machine_id, mac)]
        candidate_ips: list[str],
    ) -> None:
        self._job = (list(targets), list(candidate_ips))

    @Slot()
    def run(self) -> None:
        from .discover import discover
        from .models import normalize_mac

        job, self._job = self._job, None
        if job is None:
            return
        targets, candidates = job
        try:
            found = discover([mac for _mid, mac in targets], candidates)
        except Exception:
            found = {}
        result: dict[str, str] = {}
        for mid, mac in targets:
            ip = found.get(normalize_mac(mac))
            if ip:
                result[mid] = ip
        self.finished.emit(result)


class Discoverer(QObject):
    """发现器的线程外壳：用信号唤醒 worker，保证跨线程投递可靠。"""

    finished = Signal(dict)        # {machine_id: ip}
    _trigger = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread = QThread()
        self._worker = _DiscoverWorker()
        self._worker.moveToThread(self._thread)
        self._worker.finished.connect(self.finished)
        self._trigger.connect(self._worker.run)
        self._thread.start()

    def request(self, targets: list[tuple[str, str]], candidate_ips: list[str]) -> None:
        if not targets:
            return
        self._worker.set_job(targets, candidate_ips)
        self._trigger.emit()

    def stop(self) -> None:
        self._thread.quit()
        self._thread.wait(2500)
