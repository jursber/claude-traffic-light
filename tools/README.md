# 工具脚本

## `vibelight_gui.py`

VibeLight 桌面调试台（Tkinter）：USB 串口与 BLE 发送 **v1 二进制帧** 及旧版 ASCII。

```bash
# 仓库根目录（Windows 推荐 pythonw，避免附着黑色控制台窗口）
pythonw tools/vibelight_gui.py
# 或双击 tools/vibelight_gui.pyw（系统通常用 pythonw 打开 .pyw）
# python.exe 会先 ShowWindow 隐藏控制台再 FreeConsole；仍建议 pythonw / .pyw
python tools/vibelight_gui.py
```

说明：BLE 每次写入在当前实现里使用 `asyncio.run`，点击发送时界面会极短暂阻塞；若需高频连续调光，可后续改为常驻事件循环线程。

**仅用 USB 测呼吸时**：请确认没有 **红绿灯守护进程**（`daemon_unified.py` 等）或其它程序向**同一 COM** 写单字节 `G/g/R/...`，否则固件会切回 Legacy 常亮/闪烁，PROTO 呼吸会停。详见 `arduino/traffic_light/TUNING.md`。

## `tl_hook_light_gui.py`

Hook × 灯光配置台（四 Tab：基础设置 / Claude / Codex / Cursor），含 **第一行 Agent 切换**（异步调用 `switch_agent`，带进度条）。全量 Hook 列表见 **`docs/HOOK_EVENTS_REFERENCE.md`** / `src/claude_tl/hook_light_catalog.py`；配置保存 **`config/tl_hook_light_gui.json`**。串口占用见 **`docs/SERIAL_PORT_TROUBLESHOOTING.md`**（建议拔插 USB、任务管理器或 Process Explorer）。

```bash
# Windows 推荐（无控制台窗口）
pythonw tools/tl_hook_light_gui.py
# 或双击 tools/tl_hook_light_gui.pyw
# python.exe 会先隐藏控制台再脱离；仍推荐 pythonw / .pyw
python tools/tl_hook_light_gui.py
```

**开机启动灯控后台**：本程序写入的是启动文件夹里的 **`VibeCodingLight-unified-daemon.vbs`**（无窗口，不经 `cmd`）。若你机器上仍有旧版同名 **`.bat`**，打开本程序并勾选「开机启动」后会自动升级为 `.vbs`。

## `e2e_selftest.py`

一键端到端自检：**默认在终端询问你灯态**（每步输入 `ok` / `wrong …` / `skip`）；CI 或非交互加 **`--batch`** 跳过目视。

报告 **`reports/e2e_selftest_report.json`**，摘要 **`reports/E2E_MODIFICATION_PLAN.md`**。

```bash
# 交互（需灯与 COM 就绪，按提示回答）
python tools/e2e_selftest.py

# 无人值守（不问你灯）
python tools/e2e_selftest.py --batch
```