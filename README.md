# VibeCodingLight

VibeCodingLight 是一套把 AI 编程工具状态映射到物理红绿灯的桌面灯控系统。它通过 Claude Code、OpenAI Codex、Cursor 的 hooks 读取当前会话状态，再由后台守护进程驱动 ESP32-C3 和三色灯，让“正在思考、正在执行、等待输入、需要处理”等状态直接显示在桌面硬件上。

当前发布版为 **V3.0**，重点是可交付、可打包、可在普通 Windows 电脑上使用：提供图形化配置台、统一守护进程、Claude/Codex/Cursor 三 Agent 切换、每个 hook 事件的灯效配置、USB 串口灯控、可选 BLE、开机自启和 PyInstaller 打包方案。

项目地址：`jursber/claude-traffic-light`
GitHub：`https://github.com/jursber/claude-traffic-light`

## 当前版本

V3.0 已经从实验脚本整理为一个相对完整的桌面应用项目：

| 能力 | 说明 |
|---|---|
| 多 Agent 支持 | 支持 Claude Code、OpenAI Codex、Cursor，并可在 GUI 中切换当前 Agent |
| Hook 灯效配置 | Claude / Codex / Cursor 分别有独立标签页，可按 hook 事件配置灯效、颜色和优先级 |
| 程序位置校验 | 基础设置中可选择/查找三种 Agent 的本机程序位置，校验通过后才开放对应选项和页签 |
| 统一守护进程 | `unified_daemon` 读取状态文件，合并多会话状态后驱动硬件 |
| 物理灯控 | 默认 USB 串口连接 ESP32-C3，支持扩展灯控协议、亮度、闪烁、呼吸、组合颜色 |
| 试灯调试 | GUI 内置本地试灯、串口连接/断开、发送测试帧 |
| 热生效 | 保存配置后，灯效参数和全局亮度/周期可被运行中的后端读取 |
| Windows 交付 | 支持打包为 `VibeLight.exe`，目标电脑无需安装 Python |

## 硬件

推荐硬件组合：

- ESP32-C3 或同类 ESP32 开发板
- 三色交通灯模块，或红/黄/绿三路 LED
- USB 连接电脑
- 默认波特率：`115200`
- Espressif 原生 USB VID：`0x303A`

固件位于 `arduino/traffic_light/`。协议、接线、亮度调校和排障文档见：

- `docs/VIBELIGHT_PROTOCOL.md`
- `arduino/traffic_light/BLE.md`
- `arduino/traffic_light/TUNING.md`
- `docs/SERIAL_PORT_TROUBLESHOOTING.md`

## 快速使用

### 方式一：使用打包后的桌面程序

1. 下载或复制 `dist/VibeLight/` 文件夹。
2. 双击 `VibeLight.exe` 打开配置台。
3. 在“基础设置”里设置端口、亮度与周期。
4. 在“程序位置”中选择或查找 Claude、Codex、Cursor 的本机位置。
5. 选择当前使用的 Agent。
6. 点击“启动灯控”，或勾选开机启动。
7. 在 Claude Code、Codex 或 Cursor 中正常工作，红绿灯会跟随状态变化。

打包后只有一个主程序 `VibeLight.exe`，它会根据命令行自动扮演不同角色：

| 调用方式 | 作用 |
|---|---|
| `VibeLight.exe` | 打开图形化配置台 |
| `VibeLight.exe daemon-unified` | 作为后台守护进程运行 |
| `VibeLight.exe set-state-unified <state>` | 被 IDE hook 调用，写入状态 |
| `VibeLight.exe switch-agent <agent>` | 切换 Agent 并重写 hook 配置 |

### 方式二：源码运行

```powershell
pip install -r requirements.txt
pip install -e .

pythonw tools\tl_hook_light_gui.py
```

常用命令：

```powershell
python daemon_unified.py
python switch_agent.py status
python switch_agent.py claude
python switch_agent.py codex
python switch_agent.py cursor
python set_state_unified.py thinking --event postToolUse
python -m pytest
```

## 图形化配置台

主 GUI：`tools/tl_hook_light_gui.py`

基础设置页包含：

- Agent 选择、硬件检测、端口刷新、启动灯控、开机自启
- 全局亮度与周期
- Claude / Codex / Cursor 程序位置选择、查找与校验
- 试灯调试
- 使用说明

Claude、Codex、Cursor 三个标签页用于配置各自 hook 事件的灯效。每一行对应一个 hook 事件，可配置：

- 灯效：关闭、常亮、同步闪烁、呼吸
- 颜色：绿、黄、红，可组合
- 优先级：数字越小优先级越高

窗口底部的“保存全部”会同时保存基础设置和三个 Agent 的 hook 灯效配置。

## 工作原理

整体链路如下：

```text
Claude / Codex / Cursor Hook
        ↓
set_state_unified.py 或 VibeLight.exe set-state-unified
        ↓
写入 %LOCALAPPDATA%\Temp\<agent>_tl_states\<session_id>
        ↓
unified_daemon 合并会话状态，选择最高优先级灯效
        ↓
USB 串口或 BLE 发送灯控帧
        ↓
ESP32-C3 控制红 / 黄 / 绿灯
```

配置文件主要包括：

