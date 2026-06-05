# Claude Code Traffic Light

用硬件红绿灯实时显示 Claude Code 的工作状态。

## 灯光状态

| 状态 | 灯光 | 含义 |
|------|------|------|
| idle | 🟢 绿灯常亮 | CC 完成回复，等待输入 |
| thinking | 🟡 黄灯闪烁 | CC 正在调用模型 |
| executing | 🟡 黄灯常亮 | CC 正在执行工具 |
| permission | 🔴 红灯闪烁 | 需要用户授权 |
| error | 🔴 红灯常亮 | API 或工具出错 |
| off | ⚫ 全灭 | 会话结束 |

## 硬件

- ESP32C3 开发板
- 三色 LED 模块（绿/黄/红）
- 接线：GPIO0=绿，GPIO1=黄，GPIO2=红（有源低电平）

## 软件架构

```
CC Hook 触发 → set_state.py 写状态文件 → daemon.py 读取 → 串口发送 → ESP32C3 点灯
```

### 文件说明

| 文件 | 作用 |
|------|------|
| `config.py` | 配置（COM口、波特率、状态定义） |
| `daemon.py` | 串口守护进程，常驻后台 |
| `set_state.py` | Hook 调用入口，写状态文件 |
| `start_daemon.py` | 自动启动守护进程（幂等） |
| `test_all.py` | 全量测试脚本 |
| `arduino/traffic_light.ino` | ESP32C3 固件 |

## 安装

1. 安装 pyserial：`pip install pyserial`
2. 烧录 `arduino/traffic_light.ino` 到 ESP32C3
3. Arduino IDE 中启用 **Tools → USB CDC On Boot → Enabled**
4. 关闭 Arduino IDE 串口监视器
5. 运行 `python test_all.py` 验证

Hooks 已配置在 `~/.claude/settings.json`，启动 CC 后自动生效。

## 手动控制

```bash
# 启动守护进程
python daemon.py

# 手动切换状态
python set_state.py idle
python set_state.py thinking
python set_state.py error
```
