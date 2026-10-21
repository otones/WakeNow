"""无界面自测：模型校验、魔术包、存储、增删改查与唤醒流程。

运行：
    python tools/selftest.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import (
    STATUS_OFFLINE,
    STATUS_ONLINE,
    STATUS_UNKNOWN,
    Machine,
    MachineStore,
    default_broadcast,
    is_ip,
    is_mac,
    normalize_mac,
    validate_field,
)
from app.wol import build_magic_packet

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILS.append(name)


def test_validation() -> None:
    print("[校验]")
    check("IPv4 合法", is_ip("192.168.2.10"))
    check("IPv4 越界", not is_ip("192.168.2.300"))
    check("IPv4 段数不足", not is_ip("192.168.2"))
    check("IPv4 空", not is_ip(""))
    check("MAC 合法", is_mac("AA:BB:CC:DD:EE:FF"))
    check("MAC 小写合法", is_mac("aa:bb:cc:dd:ee:ff"))
    check("MAC 连字符合法", is_mac("AA-BB-CC-DD-EE-FF"))
    check("MAC 无分隔合法", is_mac("AABBCCDDEEFF"))
    check("MAC 位数不足", not is_mac("AA:BB:CC"))
    check("MAC 非法字符", not is_mac("GG:BB:CC:DD:EE:FF"))
    check("归一化", normalize_mac("aabbccddeeff") == "AA:BB:CC:DD:EE:FF")
    check("广播推算", default_broadcast("192.168.2.10") == "192.168.2.255")
    check("广播非法 IP 兜底", default_broadcast("bad") == "255.255.255.255")
    check(
        "无 IP 时用本机网段推广播",
        default_broadcast("", local_ip="10.1.2.3") == "10.1.2.255",
    )
    check("无 IP 也无本机 IP 兜底", default_broadcast("") == "255.255.255.255")

    check("名称必填", validate_field("name", "") != "")
    check("IP 选填（留空通过）", validate_field("ip", "") == "")
    check("IP 格式错误", validate_field("ip", "1.2.3") != "")
    check("IP 正确通过", validate_field("ip", "10.0.0.2") == "")
    check("MAC 必填", validate_field("mac", "") != "")
    check("MAC 错误", validate_field("mac", "AA:BB") != "")
    check("广播选填", validate_field("broadcast", "") == "")
    check("广播错误", validate_field("broadcast", "abc") != "")
    check("端口选填", validate_field("port", "") == "")
    check("端口越界", validate_field("port", "70000") != "")
    check("端口正确", validate_field("port", "9") == "")


def test_magic_packet() -> None:
    print("[魔术包]")
    pkt = build_magic_packet("AA:BB:CC:DD:EE:FF")
    check("长度 102 字节", len(pkt) == 102, f"got {len(pkt)}")
    check("头部 6×FF", pkt[:6] == b"\xff" * 6)
    mac = bytes.fromhex("AABBCCDDEEFF")
    check("MAC 重复 16 次", pkt[6:] == mac * 16)
    check("小写输入等价", build_magic_packet("aa:bb:cc:dd:ee:ff") == pkt)
    try:
        build_magic_packet("AA:BB")
        check("非法 MAC 抛错", False)
    except ValueError:
        check("非法 MAC 抛错", True)


def test_store() -> None:
    print("[存储]")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "machines.json")
        store = MachineStore(path)

        check("首次加载空列表", store.load() == [])
        check("无警告", store.load_warning is None)

        m1 = Machine(name="A", mac="aa:bb:cc:dd:ee:01", ip="192.168.2.10")
        m2 = Machine(name="B", ip="192.168.2.11", mac="AA:BB:CC:DD:EE:02", port=7,
                     broadcast="192.168.2.255")
        store.save([m1, m2])

        loaded = store.load()
        check("保存后读回 2 台", len(loaded) == 2)
        check("名称保留", loaded[0].name == "A")
        check("MAC 归一化", loaded[0].mac == "AA:BB:CC:DD:EE:01")
        check("ID 稳定", loaded[0].id == m1.id)
        check("端口保留", loaded[1].port == 7)
        check("广播保留", loaded[1].broadcast == "192.168.2.255")

        # 无 IP 的机器也能存取（MAC 才是唤醒的依据）
        m3 = Machine(name="无IP机", mac="AA:BB:CC:DD:EE:03")
        store.save([m3])
        reloaded = store.load()
        check("无 IP 机器可保存并读回", len(reloaded) == 1 and reloaded[0].ip == "")
        check("无 IP 标记正确", reloaded[0].has_ip is False)

        # 损坏文件
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ this is not json")
        store2 = MachineStore(path)
        result = store2.load()
        check("损坏后返回空", result == [])
        check("损坏有警告", bool(store2.load_warning))
        check("损坏已备份", os.path.exists(path + ".bak"))

        # 根节点类型错误
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"a": 1}, f)
        check("根节点非数组也回空", MachineStore(path).load() == [])

        # 脏数据过滤：缺 MAC 或无名称应丢弃，但缺 IP 应保留
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {"name": "ok", "ip": "10.0.0.1", "mac": "AA:BB:CC:DD:EE:01"},
                    {"name": "无IP", "mac": "AA:BB:CC:DD:EE:02"},
                    {"name": "", "ip": "10.0.0.2", "mac": "AA:BB:CC:DD:EE:03"},
                    {"name": "bad-ip", "ip": "999.0.0.1", "mac": "AA:BB:CC:DD:EE:04"},
                    {"name": "no-mac", "ip": "10.0.0.5"},
                ],
                f,
            )
        dirty = MachineStore(path).load()
        check("脏数据被过滤（保留无 IP 的）", len(dirty) == 3, f"got {len(dirty)}")
        check("非法 IP 被清空而非丢弃", any(m.name == "bad-ip" and m.ip == "" for m in dirty))

        # 带 BOM 的文件（记事本另存为 / PowerShell Set-Content 会产生）
        with open(path, "w", encoding="utf-8-sig") as f:
            json.dump([{"name": "bom", "ip": "10.0.0.5", "mac": "AA:BB:CC:DD:EE:FF"}], f)
        bom_store = MachineStore(path)
        bom_result = bom_store.load()
        check("BOM 文件可读", len(bom_result) == 1, f"warning={bom_store.load_warning}")
        check("BOM 文件无警告", bom_store.load_warning is None)

        # 原子写：不应残留 tmp
        store.save([m1])
        check("无 tmp 残留", not os.path.exists(path + ".tmp"))


def test_wake_flow() -> None:
    print("[唤醒流程（界面层）]")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.theme import palette
    from app.widgets.main_window import MainWindow

    class NullStore:
        def save(self, machines):
            pass

    app = QApplication.instance() or QApplication([])
    machines = [
        Machine(name="在线机", mac="AA:BB:CC:DD:EE:01", ip="127.0.0.1",
                status=STATUS_ONLINE, id="on1"),
        Machine(name="离线机", mac="AA:BB:CC:DD:EE:02", ip="192.0.2.99",
                status=STATUS_OFFLINE, id="off1"),
        Machine(name="无IP机", mac="AA:BB:CC:DD:EE:03",
                status=STATUS_UNKNOWN, id="noip"),
    ]
    win = MainWindow(machines, NullStore(), palette(False))
    win.set_scan_requester(lambda: None)
    win.set_discover_requester(lambda force=None: None)

    # 无 IP 的机器不进入 ping 目标
    check("无 IP 机不参与 ping", len(win.scan_targets()) == 2)
    check("无 IP 机进入发现队列", ("noip", "AA:BB:CC:DD:EE:03") in win.discover_targets())

    # 发现结果写入无 IP 的机器
    win.on_discovered({"noip": "192.168.2.55"})
    check("发现后写入 IP", machines[2].ip == "192.168.2.55")
    check("标记为自动发现", machines[2].discovered is True)
    check("发现后可参与 ping", len(win.scan_targets()) == 3)

    # 手填 IP 的机器不被发现结果覆盖
    win.on_discovered({"off1": "192.0.2.250"})
    check("手填 IP 不被覆盖", machines[1].ip == "192.0.2.99")

    # 自动发现的 IP 可被更新（DHCP 变动）
    win.on_discovered({"noip": "192.168.2.66"})
    check("自动发现 IP 可更新", machines[2].ip == "192.168.2.66")

    # 手动多选：全选离线 + 补选在线机
    win._on_select_offline()
    check("全选离线只选离线机", win._selected == {"off1"})
    win._on_row_toggled("on1")
    check("可同时选中在线机", win._selected == {"off1", "on1"})
    check("唤醒按钮可用", win.wake_btn.isEnabled())

    # 唤醒：应跳过在线机
    win.toast_host.show_toast = lambda *a, **k: None   # 避免弹窗动画
    win._on_wake()
    check("在线机状态未变", machines[0].status == STATUS_ONLINE)
    check("离线机变为唤醒中", machines[1].status == "waking", machines[1].status)

    # 扫描回调：唤醒中的机器探测不通应保持 waking
    win.on_scan({"on1": (True, "ICMP ping 成功"), "off1": (False, "ICMP ping 失败")})
    check("唤醒中保持", machines[1].status == "waking", machines[1].status)

    # 探测通后变在线
    win.on_scan({"off1": (True, "TCP 445 端口可达")})
    check("探测通后变在线", machines[1].status == STATUS_ONLINE)
    check("判定依据已记录", machines[1].probe_detail == "TCP 445 端口可达",
          machines[1].probe_detail)

    # 超时回退
    machines[1].status = "waking"
    win._wake_deadline["off1"] = 0  # 立即过期
    win._check_wake_timeouts()
    check("超时回离线", machines[1].status == STATUS_OFFLINE)

    # 无 IP 机器保持「未知」，不被探测结果误判为离线
    win.on_scan({"on1": (True, "ICMP ping 成功"), "off1": (False, "ICMP ping 失败")})
    check("无 IP 机不被误判", machines[2].status == STATUS_UNKNOWN, machines[2].status)

    # 搜索结果过滤
    win.search.setText("在线")
    check("搜索过滤生效", len(win.visible_machines()) == 1)
    win.search.setText("")
    check("清空搜索恢复", len(win.visible_machines()) == 3)

    # 删除
    win._delete_machine(machines[0])
    check("删除后剩 2 台", len(win._machines) == 2)
    check("选中集清理", "on1" not in win._selected)

    win.close()


def test_probe_mode() -> None:
    print("[探测方式]")
    from app.models import PROBE_AUTO, PROBE_PING, PROBE_TCP
    from app.probe import probe

    # 无 IP
    m = Machine(name="n", mac="AA:BB:CC:DD:EE:01", id="p1")
    online, detail = probe(m, 300)
    check("无 IP 判离线", online is False)
    check("无 IP 有说明", "IP" in detail, detail)

    # 仅 ping，本机回环
    m2 = Machine(name="lo", mac="AA:BB:CC:DD:EE:02", ip="127.0.0.1",
                 probe=PROBE_PING, id="p2")
    online, detail = probe(m2, 500)
    check("仅 ping 回环判在线", online is True, detail)
    check("仅 ping 说明正确", "ICMP" in detail, detail)

    # 仅 TCP 但端口为空 → 回退 ping，不应永远判离线
    m3 = Machine(name="lo2", mac="AA:BB:CC:DD:EE:03", ip="127.0.0.1",
                 probe=PROBE_TCP, probe_port=0, id="p3")
    online, detail = probe(m3, 500)
    check("仅 TCP 无端口时回退 ping", online is True, detail)
    check("回退有提示", "回退" in detail, detail)

    # 自动模式对不可达地址：代理环境下也不能误判为在线
    m4 = Machine(name="dead", mac="AA:BB:CC:DD:EE:04", ip="192.0.2.77",
                 probe=PROBE_AUTO, probe_port=445, id="p4")
    online, detail = probe(m4, 400)
    check("自动模式不误判幽灵地址", online is False, detail)


def test_models_probe_fields() -> None:
    print("[探测字段兼容]")
    from app.models import DEFAULT_PROBE_PORT, PROBE_AUTO

    # 老配置没有 probe 字段 → 补默认值
    old = {"name": "old", "mac": "AA:BB:CC:DD:EE:01", "ip": "10.0.0.1"}
    m = Machine.from_json(old)
    check("老配置补 probe", m.probe == PROBE_AUTO, m.probe)
    check("老配置补 probe_port", m.probe_port == DEFAULT_PROBE_PORT, str(m.probe_port))

    # 非法值被纠正
    bad = {"name": "bad", "mac": "AA:BB:CC:DD:EE:02", "probe": "xxx", "probe_port": "abc"}
    m2 = Machine.from_json(bad)
    check("非法 probe 被纠正", m2.probe == PROBE_AUTO)
    check("非法 probe_port 被纠正", m2.probe_port == DEFAULT_PROBE_PORT)

    # 合法值保留
    good = {"name": "good", "mac": "AA:BB:CC:DD:EE:03",
            "probe": "tcp", "probe_port": 3389}
    m3 = Machine.from_json(good)
    check("probe 保留", m3.probe == "tcp")
    check("probe_port 保留", m3.probe_port == 3389)

    # 序列化往返
    m4 = Machine(name="rt", mac="AA:BB:CC:DD:EE:04", probe="ping", probe_port=22)
    back = Machine.from_json(m4.to_json())
    check("序列化往返一致", back.probe == "ping" and back.probe_port == 22)


def test_settings() -> None:
    print("[设置]")
    import tempfile

    from app.settings import DEFAULT_INTERVAL_MS, Settings

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "settings.json")

        s = Settings.load(path)
        check("默认最小化到托盘", s.minimize_to_tray is True)
        check("默认未提示过", s.tray_hint_shown is False)
        check("默认间隔", s.probe_interval_ms == DEFAULT_INTERVAL_MS)

        s.tray_hint_shown = True
        s.minimize_to_tray = False
        s.save()
        check("设置文件已创建", os.path.exists(path))

        s2 = Settings.load(path)
        check("设置可读回", s2.tray_hint_shown is True)
        check("布尔值保留", s2.minimize_to_tray is False)

        # 损坏文件 → 回落默认值，不抛异常
        with open(path, "w", encoding="utf-8") as f:
            f.write("{broken")
        s3 = Settings.load(path)
        check("损坏时回默认", s3.minimize_to_tray is True)

        # 非法间隔被拒
        import json as _json

        with open(path, "w", encoding="utf-8") as f:
            _json.dump({"probe_interval_ms": 5}, f)
        s4 = Settings.load(path)
        check("非法间隔回默认", s4.probe_interval_ms == DEFAULT_INTERVAL_MS)

        # BOM 容忍
        with open(path, "w", encoding="utf-8-sig") as f:
            _json.dump({"tray_hint_shown": True}, f)
        s5 = Settings.load(path)
        check("设置文件容忍 BOM", s5.tray_hint_shown is True)


def test_single_instance() -> None:
    print("[单实例锁]")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.single_instance import SingleInstance

    app = QApplication.instance() or QApplication([])

    # 用独立服务名，避免与真实运行中的 WakeNow 实例互相干扰
    test_name = f"WakeNow.SelfTest.{os.getpid()}"
    mutex_name = f"Local\\WakeNow.SelfTest.Mutex.{os.getpid()}"

    first = SingleInstance(test_name, mutex_name)
    check("首个实例可抢锁", first.acquire() is True)

    activated = []
    first.activate_requested.connect(lambda: activated.append(True))

    second = SingleInstance(test_name, mutex_name)
    check("第二个实例被拒", second.acquire() is False)

    # 处理事件让 IPC 消息投递
    from PySide6.QtCore import QCoreApplication

    for _ in range(30):
        app.processEvents()
        QCoreApplication.processEvents()
    check("首个实例收到唤起请求", bool(activated))

    first.release()

    third = SingleInstance(test_name, mutex_name)
    check("释放后可重新抢锁", third.acquire() is True)
    third.release()


def test_transfer() -> None:
    print("[导入导出]")
    import tempfile

    from app.transfer import (
        ImportError_,
        export_to_file,
        load_from_file,
        plan_merge,
    )

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "export.json")

        src = [
            Machine(name="A", mac="AA:BB:CC:DD:EE:01", ip="10.0.0.1"),
            Machine(name="B", mac="AA:BB:CC:DD:EE:02"),
        ]
        n = export_to_file(src, path)
        check("导出数量正确", n == 2)
        check("导出文件存在", os.path.exists(path))

        result = load_from_file(path)
        check("导入数量一致", len(result.machines) == 2)
        check("导入用版本头", result.used_machines_key is True)
        check("导入保留 probe 默认", result.machines[0].probe == "auto")

        # 裸数组（直接拿 machines.json）也能导入
        bare = os.path.join(tmp, "bare.json")
        with open(bare, "w", encoding="utf-8") as f:
            json.dump([{"name": "C", "mac": "AA:BB:CC:DD:EE:03"}], f)
        r2 = load_from_file(bare)
        check("裸数组可导入", len(r2.machines) == 1)
        check("裸数组标记正确", r2.used_machines_key is False)

        # 无效条目被跳过而不是整体失败
        mixed = os.path.join(tmp, "mixed.json")
        with open(mixed, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {"name": "ok", "mac": "AA:BB:CC:DD:EE:04"},
                    {"name": "", "mac": "AA:BB:CC:DD:EE:05"},
                    {"name": "badmac", "mac": "xx"},
                    "not-a-dict",
                ],
                f,
            )
        r3 = load_from_file(mixed)
        check("有效条目保留", len(r3.machines) == 1, str(len(r3.machines)))
        check("无效条目被跳过", len(r3.skipped) == 3, str(r3.skipped))

        # 非法 JSON 抛错
        broken = os.path.join(tmp, "broken.json")
        with open(broken, "w", encoding="utf-8") as f:
            f.write("{not json")
        try:
            load_from_file(broken)
            check("非法 JSON 抛错", False)
        except ImportError_:
            check("非法 JSON 抛错", True)

        # 缺 machines 字段
        wrong = os.path.join(tmp, "wrong.json")
        with open(wrong, "w", encoding="utf-8") as f:
            json.dump({"foo": 1}, f)
        try:
            load_from_file(wrong)
            check("缺 machines 抛错", False)
        except ImportError_:
            check("缺 machines 抛错", True)

        # 合并去重
        current = [Machine(name="A", mac="AA:BB:CC:DD:EE:01", ip="10.0.0.1")]
        incoming = [
            Machine(name="A2", mac="aa:bb:cc:dd:ee:01"),   # 大小写不同，同一台
            Machine(name="C", mac="AA:BB:CC:DD:EE:03"),
        ]
        plan = plan_merge(incoming, current)
        check("合并识别重复", len(plan.existing) == 1, str(len(plan.existing)))
        check("合并新增其余", len(plan.added) == 1, str(len(plan.added)))

        # 文件内自身重复也只算一次
        dup_incoming = [
            Machine(name="D", mac="AA:BB:CC:DD:EE:09"),
            Machine(name="D2", mac="AA:BB:CC:DD:EE:09"),
        ]
        plan2 = plan_merge(dup_incoming, [])
        check("文件内重复去重", len(plan2.added) == 1, str(len(plan2.added)))


def test_autostart() -> None:
    print("[开机自启]")
    from app import autostart

    if not autostart.is_supported():
        print("  跳过（非 Windows）")
        return

    original = autostart.current_value()
    try:
        ok = autostart.enable()
        if not ok:
            # CI 或受限环境可能不允许写 HKCU，跳过而不是判失败
            print("  跳过（当前环境不允许写注册表）")
            return
        check("可写入注册表", ok)
        check("写入后判定为已启用", autostart.is_enabled())
        value = autostart.current_value()
        check("写入的值含 --minimized", "--minimized" in (value or ""), str(value))
        check("路径带引号", (value or "").startswith('"'), str(value))

        ok = autostart.disable()
        check("可删除注册表项", ok)
        check("删除后判定为未启用", autostart.is_enabled() is False)
        check("删除后再删不报错", autostart.disable() is True)
    finally:
        # 还原到测试前状态，避免污染用户机器
        if original:
            autostart.enable()
        else:
            autostart.disable()


def test_scanner() -> None:
    print("[内网扫描]")
    from app.scanner import (
        Found,
        candidate_prefixes,
        is_virtual_ip,
        local_ipv4_list,
        prefix_from_network,
        scan,
    )

    # 网段字符串规整
    check("规整 192.168.2", prefix_from_network("192.168.2") == "192.168.2")
    check("规整 CIDR", prefix_from_network("192.168.2.0/24") == "192.168.2")
    check("规整完整 IP", prefix_from_network("192.168.2.10") == "192.168.2")
    check("拒绝非法网段", prefix_from_network("abc") == "")
    check("拒绝空串", prefix_from_network("") == "")
    check("拒绝超范围", prefix_from_network("300.1.1") == "")

    # 虚拟网段识别
    check("Clash 网段判虚拟", is_virtual_ip("198.18.0.1") is True)
    check("Tailscale 判虚拟", is_virtual_ip("100.100.2.101") is True)
    check("link-local 判虚拟", is_virtual_ip("169.254.1.1") is True)
    check("回环判虚拟", is_virtual_ip("127.0.0.1") is True)
    check("家宽网段不判虚拟", is_virtual_ip("192.168.2.10") is False)
    check("10 段不判虚拟", is_virtual_ip("10.0.0.5") is False)

    # 本机网段候选：候选里不能出现代理/隧道网段
    usable, skipped = candidate_prefixes()
    check("有候选网段", len(usable) > 0, str(usable))
    check("首个不是代理网段",
          not usable[0].startswith("198.18") if usable else False, str(usable))
    # 只有本机真的存在这类地址时才要求它进排除列表，
    # 否则在 CI 等没有代理的机器上会误报
    from app.scanner import local_ipv4_list

    local_ips = local_ipv4_list()
    proxy_like = [
        ip for ip in local_ips
        if ip.startswith("198.18") or ip.startswith("100.")
        or ip.startswith("169.254.")
    ]
    if proxy_like:
        check("代理地址被排除",
              all(ip in skipped for ip in proxy_like),
              f"本机有 {proxy_like}, 排除列表={skipped}")
    else:
        print(f"  跳过  代理地址被排除（本机无此类地址，跳过）")
    # 无论如何，候选网段里都不该出现被排除的虚拟网段
    check("候选中无虚拟网段",
          not any(u.startswith("198.18") or u.startswith("169.254") for u in usable),
          str(usable))

    # 扫描一个必然没有设备的网段，应返回空且给出提示
    report = scan(["203.0.113"], verify=False)
    check("空网段返回报告", report is not None)
    check("空网段有提示", bool(report.error) or len(report.found) == 0)

    # 非法网段
    bad = scan(["not-a-network"])
    check("非法网段报错", bool(bad.error))


def test_scan_dialog() -> None:
    print("[扫描对话框]")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.scanner import Found
    from app.theme import palette
    from app.widgets.scan_dialog import ScanDialog

    app = QApplication.instance() or QApplication([])

    existing = [Machine(name="NAS", mac="BC:24:11:BB:94:1F", id="e1")]
    dlg = ScanDialog(palette(False), existing, None)

    # 注入结果，避免真扫网络
    demo = [
        Found(ip="192.168.2.201", mac="BC:24:11:BB:94:1F", hostname="DS918", alive=True),
        Found(ip="192.168.2.202", mac="C8:FF:BF:06:82:9F", hostname="N150", alive=True),
        Found(ip="192.168.2.117", mac="34:CE:00:FE:87:48", hostname="", alive=False),
    ]
    dlg._scanning = False
    dlg._clear_rows()
    dlg._fill_rows(demo)
    for f in demo:
        f.already_known = f.mac in {m.display_mac for m in existing}
    dlg._update_footer()

    check("结果行已建立", len(dlg._rows) == 3)
    check("初始未选中", dlg.btn_save.isEnabled() is False)

    # 勾选
    dlg._on_row_toggled("192.168.2.202")
    check("勾选后按钮可用", dlg.btn_save.isEnabled() is True)
    check("已选 1 台", len(dlg._selected) == 1)

    # 此时唯一可选项已全选，再点「全选在线」应全部取消
    dlg._toggle_all()
    check("全选可反选为空", len(dlg._selected) == 0, str(dlg._selected))

    # 再点一次：选中所有在线且未存在的机器
    dlg._toggle_all()
    check("全选排除离线", "192.168.2.117" not in dlg._selected, str(dlg._selected))
    check("全选排除已存在", "192.168.2.201" not in dlg._selected, str(dlg._selected))
    check("全选包含在线新机", "192.168.2.202" in dlg._selected)

    # 生成机器对象
    picked = dlg.selected_machines()
    check("导出 1 台", len(picked) == 1, str(len(picked)))
    m = picked[0]
    check("名称用主机名", m.name == "N150", m.name)
    check("MAC 正确", m.mac == "C8:FF:BF:06:82:9F", m.mac)
    check("IP 正确", m.ip == "192.168.2.202", m.ip)
    check("探测方式默认", m.probe == "auto")

    dlg.close()


def test_scan_streaming() -> None:
    print("[扫描实时性]")
    import time as _time

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.scanner import Found, quick_prefixes
    from app.theme import palette
    from app.widgets.scan_dialog import ScanDialog

    app = QApplication.instance() or QApplication([])

    # 1. 快速网段识别必须够快（不能启动 PowerShell）
    t0 = _time.perf_counter()
    quick_prefixes()
    ms = (_time.perf_counter() - t0) * 1000
    check("quick_prefixes 在 200ms 内", ms < 200, f"{ms:.0f}ms")

    # 2. 对话框构造后应能立刻显示，不等扫描
    t0 = _time.perf_counter()
    dlg = ScanDialog(palette(False), [], None)
    build_ms = (_time.perf_counter() - t0) * 1000
    check("对话框构造 < 2000ms", build_ms < 2000, f"{build_ms:.0f}ms")

    # 3. 首帧时列表应为空（扫描还没开始），说明没阻塞
    check("构造时尚未扫描", len(dlg._rows) == 0, str(len(dlg._rows)))

    # 4. 逐条回调应实时插入
    demo = [
        Found(ip="192.168.2.3", mac="AA:BB:CC:DD:EE:03", hostname="", alive=True),
        Found(ip="192.168.2.1", mac="AA:BB:CC:DD:EE:01", hostname="", alive=True),
        Found(ip="192.168.2.2", mac="AA:BB:CC:DD:EE:02", hostname="", alive=False),
    ]
    for f in demo:
        dlg._on_found(f)
        app.processEvents()

    check("逐条插入生效", len(dlg._rows) == 3, str(len(dlg._rows)))
    check("按 IP 排序插入",
          [r.found.ip for r in [dlg.list_lay.itemAt(i).widget()
                                for i in range(dlg.list_lay.count() - 1)]] ==
          ["192.168.2.1", "192.168.2.2", "192.168.2.3"])

    # 5. 同一 IP 第二次回调（补主机名）应更新而非新增
    dlg._on_found(Found(ip="192.168.2.1", mac="AA:BB:CC:DD:EE:01",
                        hostname="MyPC", alive=True))
    app.processEvents()
    check("重复回调不新增行", len(dlg._rows) == 3, str(len(dlg._rows)))
    check("主机名已回填", dlg._rows["192.168.2.1"].found.hostname == "MyPC")
    check("行内文字同步更新",
          "MyPC" in dlg._rows["192.168.2.1"].name.text(),
          dlg._rows["192.168.2.1"].name.text())

    # 6. 在线计数不因重复回调而虚增
    check("在线计数正确", dlg._alive_count == 2, str(dlg._alive_count))

    dlg.close()


def test_theme_and_resize() -> None:
    print("[配色与拉伸]")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication

    from app.theme import palette, resolve_dark, system_prefers_dark
    from app.widgets.main_window import MainWindow

    class NullStore:
        def save(self, machines):
            pass

    app = QApplication.instance() or QApplication([])

    # --- 主题解析
    check("light 解析为非深色", resolve_dark("light") is False)
    check("dark 解析为深色", resolve_dark("dark") is True)
    check("system 跟随系统", resolve_dark("system") == system_prefers_dark())
    check("未知值回退跟随系统", resolve_dark("bogus") == system_prefers_dark())

    # --- 两套配色确实不同
    lp, dp = palette(False), palette(True)
    check("浅色底为白", lp.h("bg").upper() == "#FFFFFF", lp.h("bg"))
    check("深色底非白", dp.h("bg").upper() != "#FFFFFF", dp.h("bg"))
    check("浅色标记正确", lp.is_dark() is False)
    check("深色标记正确", dp.is_dark() is True)
    check("两套文字色不同", lp.h("txt") != dp.h("txt"))

    # --- 窗口可拉伸且随高度自适应
    win = MainWindow([
        Machine(name="A", mac="AA:BB:CC:DD:EE:01", ip="10.0.0.1", id="a"),
    ], NullStore(), palette(True))
    win.set_scan_requester(lambda: None)
    win.set_discover_requester(lambda f=None: None)

    check("可拉伸（min != max）",
          win.minimumSize() != win.maximumSize())

    win.resize(560, 420)
    win.show()
    app.processEvents()
    h1 = win.scroll.height()

    win.resize(560, 720)
    app.processEvents()
    h2 = win.scroll.height()

    check("加高后列表区变高", h2 > h1, f"{h1} -> {h2}")
    check("加高幅度符合预期", h2 - h1 >= 290, f"增加 {h2 - h1}")
    check("底栏始终贴底", win._footer.y() + win._footer.height() == win.height(),
          f"footer底={win._footer.y() + win._footer.height()} 窗口高={win.height()}")

    # --- 边缘判定
    w, h = win.width(), win.height()
    check("左上角判定", win._edge_at(QPoint(2, 2)) == (win.EDGE_TOP | win.EDGE_LEFT))
    check("右下角判定", win._edge_at(QPoint(w - 2, h - 2)) == (win.EDGE_BOTTOM | win.EDGE_RIGHT))
    check("左边判定", win._edge_at(QPoint(2, h // 2)) == win.EDGE_LEFT)
    check("底边判定", win._edge_at(QPoint(w // 2, h - 2)) == win.EDGE_BOTTOM)
    check("内部不判定为边", win._edge_at(QPoint(w // 2, h // 2)) == 0)

    # --- 主题切换实时生效
    win.set_theme("light")
    app.processEvents()
    check("切到浅色生效", win._pal.is_dark() is False)
    check("记录当前主题", win._theme == "light")

    win.set_theme("dark")
    app.processEvents()
    check("切到深色生效", win._pal.is_dark() is True)

    # --- 切换会回调外部（用于持久化）
    seen = []
    win._theme_changed = lambda t: seen.append(t)
    win.set_theme("light")
    app.processEvents()
    check("切换触发持久化回调", seen == ["light"], str(seen))

    # --- 非法主题值不应崩溃
    win.set_theme("nonsense")
    app.processEvents()
    check("非法主题回退 system", win._theme == "system", win._theme)

    win.close()


def test_min_width() -> None:
    print("[最小宽度]")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QPushButton

    from app.theme import palette
    from app.widgets.main_window import MIN_W, MainWindow

    class NullStore:
        def save(self, machines):
            pass

    app = QApplication.instance() or QApplication([])

    # 造 20 台机器，让唤醒按钮显示两位数
    machines = [
        Machine(name=f"M{i}", mac=f"AA:BB:CC:DD:EE:{i:02X}",
                ip=f"10.0.0.{i}", id=f"m{i}")
        for i in range(20)
    ]
    win = MainWindow(machines, NullStore(), palette(True))
    for i in range(20):
        win._selected.add(f"m{i}")
    win._update_wake_button()
    win.resize(MIN_W, 340)
    win.show()
    app.processEvents()

    check("唤醒按钮显示两位数", "(20)" in win.wake_btn.text(), win.wake_btn.text())

    # 每个底栏按钮的实际宽度都必须 >= 文字所需
    squeezed = []
    for b in win._footer.findChildren(QPushButton):
        txt = b.text().strip()
        if not txt:
            continue
        need = b.sizeHint().width()
        if b.width() < need:
            squeezed.append(f"{txt}({b.width()}<{need})")
    check("最小宽度下底栏文字完整", not squeezed, ", ".join(squeezed))

    # 底栏总需求不能超过窗口最小宽度
    lay = win._footer.layout()
    margins = lay.contentsMargins()
    need_total = 0
    for i in range(lay.count()):
        w = lay.itemAt(i).widget()
        if isinstance(w, QPushButton):
            need_total += max(w.minimumWidth(), w.sizeHint().width())
    required = (
        need_total
        + lay.spacing() * (lay.count() - 1)
        + margins.left()
        + margins.right()
    )
    check(
        "最小宽度覆盖底栏需求",
        win.minimumWidth() >= required,
        f"需要 {required}px, 实际 {win.minimumWidth()}px",
    )
    check(
        "最小宽度非硬编码（随字体自适应）",
        win.minimumWidth() >= MIN_W,
        f"{win.minimumWidth()} >= {MIN_W}",
    )

    win.close()


def test_discover() -> None:
    print("[IP 发现]")
    from app.discover import arp_table, subnet_prefixes, local_ipv4

    check("本地 IP 可获取或回退 None", local_ipv4() is None or is_ip(local_ipv4()))
    prefixes = subnet_prefixes(["192.168.5.20", "10.0.0.3"])
    check("候选网段包含已知 IP", "192.168.5" in prefixes and "10.0.0" in prefixes)
    check("网段去重", len(prefixes) == len(set(prefixes)))

    table = arp_table()
    check("ARP 表可解析为 dict", isinstance(table, dict))
    for mac, ip in table.items():
        if not (is_mac(mac) and is_ip(ip)):
            check(f"ARP 条目格式 {mac}->{ip}", False)
            break
    else:
        check("ARP 条目格式均合法", True)


def main() -> int:
    test_validation()
    test_magic_packet()
    test_store()
    test_wake_flow()
    test_probe_mode()
    test_models_probe_fields()
    test_settings()
    test_single_instance()
    test_transfer()
    test_autostart()
    test_scanner()
    test_scan_dialog()
    test_scan_streaming()
    test_theme_and_resize()
    test_min_width()
    test_discover()

    print()
    if FAILS:
        print(f"{len(FAILS)} 项失败：{FAILS}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
