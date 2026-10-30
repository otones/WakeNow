# WakeNow 项目交接文档

> 面向：接手本项目的其他 AI / 开发者
> 生成时间：2026-10-30 · 仓库：https://github.com/otones/WakeNow
> 本文档所有数字均经代码实测核对，非凭记忆

---

## 一、一句话概述

**WakeNow** 是 Windows 局域网唤醒（Wake-on-LAN）桌面工具。双击运行即弹出机器列表，实时区分在线/离线，勾选后一键批量唤醒。Python 3.12 + PySide6 实现，打包为单文件 exe，免安装、免管理员权限。

**当前版本**：v1.2.0（GitHub Release 已发布）
**代码规模**：29 个 Python 文件，6696 行
**测试**：196 项无界面自测，全通过
**产物**：`dist/WakeNow.exe` 44.9 MB

---

## 二、为什么做这个项目（决策背景）

### 2.1 先调研了现成方案

调研结论：**没有完全匹配需求的开源项目**。

| 项目 | 为什么不直接用 |
|---|---|
| [basildane/WakeOnLAN](https://github.com/basildane/WakeOnLAN) | VB.NET/WinForms，技术栈老旧，功能远超「小工具」定位 |
| [nashaofu/wol](https://github.com/nashaofu/wol) | Rust + Web 前端，是本地 Web 服务而非弹窗 GUI，且逐台唤醒不支持批量 |
| Easy WOL | UWP 闭源商店应用，不支持多选批量 |

因此自研。核心逻辑（魔术包 + 探测）实现量不大，自己写更可控。

### 2.2 三个关键产品决策（含理由，改动前请先理解）

**决策 A：IP 字段改为选填（最重要）**

- **理由**：WOL 魔术包是二层广播帧（`6×0xFF + MAC×16`），**与 IP 毫无关系**。IP 在本工具里唯一用途是 ping/TCP 探测在线状态。而 DHCP 分配的 IP 会变，强制填写没有道理。
- **实现**：MAC 成为唯一必填项。IP 留空时通过 ARP 表反查 MAC 的当前 IP 并自动填充，IP 变更自动跟随。
- **关键细节**：发现到的 IP 会**立即持久化**为「上次已知地址」。因为机器关机后 ARP 表项会消失，靠这条记录才能正确显示「离线」而非「未知」。
- **手填 IP 优先级更高**，不被自动发现覆盖。

**决策 B：TCP 探测默认开启，默认端口 445**

- **理由**：很多 Windows 机器开了防火墙禁 ping。纯 ICMP 会把这类机器误判为离线，导致「全选离线 → 唤醒」发出一堆无意义的魔术包。
- **实现**：三档探测方式 `auto` / `ping` / `tcp`，默认 `auto`（ping 优先，失败再试 TCP）。
- **445 的选择理由**：Windows 默认监听 SMB，命中率最高；比 3389（RDP 需手动开）、22（仅 Linux）、80/443（不一定有 Web 服务）可靠。

**决策 C：× 按钮隐藏到托盘，而非退出**

- **理由**：常驻工具定位，后台持续探测。
- **保护**：首次点 × 弹一次气泡提示（`settings.tray_hint_shown` 记一次）；托盘菜单「退出」是唯一彻底退出路径。
- **降级**：系统托盘不可用时，× 自动退回「直接退出」。

### 2.3 明确不做的事

远程关机/重启、跨公网唤醒、多用户/同步、移动端、v1 阶段的定时唤醒。

---

## 三、架构与模块职责

```
main.py                    入口：QApplication、主题、各子系统装配
app/
  paths.py        21 行    数据文件路径（兼容 PyInstaller 的 _MEIPASS）
  models.py      201 行    Machine 实体 + 字段校验 + MachineStore（JSON 持久化）
  settings.py     72 行    本机偏好 settings.json（与用户数据分离）
  wol.py          31 行    魔术包构造与 UDP 广播发送
  probe.py       108 行    在线判定：ICMP ping + TCP，含透明代理干扰自检
  scanner.py     354 行    局域网扫描：网段识别、ARP 探测、并发存活验证
  discover.py    100 行    MAC → IP 自动发现（ARP 反查）
  monitor.py     171 行    后台探测线程 + ARP 发现线程
  single_instance.py 161行 单实例锁（命名互斥体 + 管道通知）
  tray.py        105 行    托盘图标与右键菜单
  autostart.py   110 行    开机自启（HKCU 注册表读写）
  transfer.py    122 行    导入导出与合并策略
  theme.py       363 行    设计令牌与 QSS（浅/深双主题）
  icons.py       159 行    内嵌 SVG 图标渲染（DPI 自适应）
  widgets/
    main_window.py   1391 行  主窗口（最大文件，含布局、排序、唤醒、菜单）
    machine_row.py    319 行  列表行 + 状态点
    checkbox.py       120 行  自绘复选框（含混合态）
    dialogs.py        402 行  添加/编辑对话框（含探测方式下拉）
    scan_dialog.py    536 行  扫描内网对话框
    import_dialog.py  242 行  导入策略对话框（自绘单选钮）
    toast.py          139 行  Toast 轻提示
build.py        84 行    PyInstaller 打包脚本
tools/
  selftest.py   897 行    196 项无界面自测
  shot.py       139 行    离屏截图（渲染各状态到 shots/）
  demo_discover.py 66 行  实网验证 IP 发现
  make_icon.py   94 行    生成多尺寸 ico
```

### 3.1 线程模型

- **主线程**：Qt 事件循环，UI 全部在这里
- **探测线程**（`monitor.py`）：ThreadPoolExecutor(8) 并发探测，每 3000ms 一轮，结果经 Signal 回主线程
- **发现线程**（`monitor.py`）：ARP 扫描，按需触发
- **扫描线程**（`scan_dialog.py`）：用户点「扫描内网」时启动，支持中途取消

跨线程一律走 Qt Signal/Slot，**不要**在 worker 里碰 UI 对象。

### 3.2 数据文件（都在 exe 同目录）

| 文件 | 性质 | 是否入库 |
|---|---|---|
| `machines.json` | 用户数据（机器列表），要备份/迁移 | ❌ 含隐私 |
| `settings.json` | 本机偏好（主题、托盘提示状态等） | ❌ 机器相关 |

拆分理由：前者要能导入导出，后者不该跟着走。

---

## 四、必须知道的关键实现细节（踩过的坑）

这一节是本项目的「血泪史」，改代码前务必读完。

### 4.1 【高危】TCP 探测必须用 `probe.tcp_reachable`，不能用裸 connect

本机若装了 Clash / Surge 这类 TUN 代理，**任意地址任意端口的 TCP connect 都会「成功」**（代理伪造）。直接看 `connect_ex()` 返回值会把不存在的机器全判在线。

**对策**（`app/probe.py`）：连上目标端口后，再连一个几乎不可能被监听的对照端口 `_SENTINEL_PORT = 54321`。

- 对照端口也「通」→ 判定为代理劫持，结果不可信，返回 False
- 对照端口不通 → 目标端口通就是真通

实测证据（开发机有 Clash）：

```
192.168.2.250（不存在）原始=True  自检后=False ✓
192.0.2.77（不存在）   原始=True  自检后=False ✓
192.168.2.100（真实）  原始=True  自检后=True  ✓
```

**历史教训**：这个 bug 修过一次（`probe.py`），但扫描模块自己又实现了一遍裸 connect，导致复发。**任何新增的 TCP 探测都必须复用 `tcp_reachable`**。

### 4.2 【高危】单实例锁用命名互斥体，不要改回管道

原本用 `QLocalServer` 命名管道判断。问题：**进程被强杀/崩溃时管道残留**，新实例「连接成功」但没有进程应答，会误判「已有实例」而静默退出——表现为**双击一闪而过、没有任何报错**。

**当前实现**（`app/single_instance.py`）：

- **主判定**：命名互斥体 `Local\WakeNow.SingleInstance.Mutex.v1`。内核对象，进程退出（含崩溃）时系统自动回收，**不会残留**。
- **辅助**：管道只用来「把已有窗口唤到前台」，失败不影响启动。
- **关键**：`CreateMutex` 无论是否已存在都返回句柄。**非首个实例拿到句柄后必须立即 `CloseHandle`**，否则它会一直持有内核对象，导致首个实例退出后锁仍被占用（后续永远起不来）。这里出过 bug。

### 4.3 【高危】图标必须按真实 DPI 渲染

原实现把 `devicePixelRatio` 硬编码为 `2.0`。在 125% 缩放屏（如开发机 2560×1440 @125%）下，Qt 需要在 17.5px 的物理区域画 28px 像素图，**图标被裁掉边缘**。

**对策**（`app/icons.py`）：

- 读 `screen.devicePixelRatio()`，不写死
- 同一图标按 1.0 / 1.25 / 1.5 / 2.0 / 3.0 多档各备一张，交给 Qt 挑
- **不要用 `.scaled()`**——它会把 devicePixelRatio 重置为 1，同样导致模糊

**任务栏图标**：`--icon` 写入 exe 资源的是单尺寸压缩图，任务栏取小尺寸时会被缩得发虚。对策是把 `assets/wakenow.ico`（16~256 共 7 档）用 `--add-data` 一起打包，运行时从打包资源加载。

### 4.4 【高危】最小窗口宽度必须动态计算

底栏 6 个按钮 + 间距 + 边距的实际需求约 **629px**（125% DPI 下 653px，offscreen 字体下 700px）。硬编码任何单一数字，都会在另一种字体环境下失准，导致**按钮文字被截断**。

**对策**（`main_window.py::_apply_footer_min_width`）：按各按钮真实 `sizeHint()` 求和，且**必须在 QSS 应用之后**再算一次（样式表会改变内边距，早算偏小）。

### 4.5 对话框是独立顶层窗口，样式表要各自挂

主窗口的 QSS **不会**被对话框继承。`MachineDialog` 和 `ImportDialog` 都在构造函数里自己 `setStyleSheet(build_qss(pal))`。

同时**不要**把 QSS 挂到 `QApplication` 全局——因为测试工具要在同一进程里同时渲染深、浅两套主题，全局只能挂一套。

### 4.6 JSON 读取必须用 `utf-8-sig`

记事本、PowerShell `Set-Content` 都可能写入 BOM。用 `encoding="utf-8"` 会在第一个字节就抛异常，导致整个配置被丢弃、程序以空列表启动。

### 4.7 无边框窗口的拉伸要自己实现

`FramelessWindowHint` 窗口没有系统拉伸把手。`main_window.py` 里实现了边缘判定（`_edge_at`）、8 方向光标切换（`_cursor_for_edge`）、拖拽改尺寸（`mouseMoveEvent`），并已做 `max(min_w, ...)` 保护。

### 4.8 Qt QSS 的若干限制（踩过）

| 想做的事 | 结果 | 实际做法 |
|---|---|---|
| `::down-arrow` 用 CSS 三角画下拉箭头 | 渲染成小方块 | 自绘 `ProbeCombo` 画 chevron |
| `::indicator` 画圆形单选钮 | 圆角不生效，变方块 | 自绘 `RadioDot` 控件 |
| `filter: brightness()` | Qt 不支持，日志报 Unknown property | 去掉，用颜色变化代替 |
| `padding-left` 手动留位给搜索图标 | 与图标位置难对齐 | 改用 `QLineEdit.addAction(..., LeadingPosition)` |

---

## 五、测试体系

### 5.1 运行方式

```bash
.venv\Scripts\python tools\selftest.py
```

无界面（`QT_QPA_PLATFORM=offscreen`），**196 项断言**，约 2 秒跑完。

### 5.2 覆盖范围（16 个测试函数）

| 函数 | 覆盖内容 |
|---|---|
| `test_validation` | IP/MAC/端口/广播地址校验 |
| `test_magic_packet` | 魔术包字节结构（102 字节、6×FF、MAC×16） |
| `test_store` | JSON 读写、BOM 兼容、损坏备份、脏数据过滤、原子写 |
| `test_wake_flow` | 唤醒状态机（跳过在线、唤醒中保持、超时回退） |
| `test_probe_mode` | 三种探测方式、无端口回退、代理不误判 |
| `test_models_probe_fields` | 老配置兼容（缺 probe 字段补默认值） |
| `test_settings` | 设置读写、损坏回默认、非法值拒绝 |
| `test_single_instance` | 首实例抢锁、次实例被拒、唤起信号、释放后重抢 |
| `test_transfer` | 导出/导入、裸数组兼容、逐条容错、合并去重 |
| `test_autostart` | 注册表写入/删除/回读（无权限时跳过而非失败） |
| `test_scanner` | 网段规整、虚拟网段识别、空网段处理 |
| `test_scan_dialog` | 结果行、勾选、全选排除已存在 |
| `test_scan_streaming` | 逐条插入、排序、重复回调不新增行、主机名回填 |
| `test_theme_and_resize` | 主题解析、两套配色差异、边缘判定、拉伸自适应 |
| `test_min_width` | 最小宽度覆盖底栏需求、文字不截断 |
| `test_discover` | ARP 表解析、网段去重 |

### 5.3 测试环境依赖（重要）

有 3 处测试依赖真实环境，已做「优雅跳过」：

- **注册表**：`test_autostart` 写不进去时打印「跳过」而非 FAIL
- **代理网段**：`test_scanner` 只在「本机确实存在 198.18/100./169.254 地址」时才校验排除列表
- **命名互斥体**：`test_single_instance` 用带 PID 的独立名字，避免与真实运行实例冲突

**CI 首次因为第 2 点失败过**（GitHub runner 没有 Clash，排除列表为空，断言 `代理地址被排除 []` 失败）。新增测试时务必注意**不要假设开发机的特殊环境**。

### 5.4 截图工具

```bash
.venv\Scripts\python tools\shot.py    # 渲染各状态到 shots/
```

依赖 `QT_QPA_PLATFORM=windows`（offscreen 无字体，中文会显示成方块）。

---

## 六、构建与发布

### 6.1 本地构建

```bash
.venv\Scripts\python tools\make_icon.py   # 生成 assets/wakenow.ico
.venv\Scripts\python build.py             # 产出 dist/WakeNow.exe
```

### 6.2 CI（GitHub Actions）

配置：`.github/workflows/build.yml`

```yaml
test job   → windows-latest 跑 196 项自测
build job  → 依赖 test 通过才打包
           → 校验产物体积（<20MB 视为不完整，直接 fail）
           → 上传 artifact（保留 30 天）
           → 创建 Release 并附 exe
```

**触发方式**：

- 打 tag（`v*`）→ 自动发布
- 手动 `workflow_dispatch` → 可指定版本号，留空用日期+流水号

**发版流程**：

```bash
git tag v1.3.0
git push origin v1.3.0
```

### 6.3 已发布版本

- v1.2.0：https://github.com/otones/WakeNow/releases/tag/v1.2.0
- CI 实测：两个 job 全绿，产物下载后验证可正常启动（3 秒出窗口）

---

## 七、当前状态与已知边界

### 7.1 完成度

| 功能 | 状态 |
|---|---|
| 机器列表（名称/MAC/IP、搜索、排序） | ✅ |
| 双路探测（ping + TCP，含代理自检） | ✅ |
| 多选批量唤醒 + 唤醒中状态跟踪 | ✅ |
| MAC → IP 自动发现（ARP 反查） | ✅ |
| 扫描内网（边扫边显示） | ✅ |
| 托盘常驻 / 单实例 / 开机自启 | ✅ |
| 导入导出（合并/替换策略） | ✅ |
| 浅色/深色主题切换 | ✅ |
| 窗口边缘拉伸 | ✅ |
| CI 自动打包发布 | ✅ |

### 7.2 已知边界（不是 bug，是设计约束）

- **扫描只能发现开机的设备**：关机机器不在 ARP 表，扫不到，需手动添加 MAC
- **Win11 托盘图标默认收进溢出区**：系统策略，用户可在「任务栏设置」里固定
- **WOL 有前置条件**：目标机需开 BIOS WOL、网卡允许幻数据包、关闭快速启动、用有线网卡（README 有详细说明）

### 7.3 环境相关的坑（交接必读）

**Smart App Control（SAC）**：开发机曾因 Windows SAC 拦截未签名 exe 导致 `WakeNow.exe` 无法启动，报错 `An Application Control policy has blocked this file`。

- SAC 判定：云端信誉 → 无结论则看证书是否由「受信任根证书计划」的 CA 签发
- **自签名证书无效**（官方明确：必须是 trusted provider 签发的）
- 每次重新打包产生新哈希，对 SAC 都是「全新文件」，会重新触发拦截
- 开发机最终选择**关闭 SAC**（Windows 安全中心 → 应用和浏览器控制 → Smart App Control）
- **若接手机器出现同样问题，优先排查此项**

**透明代理**：见 4.1，会让所有 TCP 连接"成功"。

---

## 八、给接手者的建议顺序

1. **先读** `README.md`（用户视角）→ 本文档（开发视角）→ `PRD.md` + `DESIGN-v1.2.md`（需求与决策）
2. **先跑** `tools/selftest.py`，确认 196 项全过（这是健康基线）
3. **先跑** `python main.py`，亲手操作一遍：扫描内网 → 保存 → 唤醒 → 切主题 → 拉窗口
4. **改代码前**务必读第 4 节，尤其是 4.1 / 4.2 / 4.3 这三条高危项
5. **加测试时**注意第 5.3 条，不要假设开发机特殊环境（如代理、特定网段）

### 可扩展方向（未做，不冲突现有架构）

- 定时唤醒（类似计划任务）
- 托盘图标动态角标（有机器唤醒中时显示小点）
- 主题手动切换已实现，`settings.json` 的 `theme` 字段可扩展更多
- Release 附 SHA256 校验值

---

## 九、参考资料

- 仓库：https://github.com/otones/WakeNow
- Release：https://github.com/otones/WakeNow/releases
- 设计文档：`PRD.md`（产品需求）、`DESIGN-v1.2.md`（v1.2 功能设计）、`ui-design.html`（可交互 UI 原型）
- Wake-on-LAN 原理：[Wikipedia](https://en.wikipedia.org/wiki/Wake-on-LAN)
- SAC 官方说明：[FAQ](https://support.microsoft.com/en-us/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions) · [Code signing](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control)
