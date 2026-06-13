# 统一红绿灯系统 - 支持 Claude Code 和 OpenAI Codex

本系统支持在 Claude Code 和 OpenAI Codex 之间切换，共享同一套硬件红绿灯。

## 架构设计

```
CC hooks  ──┐
            ├──→ 状态文件 ──→ daemon ──→ ESP32C3
Codex hooks ─┘
```

- **底层（通用）**：daemon + 状态文件 + 串口通信，与 CC/Codex 无关
- **上层（适配）**：各自的 hook 系统，写入同一个状态目录
- **切换机制**：配置文件指定当前激活的 agent

## 文件说明

| 文件 | 作用 |
|------|------|
| `active_agent.json` | 配置文件，指定当前激活的 agent |
| `daemon_unified.py` | 统一守护进程，支持 CC 和 Codex |
| `set_state_unified.py` | 统一状态设置脚本 |
| `start_daemon_unified.py` | 统一守护进程启动器 |
| `daemon_guard_unified.vbs` | 统一守护脚本（开机自启） |
| `switch_agent.py` | Agent 切换脚本 |
| `tests/test_unified.py` | 测试脚本 |

## 使用方法

### 1. 切换到 Claude Code

```bash
python switch_agent.py claude
```

### 2. 切换到 OpenAI Codex

```bash
python switch_agent.py codex
```

### 3. 查看当前状态

```bash
python switch_agent.py status
```

### 4. 测试红绿灯

```bash
python tests/test_unified.py test
```

## 配置文件

### active_agent.json

```json
{
  "active": "claude",
  "agents": {
    "claude": {
      "name": "Claude Code",
      "state_dir": "cc_tl_states",
      "hooks_config": "~/.claude/settings.json"
    },
    "codex": {
      "name": "OpenAI Codex",
      "state_dir": "codex_tl_states",
      "hooks_config": "~/.codex/hooks.json"
    }
  }
}
```

- `active`: 当前激活的 agent（"claude" 或 "codex"）
- `agents`: Agent 配置
  - `state_dir`: 状态文件目录名（相对于 %LOCALAPPDATA%\Temp\）
  - `hooks_config`: Hook 配置文件路径

## Hook 事件映射

| 状态 | Claude Code 事件 | Codex 事件 |
|------|------------------|------------|
| thinking | UserPromptSubmit / PostToolBatch | UserPromptSubmit / PostToolUse |
| working | PreToolUse (auto) | PreToolUse (auto) |
| alert | PermissionRequest / Notification / StopFailure / PreToolUse (auto) | PreToolUse (auto) |
| idle | Stop | Stop |
| off | SessionEnd | SessionEnd |

## 安装步骤

### 1. 复制文件

将整个 `traffic_light` 文件夹复制到 `~/.claude/traffic_light/`

### 2. 配置 Codex hooks

将 `hooks_traffic_light.json` 的内容合并到 `~/.codex/hooks.json`

### 3. 启动守护进程

```bash
# 方式 1：直接启动
python daemon_unified.py

# 方式 2：使用守护脚本（推荐）
cscript daemon_guard_unified.vbs

# 方式 3：安装为计划任务
python extras/legacy_windows/install_service.py
```

### 4. 验证安装

```bash
python tests/test_unified.py test
```

## 切换 Agent

当切换 agent 时，系统会：

1. 禁用当前 agent 的 hooks
2. 启用新 agent 的 hooks
3. 更新配置文件
4. 守护进程自动读取新 agent 的状态目录

## 故障排查

### 1. 灯不亮

- 检查 ESP32C3 是否连接
- 检查守护进程是否运行：`tasklist | grep pythonw`
- 检查日志：`%LOCALAPPDATA%\Temp\cc_traffic_light_daemon.log`

### 2. Hook 不触发

- 检查 hooks 配置文件是否正确
- 检查 Python 路径是否正确
- 重启 CC 或 Codex

### 3. 状态文件残留

- 状态文件超过 30 分钟会自动清理
- 手动清理：删除 `%LOCALAPPDATA%\Temp\cc_tl_states\` 或 `%LOCALAPPDATA%\Temp\codex_tl_states\`

## 备份与回滚

### 备份

```bash
# 备份目录
~/.claude/traffic_light/backup_YYYYMMDD_HHMMSS/
```

### 回滚

```bash
# 恢复备份文件
cp ~/.claude/traffic_light/backup_YYYYMMDD_HHMMSS/* ~/.claude/traffic_light/
```

## 注意事项

1. 切换 agent 后需要重启 CC 或 Codex 才能生效
2. 两个 agent 不能同时使用同一套红绿灯
3. 守护进程会自动读取配置文件，无需重启
4. 状态文件使用 JSON 格式，包含时间戳
