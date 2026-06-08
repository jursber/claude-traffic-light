# Claude Code 红绿灯项目 - 迁移教程

本教程指导你将红绿灯项目迁移到新电脑。此教程面向新电脑上的 Claude Code，帮助它理解项目结构并完成部署。

---

## 一、源电脑环境信息（用于排查问题）

### 硬件配置

| 项目 | 详情 |
|------|------|
| **操作系统** | Windows 10 专业版 22H2 (Build 19045) |
| **CPU** | Intel Core i5-7500 @ 3.40GHz (4核4线程) |
| **主板** | ASUS PRIME B250M-A |
| **内存** | 16 GB |
| **BIOS** | American Megatrends 1205 (2018/5/11) |
| **COM 端口** | COM1 (系统默认)，ESP32C3 自动检测 |

### 软件环境

| 项目 | 版本/路径 |
|------|-----------|
| **Python** | 3.11.15 |
| **pyserial** | 3.5 |
| **Python 路径** | `%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe` |
| **pythonw 路径** | `%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\pythonw.exe` |
| **Arduino IDE** | 需要安装（用于烧录 ESP32C3 固件） |

### ESP32C3 硬件信息

| 项目 | 详情 |
|------|------|
| **芯片** | ESP32C3 |
| **USB Vendor ID** | 0x303A (Espressif) |
| **串口波特率** | 115200 |
| **LED 引脚** | GPIO0=绿, GPIO1=黄, GPIO2=红 |
| **电平逻辑** | 有源低电平 (LOW=亮) |

---

## 二、项目文件清单

```
claude_traffic_light/
├── config.py                 # 配置模块（串口检测、状态定义、优先级）
├── daemon.py                 # 核心守护进程（串口通信、状态轮询）
├── daemon_guard.vbs          # VBScript 守护脚本（崩溃自动重启）
├── daemon_service.py         # Windows 服务版本（备用方案）
├── daemon_task.xml           # 计划任务 XML 配置
├── daemon_watchdog.ps1       # PowerShell 看门狗脚本
├── install_daemon_task.bat   # 安装计划任务批处理
├── install_service.py        # 安装 Windows 计划任务脚本
├── install_watchdog.bat      # 安装看门狗批处理
├── install_watchdog.ps1      # 安装看门狗 PowerShell 脚本
├── set_alert_and_defer.py    # PermissionRequest hook 专用脚本
├── set_state.py              # Hook 调用入口（写状态文件）
├── start_daemon.py           # 自动启动守护进程（幂等）
├── start_daemon_hidden.bat   # 隐藏窗口启动批处理
├── start_daemon_hidden.vbs   # 隐藏窗口启动 VBScript
├── test_all.py               # 全量测试脚本
├── README.md                 # 项目说明
├── TROUBLESHOOTING.md        # 踩坑记录
├── MIGRATION_GUIDE.md        # 本迁移教程
├── query                     # 查询任务名
├── start                     # 启动任务名
├── nssm.zip                  # NSSM 工具（用于创建 Windows 服务）
└── arduino/
    └── traffic_light/
        └── traffic_light.ino # ESP32C3 固件
```

---

## 三、迁移步骤

### 步骤 1：安装 Python 环境

1. 安装 Python 3.11 或更高版本
2. 安装 pyserial 库：
   ```bash
   pip install pyserial
   ```

### 步骤 2：烧录 ESP32C3 固件

1. 安装 Arduino IDE
2. 在 Arduino IDE 中安装 ESP32C3 开发板支持
3. 打开 `arduino/traffic_light/traffic_light.ino`
4. **重要**：在 Tools 菜单中启用 `USB CDC On Boot → Enabled`
5. 选择正确的开发板和端口，烧录固件
6. 烧录完成后**关闭 Arduino IDE 的串口监视器**（否则会占用 COM 口）

### 步骤 3：复制项目文件

将整个 `claude_traffic_light` 文件夹复制到新电脑的任意位置，例如：
```
C:\Users\<你的用户名>\.claude\traffic_light\
```

### 步骤 4：修改配置文件中的路径

需要修改以下文件中的硬编码路径：

#### 4.1 `daemon_guard.vbs`

找到第 65-68 行，修改为你的实际路径：
```vbscript
' 守护进程所在的目录
strDir = "C:\Users\<你的用户名>\.claude\traffic_light"

' pythonw.exe 的路径
strPythonW = objShell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\hermes\hermes-agent\venv\Scripts\pythonw.exe"
```

