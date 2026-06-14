# 统一红绿灯系统 - 支持 Claude Code、OpenAI Codex 与 Cursor

本系统支持在 Claude Code、OpenAI Codex 与 Cursor 之间切换，共享同一套硬件红绿灯。

## 架构设计

```
CC hooks   ──┐
Codex hooks ├──→ 状态文件 ──→ daemon ──→ ESP32C3
Cursor hooks ┘
```

- **底层（通用）**：daemon + 状态文件 + 串口通信，与 CC/Codex/Cursor 无关
- **上层（适配）**：各自的 hook 系统，写入当前 agent 对应的状态目录
- **切换机制**：配置文件指定当前激活的 agent

## 文件说明

| 文件 | 作用 |
|------|------|
| `active_agent.json` | 配置文件，指定当前激活的 agent |
| `daemon_unified.py` | 统一守护进程，支持 CC、Codex、Cursor |
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

### 3. 切换到 Cursor

```bash
python switch_agent.py cursor
```

### 4. 查看当前状态

```bash
python switch_agent.py status
```

### 5. 测试红绿灯

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
    },
    "cursor": {
      "name": "Cursor",
      "state_dir": "cursor_tl_states",
      "hooks_config": "~/.cursor/hooks.json"
    }
  }
}
```

- `active`: 当前激活的 agent（`"claude"`、`"codex"` 或 `"cursor"`）
- `agents`: Agent 配置
  - `state_dir`: 状态文件目录名（相对于 %LOCALAPPDATA%\Temp\）
  - `hooks_config`: Hook 配置文件路径

## Hook 事件映射

> **全量事件名与默认接线**以 **`docs/HOOK_EVENTS_REFERENCE.md`** 与 **`src/claude_tl/hook_light_catalog.py`** 为准（Claude 官方文档约 30 个生命周期事件；Codex 以 OpenAI 文档为准；Cursor 以 [cursor.com/docs/hooks](https://cursor.com/docs/hooks) 为准）。下表为**状态语义**与**代表性事件**的简图，便于对照守护进程优先级。

| 状态 | Claude Code（代表性事件） | Codex（代表性事件） | Cursor（代表性事件） |
|------|--------------------------|----------------------|----------------------|
| thinking | `UserPromptSubmit` / `PostToolBatch` / `SubagentStart` / `PreCompact` / … | `UserPromptSubmit` / `PostToolUse` / `SubagentStart` / `PreCompact` / … | `beforeSubmitPrompt` / `postToolUse` / `subagentStart` / `preCompact` / … |
| working | `PreToolUse`(auto) / `PostToolUse` / `SubagentStop` / … | `PreToolUse`(auto) / `SubagentStop` / … | `preToolUse`(auto) / `subagentStop` / … |
| alert | `PermissionRequest` / `Notification` / `StopFailure` / `PermissionDenied` / `Elicitation` / … | `PermissionRequest` / `PreToolUse`(auto) / … | `postToolUseFailure` / … |
| idle | `Stop` / `PostCompact` / `Setup` / … | `Stop` / `PostCompact` / … | `stop` / … |
| off | `SessionEnd` | `SessionEnd` | `sessionEnd` |

另：`SessionStart` 仅用于启动统一守护进程，不映射上表「灯色状态」。

## 安装步骤

### 1. 复制文件

将整个 `traffic_light` 文件夹复制到 `~/.claude/traffic_light/`

### 2. 配置 Codex hooks

将 `extras/legacy_hooks/hooks_traffic_light.json` 的内容合并到 `~/.codex/hooks.json`

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
