# 踩坑记录

开发过程中遇到的问题和解决方案。

## 1. Python 版本冲突

**现象**：`pip install pyserial` 成功，但 `import serial` 报 ModuleNotFoundError。

**原因**：系统装了多个 Python（3.11 和 3.14），`pip` 默认装到了 3.14 的 site-packages，但 `python` 命令解析到 hermes venv 的 3.11。

**解决**：用 `pip3.exe`（hermes venv 目录下）安装：`C:\...\hermes-agent\venv\Scripts\pip3.exe install pyserial`

## 2. 串口打开卡死 / Semaphore Timeout

**现象**：Python 打开 COM3 后 `write()` 卡住，报 "The semaphore timeout period has expired"。

**原因**：ESP32C3 的 **USB CDC On Boot** 默认是 Disabled，USB 虚拟串口功能没启用。

**解决**：Arduino IDE → Tools → USB CDC On Boot → **Enabled**，重新烧录。

## 3. DTR 复位导致灯闪烁即灭

**现象**：Python 发送指令后灯闪一下就灭了，或者完全不亮。

**原因**：`serial.Serial()` 打开串口时会拉高 DTR 信号，触发 ESP32C3 复位。复位后程序重新初始化，之前的指令丢失。

**解决**：打开串口时禁用 DTR：
```python
ser = serial.Serial(port, baud, dsrdtr=False)
ser.dtr = False
ser.rts = False
```

## 4. Arduino IDE 串口监视器占用 COM 口

**现象**：Python 报 PermissionError，无法打开 COM3。

**原因**：Arduino IDE 的串口监视器打开了 COM3，独占端口。

**解决**：关闭 Arduino IDE 串口监视器（关掉窗口即可，不用关 IDE）。

## 5. Hook 延迟过大

**现象**：每次 hook 触发后灯要等几百毫秒才亮。

**原因**：每次 hook 都启动一个新 Python 进程（~300ms 启动时间），加上串口开关耗时。

**解决**：改用守护进程模式。`daemon.py` 常驻后台持有串口连接，hook 只需写一个几字节的状态文件（<1ms）。

## 6. ESP32C3 引脚和电平

**现象**：按文档写的 GPIO2/3/4 不亮。

**原因**：不同开发板引脚定义不同。本项目的板子用 GPIO0/1/2，且 LED 是有源低电平（LOW=亮）。

**解决**：以实际跑通的跑马灯代码为准，确认引脚和电平逻辑后再写控制代码。

## 7. Settings 修改不即时生效

**现象**：修改 `~/.claude/settings.json` 的权限配置后，当前会话不生效。

**原因**：CC 在会话启动时加载配置，运行中不会热更新。

**解决**：修改 settings.json 后需要重启 CC 会话。

## 8. 多终端状态互相覆盖

**现象**：开两个 CC 终端，灯只显示最后写入的那个状态。

**原因**：最初设计用单个状态文件，多终端写同一个文件会互相覆盖。

**解决**：改为每个会话独立的状态文件（`{STATE_DIR}/{session_id}`），守护进程读取所有文件，按优先级显示最高优先级状态。

## 9. PowerShell 不传递 stdin

**现象**：hook 用 `shell: "powershell"` 时，`set_state.py` 读不到 session_id，全部写到 `default` 文件。

**原因**：PowerShell 的 `$input` 变量在命令字符串中不工作。CC 通过 stdin 发送的 JSON 无法传递给 Python。

**解决**：hook 改用 `shell: "bash"`（默认），bash 会自动将 stdin 传递给子进程。

## 10. 守护进程被 CC 退出时杀死

**现象**：`/exit` 退出 CC 后，守护进程也跟着死了。

**原因**：用 `run_in_background` 启动的后台任务会在会话结束时被清理。即使用 `DETACHED_PROCESS` 标志也不生效。

**解决**：用 Windows 任务计划程序（`schtasks`）注册守护进程为登录自启任务，完全独立于 CC。通过 `extras/legacy_windows/install_service.py` 安装。

## 11. S4U 计划任务无法访问 COM 端口

**现象**：计划任务用 `S4U` LogonType 时，守护进程启动后立即崩溃，报 COM 端口权限错误。

**原因**：S4U 登录类型在非交互式会话中运行，无法访问 COM 端口。

**解决**：改用 `InteractiveToken` + `<Hidden>true</Hidden>`，既能在交互式会话中访问 COM 端口，又不显示窗口。但这种方式下，关闭同会话的其他 Python 进程可能连带杀死守护进程。

## 12. 守护进程被其他 Python 进程关闭时连带杀死

**现象**：关闭某个 Python 窗口后，守护进程也跟着死了。

**原因**：Windows 会话管理可能在特定条件下清理同会话的进程。

**解决**：改用启动文件夹（`Startup`）+ VBScript 守护脚本（`daemon_guard.vbs`）。守护脚本循环监控守护进程，崩溃后 3 秒自动重启。比计划任务更可靠。

## 13. AskUserQuestion 显示绿灯而非红灯

**现象**：CC 通过 AskUserQuestion 弹出选择框时，灯显示绿灯常亮（working），而不是红灯闪烁（alert）。

**原因**：AskUserQuestion 也是工具调用，触发 PreToolUse hook 设置 "working" 状态。CC 没有专门的 hook 区分"正在执行工具"和"正在等用户回答"。

**解决**：PreToolUse hook 改用 `auto` 模式，脚本根据 `tool_name` 自动判断：AskUserQuestion → alert，其他工具 → working。

## 14. 换 USB 口后灯不亮

**现象**：ESP32C3 换到另一个 USB 口后，灯不亮了。

**原因**：守护进程启动时连接到固定的 COM 口，换 USB 口后 COM 口号变了，守护进程还连着旧端口。

**解决**：守护进程增加断线重连逻辑。串口写入失败时，自动扫描所有 USB 端口，通过 VID（0x303A）找到 ESP32C3 后重新连接。

## 15. 退出 CC 后灯不灭

**现象**：`/exit` 退出所有 CC 窗口后，红灯依然亮着。

**原因**：SessionEnd hook 没有正确触发，或者 hook 没有传递 session_id，导致状态文件没有被更新为 "off"。

**解决**：
1. `set_state.py` 增加 `_global_off` 机制：当 session_id 为空且状态为 "off" 时，写入 `_global_off` 文件
2. `daemon.py` 检测到 `_global_off` 文件后，清除所有状态文件并关灯
3. 心跳超时机制作为兜底：活跃状态超过 60 秒自动降级为 idle

## 16. 守护进程不发 off 命令

**现象**：状态文件全部删除后，守护进程没有发送 off 命令，灯还亮着。

**原因**：守护进程的 `last_cmd` 变量记录了上次发送的指令。如果上次发送的是 off，删除状态文件后不会重复发送。

**解决**：守护进程启动时强制发送一次当前状态，确保灯的状态与状态文件一致。
