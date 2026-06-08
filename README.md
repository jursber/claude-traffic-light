# Claude Code Traffic Light

用硬件红绿灯实时显示 Claude Code 的工作状态。支持多终端并行，优先级显示。

## 灯光状态

| 状态 | 灯光 | 含义 | 优先级 |
|------|------|------|--------|
| alert | 🔴 红灯闪烁 | 需要用户授权 / API 或工具出错 / CC 问你问题 | 1 (最高) |
| thinking | 🟡 黄灯闪烁 | 思考中 | 2 |
| model | 🟢 绿灯闪烁 | 调用模型中，等待 API 响应 | 3 |
| working | 🟢 绿灯常亮 | 拿到回复，正在写代码/执行操作 | 4 |
| idle | 🔴 红灯常亮 | CC 完成回复，等待输入 | 5 |
| off | ⚫ 全灭 | 会话结束 | 6 (最低) |

### 状态流转

```
用户发消息 → thinking(黄闪) → model(绿闪) → working(绿亮) → model(绿闪) → ... → idle(红亮)
```

### 多终端优先级

多个 CC 终端同时运行时，灯显示**优先级最高**的状态。

### 心跳超时

活跃状态（working/thinking/model/alert）超过 60 秒未更新，自动降级为 idle。防止 CC 崩溃后灯永远亮着。

### 断线重连

守护进程检测到串口断开时，自动扫描所有 USB 端口，找到 ESP32C3 后重新连接。换 USB 口或拔插后无需手动干预。

### 全局关灯

SessionEnd hook 写入 `_global_off` 文件，守护进程清除所有状态文件并关灯。确保退出 CC 后灯正确熄灭。

## 硬件

- ESP32C3 开发板
- 三色 LED 模块（绿/黄/红）
- 接线：GPIO0=绿，GPIO1=黄，GPIO2=红（有源低电平）
- 串口自动检测（通过 Espressif USB VID 0x303A）

## 软件架构

```
CC Hook 触发 → set_state.py 写状态文件(带时间戳)
                     ↓
              daemon.py 读取所有 session 文件
                     ↓
              按优先级选最高 + 心跳超时检测
                     ↓
              串口发送 → ESP32C3 点灯
```

### 文件说明

| 文件 | 作用 |
|------|------|
| `config.py` | 自动检测串口 + 状态/优先级/心跳超时配置 |
| `daemon.py` | 串口守护进程，多会话聚合 + 断线重连 |
| `set_state.py` | Hook 调用入口，读 session_id 写状态文件（JSON 格式） |
| `start_daemon.py` | 自动启动守护进程（幂等） |
| `daemon_guard.vbs` | 守护脚本，崩溃自动重启（放在启动文件夹） |
| `install_service.py` | 注册 Windows 计划任务（备用方案） |
| `test_all.py` | 全量测试脚本 |
| `arduino/traffic_light.ino` | ESP32C3 固件 |

## 安装

1. 安装 pyserial：`pip install pyserial`
2. 烧录 `arduino/traffic_light.ino` 到 ESP32C3
3. Arduino IDE 中启用 **Tools → USB CDC On Boot → Enabled**
4. 关闭 Arduino IDE 串口监视器
5. 将 `daemon_guard.vbs` 复制到启动文件夹：
   ```
   %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\
   ```
6. 运行 `python test_all.py` 验证

Hooks 已配置在 `~/.claude/settings.json`，启动 CC 后自动生效。

## 手动控制

```bash
# 启动守护进程
python daemon.py

# 手动切换状态
echo '{"session_id":"test"}' | python set_state.py idle
python set_state.py thinking
python set_state.py alert
```

## 踩坑记录

见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