如果没有安装 hermes，改为系统 Python：
```vbscript
strPythonW = "pythonw.exe"
```

#### 4.2 `daemon_watchdog.ps1`

找到第 2-3 行，修改为你的实际路径：
```powershell
$python = "C:\Users\<你的用户名>\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
$workDir = "C:\Users\<你的用户名>\.claude\traffic_light"
```

#### 4.3 `daemon_task.xml`

找到第 36-38 行，修改为你的实际路径：
```xml
<Command>C:\Users\<你的用户名>\AppData\Local\hermes\hermes-agent\venv\Scripts\pythonw.exe</Command>
<Arguments>daemon.py</Arguments>
<WorkingDirectory>C:\Users\<你的用户名>\.claude\traffic_light</WorkingDirectory>
```

#### 4.4 `install_daemon_task.bat`

找到第 3 行，修改为你的实际路径：
```bat
schtasks /Create /TN "ClaudeTrafficLightDaemon" /XML "C:\Users\<你的用户名>\.claude\traffic_light\daemon_task.xml" /F
```

#### 4.5 `install_watchdog.ps1`

找到第 3 行，修改为你的实际路径：
```powershell
$scriptPath = "C:\Users\<你的用户名>\.claude\traffic_light\daemon_watchdog.ps1"
```

#### 4.6 `install_watchdog.bat`

找到第 3 行，修改为你的实际路径：
```bat
schtasks /Create /TN "ClaudeTrafficLightWatchdog" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\Users\<你的用户名>\.claude\traffic_light\daemon_watchdog.ps1" ...
```

### 步骤 5：配置 Claude Code Hooks

在新电脑的 Claude Code 配置文件中添加 hooks。

配置文件位置：
- Windows: `%APPDATA%\Claude\settings.json`
- 或: `~/.claude/settings.json`

在 `settings.json` 中添加以下 hooks 配置（修改路径为你的实际路径）：

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python C:/Users/<你的用户名>/.claude/traffic_light/start_daemon.py",
            "shell": "powershell",
            "timeout": 10
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python C:/Users/<你的用户名>/.claude/traffic_light/set_state.py thinking",
            "shell": "powershell",
            "timeout": 5
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python C:/Users/<你的用户名>/.claude/traffic_light/set_state.py auto",
            "shell": "powershell",
            "timeout": 5
          }
        ]
      }
    ],
    "PostToolBatch": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python C:/Users/<你的用户名>/.claude/traffic_light/set_state.py thinking",
            "shell": "powershell",
            "timeout": 5
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python C:/Users/<你的用户名>/.claude/traffic_light/set_state.py idle",
            "shell": "powershell",
            "timeout": 5
          }
        ]
      }
    ],
    "PermissionRequest": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python C:/Users/<你的用户名>/.claude/traffic_light/set_alert_and_defer.py",
            "shell": "powershell",
            "timeout": 5
          }
        ]
      }
    ],
    "Notification": [
      {
        "matcher": "permission_prompt",
        "hooks": [
          {
            "type": "command",
            "command": "python C:/Users/<你的用户名>/.claude/traffic_light/set_state.py alert",
            "shell": "powershell",
            "timeout": 5
          }
        ]
      }
    ],
    "StopFailure": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python C:/Users/<你的用户名>/.claude/traffic_light/set_state.py alert",
            "shell": "powershell",
            "timeout": 5
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python C:/Users/<你的用户名>/.claude/traffic_light/set_state.py off",
            "shell": "powershell",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

