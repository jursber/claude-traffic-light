# 打包与分发（Windows / 任意电脑可用）

本文说明如何把 VibeCodingLight 打包成**绿色 exe**，分发到**没有 Python 的电脑**上也能正常用（硬件太差 / Windows 太旧的情况不在保障范围内）。

---

## 1. 设计：一个 exe 三种角色

打包后只有一个 `VibeLight.exe`，它根据命令行参数自动切换角色：

| 调用方式 | 角色 | 谁来调 |
|---|---|---|
| 双击 / `VibeLight.exe` | 配置台 GUI | 用户 |
| `VibeLight.exe daemon-unified` | 常驻守护进程（读状态、写硬件灯） | GUI / 开机自启 |
| `VibeLight.exe set-state-unified auto` | hook（把 IDE 事件写成状态文件） | Claude / Codex / Cursor |
| `VibeLight.exe switch-agent <claude\|codex\|cursor>` | 切换 Agent + 重写 hook 注册 | GUI |

角色分发在入口最早期完成（`tools/tl_hook_light_gui.py` 顶部 `_maybe_run_cli_subcommand`），在加载 GUI、隐藏控制台之前，因此 hook 进程既不加载 Tk（启动快），也保留干净的 stdin。

> 关键：开发模式（有 Python 源码）与打包模式（frozen）的命令生成统一收敛在 `src/claude_tl/launcher.py`。开发模式生成 `python xxx.py`，打包模式生成 `VibeLight.exe 子命令`。两者由 `sys.frozen` 自动区分，互不影响。

---

## 2. 构建步骤

在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_win.ps1
```

脚本会自动安装 `pyinstaller` + 依赖，按 `packaging/vibelight.spec` 打包，并对产物做一次冒烟测试（`VibeLight.exe switch-agent status`）。

产物：`dist\VibeLight\`（**onedir** 整个文件夹）。分发时把这个文件夹整体拷给用户即可。

---

## 3. 用户在新电脑上的使用流程

1. 解压 `VibeLight` 文件夹到任意位置，双击 `VibeLight.exe` 打开配置台。
2. 选择正在用的 Agent（Claude / Codex / Cursor）——这一步会把 hook 注册写进对应的用户配置：
   - Claude：`~/.claude/settings.json`
   - Codex：`~/.codex/hooks.json`
   - Cursor：`~/.cursor/hooks.json`
   - 注册的命令直接指向 `VibeLight.exe`，**不依赖目标机有 Python，也不依赖 Git Bash**。
3. 点「启动灯控」（或勾选「开机启动」），守护进程会在后台运行。
4. 插上 ESP32（USB），在 IDE 里正常对话，灯会随状态变化。

数据文件（`active_agent.json`、GUI 配置、状态文件锁/日志）：
- `active_agent.json` 与 GUI 配置首次运行时自动生成在 **exe 同目录**（`sys.frozen` 时 `repo_root()` = exe 所在目录）。
- 运行期文件（状态、PID、锁、日志）统一在 `%LOCALAPPDATA%\Temp\`，与是否打包无关。

---

## 4. 已规避的「换电脑就坏」的坑

| 坑 | 处理 |
|---|---|
| hook/守护进程依赖 `python.exe` + `.py` 源文件 | frozen 时改用 `exe 子命令`，见 `launcher.py` |
| Claude/Codex hook 依赖 Git Bash 传 stdin | frozen 时不再设 `shell: "bash"`，IDE 直接把 stdin 管道给 exe |
| 开机自启 `.vbs` 写死 `pythonw daemon_unified.py` | frozen 时改写为 `exe daemon-unified` |
| 硬编码绝对路径 / 盘符 / 用户名 | 源码中本就没有；全部基于 `__file__` / `%LOCALAPPDATA%` / `~` / `sys.executable` |
| ESP32 原生 USB 偶发复位导致写串口失败 | 串口写入失败自动重连重试（`_serial_write_with_retry`） |
| Windows `os.kill` 偶发 PermissionError 误判进程死亡 | 仅在「明确不存在」时清理 PID（`_daemon_process_running`） |
| 守护进程单实例陈旧锁导致起不来 | 无存活 PID 时自动清理陈旧锁后重试（`unified_daemon.acquire_lock`） |

---

## 5. 注意事项 / 取舍

- **控制台**：spec 用 `console=True` 以保证 hook 身份能读 stdin。双击 GUI 时会被 `_win_detach_console_if_any` 立刻隐藏，正常使用看不到黑框；个别机器启动瞬间可能一闪。若要彻底无黑框，可改为「两个 exe」（GUI 用 `console=False`，另出一个 console 的 `cc_tl_hook.exe` 专跑 hook/daemon）。
- **串口驱动**：ESP32 原生 USB（VID 303A）在 Win10/11 通常免驱；若用的是 CP2102/CH340 转串口板，目标机需要对应驱动。
- **杀毒/SmartScreen**：未签名的 PyInstaller exe 可能被 SmartScreen 拦一次，选择「仍要运行」即可；批量分发建议做代码签名。
- **BLE**：默认走 USB 串口；只有设了 `CC_TL_TRANSPORT=ble` 才用蓝牙，需要构建机装了 `bleak` 才会打进包。
- **首次构建**：需要联网安装 PyInstaller；之后离线可重复构建。