| 文件 | 作用 |
|---|---|
| `active_agent.json` | 当前启用的 Agent，以及各 Agent 的状态目录 |
| `config/tl_hook_light_gui.json` | GUI 保存的端口、亮度、周期、程序位置和 hook 灯效 |
| `~/.claude/settings.json` | Claude Code hook 配置 |
| `~/.codex/hooks.json` | Codex hook 配置 |
| `~/.cursor/hooks.json` | Cursor hook 配置 |

运行期状态、日志和锁文件位于 `%LOCALAPPDATA%\Temp\`。

## 灯光语义

默认语义可以在 GUI 中按事件重新配置。通常建议：

| 状态 | 建议灯效 | 含义 |
|---|---|---|
| `idle` | 红灯常亮 | 等待用户输入 |
| `thinking` | 黄灯闪烁或呼吸 | 模型正在思考 |
| `working` | 绿灯常亮 | 正在执行工具或处理任务 |
| `model` | 绿灯闪烁 | 等待模型返回 |
| `alert` | 红灯闪烁 | 需要确认、授权或处理异常 |
| `off` | 全灭 | 会话结束或不显示 |

多会话同时存在时，守护进程会按优先级选择要显示的灯效。优先级数字越小越靠前。

## 项目结构

| 路径 | 说明 |
|---|---|
| `src/claude_tl/` | V3 核心 Python 包，包含守护进程、状态写入、传输、hook 生成等业务逻辑 |
| `tools/tl_hook_light_gui.py` | 主配置台 GUI |
| `daemon_unified.py`、`set_state_unified.py`、`switch_agent.py` | 兼容源码运行的薄启动器 |
| `config/` | GUI 默认配置与运行配置 |
| `arduino/traffic_light/` | ESP32 固件和硬件说明 |
| `packaging/` | Windows 打包脚本与 PyInstaller spec |
| `tests/` | 自动化测试、硬件冒烟测试、发布验证 |
| `docs/` | 协议、打包、迁移、排障、hook 事件说明 |
| `reports/` | 上线前测试报告 |
| `extras/` | 历史脚本和旧打包方案归档 |

## 打包发布

Windows 打包入口：

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_win.ps1
```

产物：

```text
dist\VibeLight\VibeLight.exe
```

分发时复制整个 `dist/VibeLight/` 文件夹即可。更多说明见 `docs/BUILD_AND_DISTRIBUTE.md`。

当前打包方案已经处理：

- hook 不依赖目标电脑安装 Python
- hook 不依赖 Git Bash
- GUI、daemon、hook 共用同一个 exe
- 开机自启可指向 exe 子命令
- 打包时不把测试、历史归档脚本混入主程序

## 测试与验证

常用测试：

```powershell
python -m pytest
python tests\release_validation.py
```

当前发布验证报告位于 `reports/RELEASE_VALIDATION_REPORT.md`，最近一次上线前验证结果为：

| 检查项 | 结果 |
|---|---|
| 静态结构检查 | PASS |
| Python 编译检查 | PASS |
| pytest 回归 | PASS |
| 端到端自检 | PASS |
| PyInstaller 构建 | PASS |
| exe 冒烟测试 | PASS |

## 常见问题

### 灯不亮

先确认：

1. GUI 中已经启动灯控后台。
2. 端口选择正确。
3. ESP32 固件已经烧录。
4. 当前 Agent 已切换成功。
5. 对应 IDE 已重新加载 hooks。必要时新建会话或重启 IDE。

### 点击“连接”后真实状态不更新

“连接”是本地试灯调试功能，会接管串口。调试结束后点击“断开”，让后台守护进程重新接管串口。

### 访问 COM 端口被拒绝

通常是 Arduino IDE、串口调试助手或另一个程序占用了同一端口。关闭占用程序后刷新端口，仍不行时重新插拔 USB。

### 切换 Agent 后灯效没有变化

切换 Agent 会立即改写后台配置，但某些 IDE 不会立即重载 hook。新建会话或重启该 IDE 通常即可。

更多排障见：

- `docs/TROUBLESHOOTING.md`
- `docs/SERIAL_PORT_TROUBLESHOOTING.md`
- `docs/CODEX_HOOKS_AND_LIGHT_PATHS.md`

## 版本演进

### V1.x：单工具原型

早期版本主要围绕 Claude Code 做状态灯原型，重点验证“IDE hook → 状态文件 → 守护进程 → 物理灯”的基本链路。

### V2.0：多 Agent 与统一守护

V2.0 是一次重要扩展，加入了 Claude / Codex / Cursor 的多 Agent 思路，统一了状态目录和后台守护进程，并沉淀出 `active_agent.json`、`set_state_unified.py`、`daemon_unified.py` 等核心机制。V2.0 已通过 Git 标签 `V2.0` 归档，可用于回看历史实现。

### V3.0：发布版桌面应用

V3.0 的重点是“能交付给别人用”：

- 整理为 `src/claude_tl` Python 包，根目录脚本变为薄启动器
- 新增完整 GUI 配置台
- 支持 Claude、Codex、Cursor 三套 hook 事件独立灯效配置
- 新增程序位置选择、查找、校验和对应 UI 禁用逻辑
- 支持全局亮度、闪烁周期、呼吸周期
- 增强 Windows 串口、PID、锁文件、开机自启稳定性
- 支持 PyInstaller 打包为 `VibeLight.exe`
- 补齐自动化测试、发布验证和报告文档

## License

本仓库当前未声明开源许可证。正式公开发布前，建议根据你的分发目标补充 `LICENSE` 文件。
