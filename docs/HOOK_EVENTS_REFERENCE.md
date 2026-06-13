# Claude Code / Codex — Hook 全量与红绿灯接线

本文档说明 **官方支持的 Hook 事件全量列表**、**本仓库 `switch_agent` 默认写入 IDE 的接线子集**，以及 **V2.0 除 Hook 外的机制**。

- **机器可读目录**：`src/claude_tl/hook_light_catalog.py`（`CLAUDE_HOOK_CATALOG` / `CODEX_HOOK_CATALOG`，含 `wired` 与 `wire_kind`）。
- **GUI**：`tools/tl_hook_light_gui.py` 第一行可切换 **Claude / Codex**（调用 `switch_agent.switch_agent`，异步 + 进度条）；Claude/Codex 两 Tab 与目录行一一对应。

---

## V2.0 除 Hook 外还用到了什么？

Git 标签 **`V2.0`** 下同样是：**Hook 脚本极薄**（`set_state.py` / `set_state_unified.py`）只写 **`%LOCALAPPDATA%\Temp\` 下状态文件**；**`daemon.py` / `daemon_unified.py` 常驻**占串口、合并多会话优先级后驱动灯。  
因此除 hooks 外，核心是 **守护进程 + 状态文件 IPC**，不是 MCP 轮询灯态。详见 `UNIFIED_README.md`、`TROUBLESHOOTING.md`。

---

## Claude Code — 官方全量事件（文档表）

下列与 **Anthropic 文档** [Hooks reference](https://code.claude.com/docs/en/hooks) 中 *Hook lifecycle* 表一致（2026-06 抓取）。**本仓库 GUI 展示全部**；**`wired=True`** 的项会由 `switch_agent` 写入 `~/.claude/settings.json`（与 `hook_light_catalog` 一致）。

| 事件名 | 默认中文名 | 本仓库默认接线（`wired`） | 说明摘要 |
|--------|------------|---------------------------|----------|
| `SessionStart` | 会话开始 | 是 | 起 `start_daemon_unified.py` |
| `Setup` | 安装/维护模式 | 是 | `set_state_unified.py idle` |
| `UserPromptSubmit` | 用户提交提示 | 是 | `prompt` |
| `UserPromptExpansion` | 命令展开为提示 | 是 | `thinking` |
| `PreToolUse` | 工具调用前 | 是 | `auto` |
| `PermissionRequest` | 权限请求 | 是 | `set_alert_and_defer.py` |
| `PermissionDenied` | 权限被拒绝 | 是 | `alert` |
| `PostToolUse` | 工具成功后 | 是 | `working` |
| `PostToolUseFailure` | 工具失败后 | 是 | `alert` |
| `PostToolBatch` | 并行工具批结束 | 是 | `thinking` |
| `Notification` | 通知 | 是（matcher=`permission_prompt`） | `alert`；其它 notification type 可再自行加 hook 组 |
| `MessageDisplay` | 助手消息展示 | 否 | 高频，默认不接线 |
| `SubagentStart` | 子代理启动 | 是 | `thinking` |
| `SubagentStop` | 子代理结束 | 是 | `working` |
| `TaskCreated` | 任务创建 | 否 | |
| `TaskCompleted` | 任务完成 | 否 | |
| `Stop` | 回合停止 | 是 | `idle` |
| `StopFailure` | 停止失败/API 错 | 是 | `alert` |
| `TeammateIdle` | 队友即将空闲 | 否 | |
| `InstructionsLoaded` | 规则/说明加载 | 否 | |
| `ConfigChange` | 配置变更 | 否 | |
| `CwdChanged` | 工作目录变更 | 否 | 无 matcher，易极频繁 |
| `FileChanged` | 监视文件变更 | 否 | 需在 matcher 中配置监视路径 |
| `WorktreeCreate` | 工作树创建 | 否 | |
| `WorktreeRemove` | 工作树移除 | 否 | |
| `PreCompact` | 压缩上下文前 | 是 | `thinking` |
| `PostCompact` | 压缩上下文后 | 是 | `idle` |
| `Elicitation` | MCP 征求输入 | 是 | `alert` |
| `ElicitationResult` | MCP 征求结果 | 是 | `idle` |
| `SessionEnd` | 会话结束 | 是 | `off` |

若上游新增事件：请在 **`hook_light_catalog.py`** 增补一行，并视需要把 `wired` 设为 `True` 且在 `iter_claude_wired_hook_groups` 逻辑可表达（`daemon` / `alert` / `set_state`）。

---

## Codex — 官方事件 + 本仓库 SessionEnd

依据 [Hooks – Codex](https://developers.openai.com/codex/hooks) 的 matcher 表与正文（2026-06）。**`SessionEnd`** 在官方示例中常与 Stop 并列出现；本仓库历史配置使用 **`SessionEnd` → `off`**，故目录中保留。

| 事件名 | 默认中文名 | 默认接线 | 说明 |
|--------|------------|----------|------|
| `SessionStart` | 会话开始 | 是 | 起守护进程 |
| `UserPromptSubmit` | 用户提交提示 | 是 | `prompt` |
| `PreToolUse` | 工具调用前 | 是 | `auto` |
| `PermissionRequest` | 权限请求 | 是 | `set_alert_and_defer.py` |
| `PostToolUse` | 工具使用后 | 是 | `thinking`（与历史 UNIFIED 表一致） |
| `PreCompact` | 压缩前 | 是 | `thinking` |
| `PostCompact` | 压缩后 | 是 | `idle` |
| `SubagentStart` | 子代理启动 | 是 | `thinking` |
| `SubagentStop` | 子代理结束 | 是 | `working` |
| `Stop` | 回合停止 | 是 | `idle` |
| `SessionEnd` | 会话结束 | 是 | `off` |

---

## GUI 与 `tl_hook_light_gui.json`

- **Agent 切换**：写 `active_agent.json` 并改写 Claude/Codex 的 hooks；完成后应 **重启对应 IDE 会话**。
- **灯光/优先级表**：存 `config/tl_hook_light_gui.json`；**守护进程按 hook 映射灯效** 仍为后续工作。

---

## 相关源码

| 文件 | 作用 |
|------|------|
| `src/claude_tl/hook_light_catalog.py` | 全量目录 + `iter_*_wired_hook_groups` |
| `src/claude_tl/switch_agent.py` | 启用/禁用 hooks、`switch_agent()` |
| `tools/tl_hook_light_gui.py` | 配置 GUI + Agent 切换 |
