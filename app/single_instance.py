"""单实例锁。

用 Windows 命名互斥体（Named Mutex）判断，而不是命名管道：

- 管道在进程被强杀后会残留，新实例连上去「成功」却没人应答，
  会误判为「已有实例」从而静默退出（这正是本程序曾经一闪而过退出的原因）。
- 互斥体是内核对象，进程退出（含崩溃、强杀）时由系统自动释放，不会残留。

管道只负责「把已有窗口唤到前台」这一件事，且失败不影响正确性。
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

SERVER_NAME = "WakeNow.SingleInstance.v1"
MUTEX_NAME = "Local\\WakeNow.SingleInstance.Mutex.v1"
_MSG_SHOW = b"show"
_TIMEOUT_MS = 400


class SingleInstance(QObject):
    """activate_requested: 收到第二个实例的「请显示窗口」请求。

    name / mutex_name 可自定义，便于测试用独立名字互相隔离。
    """

    activate_requested = Signal()

    def __init__(
        self,
        name: str = SERVER_NAME,
        mutex_name: str = MUTEX_NAME,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._name = name
        self._mutex_name = mutex_name
        self._server: QLocalServer | None = None
        self._handle = None
        self._is_primary = False

    @property
    def is_primary(self) -> bool:
        return self._is_primary

    # ---------------------------------------------------------------- 抢锁
    def acquire(self) -> bool:
        """True = 本进程是首个实例；False = 已有实例在跑（已请求它显示窗口）。"""
        if not self._create_mutex():
            # 已有实例：尽力通知它把窗口弄到前台，然后本进程退出
            self._notify_existing()
            return False

        self._start_server()
        self._is_primary = True
        return True

    def _create_mutex(self) -> bool:
        """创建命名互斥体。返回 True 表示本次是第一个创建者。

        注意：CreateMutex 无论是否已存在都会返回有效句柄。非首个实例拿到
        句柄后必须立即关闭，否则它会一直持有这个内核对象，导致首个实例
        退出后锁仍被占用（后续实例永远抢不到）。
        """
        if sys.platform != "win32":
            return True
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            create = kernel32.CreateMutexW
            create.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
            create.restype = wintypes.HANDLE
            close = kernel32.CloseHandle
            close.argtypes = [wintypes.HANDLE]
            close.restype = wintypes.BOOL

            ERROR_ALREADY_EXISTS = 183
            ctypes.set_last_error(0)
            handle = create(None, False, self._mutex_name)
            err = ctypes.get_last_error()
            if not handle:
                return True   # 创建失败时不该阻止启动

            if err == ERROR_ALREADY_EXISTS:
                # 已有实例持有：立刻释放我们这份多余引用
                close(handle)
                return False

            # 我们是首个创建者，保留句柄直到 release()
            self._handle = handle
            return True
        except Exception:
            return True

    # ---------------------------------------------------------------- 管道
    def _start_server(self) -> None:
        """开启管道服务，用于接收第二个实例的「显示窗口」请求。"""
        self._server = QLocalServer(self)
        QLocalServer.removeServer(self._name)
        if not self._server.listen(self._name):
            # 起不来只是收不到唤起请求，不影响程序本身运行
            self._server = None
            return
        self._server.newConnection.connect(self._on_new_connection)

    def _notify_existing(self) -> None:
        """通知已有实例显示窗口。

        刚建立连接时管道缓冲可能还没就绪，立即 write 会失败
        （bytesWritten 返回 False）。需要处理事件循环让连接完成握手。
        """
        from PySide6.QtCore import QCoreApplication

        sock = QLocalSocket()
        sock.connectToServer(self._name)
        if not sock.waitForConnected(_TIMEOUT_MS):
            sock.abort()
            return
        try:
            # 让连接状态真正就绪
            for _ in range(3):
                QCoreApplication.processEvents()
            sock.write(_MSG_SHOW)
            sock.flush()
            if not sock.waitForBytesWritten(_TIMEOUT_MS):
                # 再试一次：等事件循环推进后重写
                QCoreApplication.processEvents()
                sock.write(_MSG_SHOW)
                sock.flush()
                sock.waitForBytesWritten(_TIMEOUT_MS)
        except Exception:
            pass
        finally:
            sock.disconnectFromServer()

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            conn = self._server.nextPendingConnection()
            if conn is None:
                break
            conn.readyRead.connect(lambda c=conn: self._read(c))
            conn.disconnected.connect(conn.deleteLater)

    def _read(self, conn: QLocalSocket) -> None:
        try:
            data = bytes(conn.readAll())
        except Exception:
            return
        if _MSG_SHOW in data:
            self.activate_requested.emit()

    # ---------------------------------------------------------------- 释放
    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(self._name)
            self._server = None
        if self._handle is not None:
            try:
                import ctypes
                from ctypes import wintypes

                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                close = kernel32.CloseHandle
                close.argtypes = [wintypes.HANDLE]
                close.restype = wintypes.BOOL
                close(self._handle)
            except Exception:
                pass
            self._handle = None
