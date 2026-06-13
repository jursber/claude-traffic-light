# 工具脚本

## `vibelight_gui.py`

VibeLight 桌面调试台（Tkinter）：USB 串口与 BLE 发送 **v1 二进制帧** 及旧版 ASCII。

```bash
# 仓库根目录
python tools/vibelight_gui.py
```

说明：BLE 每次写入在当前实现里使用 `asyncio.run`，点击发送时界面会极短暂阻塞；若需高频连续调光，可后续改为常驻事件循环线程。

**仅用 USB 测呼吸时**：请确认没有 **红绿灯守护进程**（`daemon_unified.py` 等）或其它程序向**同一 COM** 写单字节 `G/g/R/...`，否则固件会切回 Legacy 常亮/闪烁，PROTO 呼吸会停。详见 `arduino/traffic_light/TUNING.md`。

## `tl_hook_light_gui.py`

Hook × 灯光配置台（三 Tab：基础设置 / Claude / Codex），含 **第一行 Claude↔Codex 切换**（异步调用 `switch_agent`，带进度条）。全量 Hook 列表见 **`docs/HOOK_EVENTS_REFERENCE.md`** / `src/claude_tl/hook_light_catalog.py`；配置保存 **`config/tl_hook_light_gui.json`**。

```bash
python tools/tl_hook_light_gui.py
```
