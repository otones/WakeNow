"""开发用：验证「MAC → 自动发现 IP → ping 探测状态」全链路，并截图。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.models import STATUS_UNKNOWN, Machine
from app.monitor import Discoverer, Monitor
from app.theme import app_font, palette
from app.widgets.main_window import MainWindow


class NullStore:
    def save(self, machines):
        pass


app = QApplication([])
app.setFont(app_font())

machines = [
    Machine(name="房间主机", mac="50:03:CF:0D:EA:CF", status=STATUS_UNKNOWN, id="x1"),
    Machine(name="NAS", mac="C8:94:02:F8:6A:8D", status=STATUS_UNKNOWN, id="x2"),
    Machine(name="不存在", mac="02:00:00:00:00:99", status=STATUS_UNKNOWN, id="x3"),
]
win = MainWindow(machines, NullStore(), palette(False))
win.show()

mon = Monitor(interval_ms=1500)
mon.set_targets(win.scan_targets())
mon.scanned.connect(win.on_scan)

disc = Discoverer()
disc.finished.connect(win.on_discovered)

win.set_scan_requester(
    lambda: (mon.set_targets(win.scan_targets()), mon.scan_now())
)
win.set_discover_requester(
    lambda force=None: disc.request(win.discover_targets(), win.known_ips())
)
mon.start()
win.request_discover()


def report():
    for m in machines:
        print(
            f"  {m.name:8s} ip={m.ip or '(空)':15s} "
            f"disc={str(m.discovered):5s} status={m.status}"
        )
    win.grab().save(
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "shots",
            "discover.png",
        )
    )


QTimer.singleShot(7000, report)
QTimer.singleShot(8000, lambda: (mon.stop(), disc.stop(), win.close(), app.quit()))
app.exec()
