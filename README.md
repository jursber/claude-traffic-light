# Claude Code Traffic Light（V3 布局）

用硬件红绿灯显示 **Claude Code** / **OpenAI Codex** 的工作状态（ESP32-C3 + 三色灯）。  
**V3**：可安装 Python 包 `claude_tl`（源码在 `src/claude_tl`），根目录 `.py` 仅为薄启动器，便于旧 hook 与 VBS 继续工作。

> **小白说明**：仓库结构、Git 标签/分支、与打 exe 的关系见 **[docs/V3_LAYOUT_AND_GIT.md](docs/V3_LAYOUT_AND_GIT.md)**。  
> **V2.0 冻结代码**：Git 标签 **`V2.0`**（可选远程分支 `archive/v2.0`），不要依赖磁盘上的 `.old` 文件夹。

## 目录一览

| 路径 | 作用 |
|------|------|
| `src/claude_tl/` | **唯一业务源码**（守护进程、BLE/串口、set_state、switch_agent） |
| `daemon_unified.py` 等根脚本 | 把 `src/` 加入路径后调用包内逻辑（**不要**在这里写业务） |
| `tests/` | 手动/冒烟测试（不打进 exe） |
| `extras/legacy_windows/` | 旧计划任务/NSSM 等脚本（**不打进**默认 exe） |
| `packaging/pyinstaller/` | PyInstaller 规格，**只收集** `claude_tl` |
| `arduino/` | 固件 `.ino` + `BLE.md` |

## 安装与运行

```bash
pip install -r requirements.txt
# 推荐开发体验（可选）：
pip install -e .
```

- 统一守护进程：`python daemon_unified.py` 或 `python -m claude_tl daemon-unified`
- 切换 agent：`python switch_agent.py claude` / `codex` / `status`
- 手动测试灯：`python tests/test_all.py`（需守护进程已运行）

## 硬件与 BLE（VibeLight）

- 接线、固件、**v1 扩展协议**（PWM / 组合 / 呼吸 / 亮度）：见 `arduino/traffic_light/`、[docs/VIBELIGHT_PROTOCOL.md](docs/VIBELIGHT_PROTOCOL.md)、[arduino/traffic_light/BLE.md](arduino/traffic_light/BLE.md)、[arduino/traffic_light/TUNING.md](arduino/traffic_light/TUNING.md)（USB-only 与守护进程抢串口等排查）、[arduino/traffic_light/DEBUGGING_EXPERIENCE.md](arduino/traffic_light/DEBUGGING_EXPERIENCE.md)（呼吸/PWM 问题与经验备忘）
- 桌面调试台：`python tools/vibelight_gui.py`（[tools/README.md](tools/README.md)）；Hook×灯效配置：`python tools/tl_hook_light_gui.py`（见 [docs/HOOK_EVENTS_REFERENCE.md](docs/HOOK_EVENTS_REFERENCE.md)）
- PC 侧 BLE 冒烟：`python tests/test_ble.py`；守护进程仍用 `set CC_TL_TRANSPORT=ble`（默认设备名 **VibeLight**）

## 打 exe（V3 不被旧文件污染）

见 [packaging/pyinstaller/README.md](packaging/pyinstaller/README.md)。spec 入口为 `packaging/pyinstaller/entry.py`，**仅**分析 `src/claude_tl` 依赖链；`tests/`、`extras/` 不会进入包分析。

## 环境变量（常用）

| 变量 | 作用 |
|------|------|
| `CC_TL_TRANSPORT` | `serial`（默认）或 `ble` |
| `CC_TL_HOME` | `active_agent.json` 所在目录（默认仓库根） |
| `CC_TL_REPO_ROOT` | hook 里写的路径与克隆位置不一致时，指向仓库根 |

## 开机守护（Windows）

将 `daemon_guard_unified.vbs` 放到启动文件夹；脚本已改为**自动使用 vbs 所在目录**为项目根，不再写死 Administrator 路径。请本机安装好 Python，或把 `pythonw` 路径写进 vbs 顶部变量。

## 更多文档

- [UNIFIED_README.md](UNIFIED_README.md) — Claude / Codex 切换
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — 踩坑
- [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) — 迁移说明
- 旧 **install_service** 等：见 `extras/legacy_windows/README.md`