**注意**：路径使用正斜杠 `/` 而不是反斜杠 `\`。

### 步骤 6：安装守护进程（可选但推荐）

有两种方式让守护进程开机自启：

#### 方式 A：VBScript 守护脚本（推荐）

1. 将 `daemon_guard.vbs` 复制到启动文件夹：
   ```
   %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\
   ```
   例如：`C:\Users\<你的用户名>\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\`

2. 双击运行 `daemon_guard.vbs`，守护进程立即启动

#### 方式 B：Windows 计划任务

1. 以管理员身份运行 `install_daemon_task.bat`
2. 守护进程会在每次登录时自动启动

#### 方式 C：看门狗（最可靠）

1. 以管理员身份运行 `install_watchdog.bat`
2. 看门狗每 1 分钟检查一次，如果守护进程崩溃会自动重启

### 步骤 7：验证安装

1. 插入 ESP32C3 开发板
2. 运行测试脚本：
   ```bash
   python test_all.py
   ```
3. 观察灯的变化，确认所有状态都正确

---

## 四、灯光状态说明

| 状态 | 灯光 | 含义 | 优先级 |
|------|------|------|--------|
| alert | 🔴 红灯闪烁 | 需要用户授权 / 出错 / CC 问你问题 | 1 (最高) |
| thinking | 🟡 黄灯闪烁 | 思考中 | 2 |
| model | 🟢 绿灯闪烁 | 调用模型中，等待 API 响应 | 3 |
| working | 🟢 绿灯常亮 | 拿到回复，正在写代码/执行操作 | 4 |
| idle | 🔴 红灯常亮 | CC 完成回复，等待输入 | 5 |
| off | ⚫ 全灭 | 会话结束 | 6 (最低) |

---

## 五、常见问题排查

### 问题 1：灯不亮

**检查清单**：
1. ESP32C3 是否正确连接 USB？
2. Arduino IDE 中是否启用了 `USB CDC On Boot → Enabled`？
3. Arduino IDE 串口监视器是否关闭？
4. 守护进程是否在运行？（检查任务管理器中是否有 `pythonw.exe` 进程）

### 问题 2：串口打开失败

**可能原因**：
- Arduino IDE 串口监视器占用了 COM 口 → 关闭串口监视器
- 其他程序占用了 COM 口 → 检查设备管理器

### 问题 3：Hook 不触发

**检查清单**：
1. `settings.json` 中的路径是否正确？
2. 路径是否使用了正斜杠 `/`？
3. Claude Code 是否重启了？（修改 settings.json 后需要重启）

### 问题 4：守护进程频繁崩溃

**排查步骤**：
1. 查看日志文件：`%LOCALAPPDATA%\Temp\cc_traffic_light_daemon.log`
2. 检查 ESP32C3 是否松动
3. 尝试更换 USB 线缆或 USB 口

### 问题 5：Python 版本冲突

如果系统有多个 Python 版本，确保 hooks 中使用的 `python` 命令指向正确的版本。可以在命令中使用完整路径，例如：
```json
"command": "C:/Python311/python.exe C:/Users/<你的用户名>/.claude/traffic_light/set_state.py thinking"
```

---

## 六、架构原理

```
用户发消息 → CC 触发 UserPromptSubmit hook
                    ↓
           set_state.py 写状态文件 (JSON 格式，带时间戳)
                    ↓
           daemon.py 每 50ms 轮询状态目录
                    ↓
           读取所有 session 的状态文件
                    ↓
           按优先级选出最高优先级状态
                    ↓
           通过串口发送单字符指令给 ESP32C3
                    ↓
           ESP32C3 点亮对应的 LED
```

### 多终端支持

- 每个 CC 终端有独立的 session_id
- 每个终端写自己的状态文件：`{STATE_DIR}/{session_id}`
- 守护进程读取所有文件，按优先级显示最高优先级状态
- 例如：终端 A 在干活（working=4），终端 B 需要授权（alert=1）→ 显示红灯闪烁

### 容错设计

- 守护进程外层无限重启循环，任何异常都不会导致进程退出
- 串口断开自动重连（USB 拔插、系统休眠唤醒）
- 单次循环出错不影响下一次
- 状态文件过期自动清理（30 分钟）
- VBScript 守护脚本崩溃后 3 秒自动重启

---

## 七、手动控制

```bash
# 启动守护进程
python daemon.py

# 手动切换状态
echo '{"session_id":"test"}' | python set_state.py idle
python set_state.py thinking
python set_state.py alert

# 运行全量测试
python test_all.py

# 安装/卸载计划任务
python install_service.py
python install_service.py --uninstall
```

---

## 八、源电脑的 settings.json 完整配置（参考）

源电脑的 Claude Code 配置位于 `C:\Users\Administrator\.claude\settings.json`，其中包含：
- API 配置（env 部分）
- 权限配置（permissions 部分）
- Hooks 配置（hooks 部分）
- 模型配置

迁移时只需要复制 hooks 部分，其他配置根据新电脑的实际情况调整。

---

*本教程基于源电脑：Windows 10 Pro 22H2 / Intel i5-7500 / 16GB RAM / Python 3.11.15 / pyserial 3.5*
