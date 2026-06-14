# Codex 官方 Hook 与「非 Hook」灯控路径

## 1. Codex 官方到底有哪些 Hook 事件？

依据 OpenAI 文档 [Hooks – Codex](https://developers.openai.com/codex/hooks) 当前列出的**生命周期事件**主要包括（与 matcher 表一致）：

| 事件 | 说明摘要 |
|------|----------|
| `SessionStart` | 会话/线程启动（matcher：`startup` / `resume` / `clear` / `compact`） |
| `SubagentStart` | 子代理启动 |
| `PreToolUse` | 工具执行前（按工具名 matcher） |
| `PermissionRequest` | 即将弹出审批 |
| `PostToolUse` | 工具输出完成后 |
| `PreCompact` / `PostCompact` | 压缩前后（`manual` / `auto`） |
| `UserPromptSubmit` | 用户提交提示（matcher 文档写明不支持/忽略） |
| `SubagentStop` | 子代理结束 |
| `Stop` | 回合停止（matcher 不支持） |

文档还说明：可存在**多个配置文件层**（`hooks.json`、`config.toml` 内联、`~/.codex`、项目 `.codex`、**插件自带 hooks** 等），同一事件可挂**多条**命令 hook。

本仓库 **`CODEX_HOOK_CATALOG`** 在以上官方集合之外，仅**额外保留**了历史在用的 **`SessionEnd` → `off`**（用于会话结束时灭灯），因此 GUI 里 Codex 表只有 **11 行**是正常现象——**不是漏了官方十几条**，而是官方当前正文里列出的「事件名」本身就不多；其余能力通过 **matcher 分组** 在同一事件下扩展，而不是再增加新事件名。

## 2. 除 Hooks 外，还有哪些办法能给灯光信号？

与 Claude 侧相同，本仓库 V2/V3 核心仍是 **「写状态文件 + 统一守护进程占串口/BLE」**。不经过 Codex hooks 也可以：

1. **手动调用** `set_state_unified.py`（或旧版 `set_state.py`）写入 `%TEMP%` 下对应 agent 的状态目录。  
2. **直接写状态 JSON 文件**（与 hook 脚本相同路径约定），由 **`daemon_unified.py`** 轮询后发 ASCII 或后续扩展发 v1 帧。  
3. **GUI 试灯**：写 **`cc_tl_gui_proto.json`**（`gui_proto_ipc`），由守护进程 `send_raw` 发出 v1 帧（需 daemon 在跑）。  
4. **本机 GUI「连接」串口**：试灯可走 **直连串口**（与 daemon 二选一占口，勿同时抢同一 COM）。  
5. **未来扩展**：任意进程只要能写上述状态文件或 proto 请求文件，即可驱动灯；与是否安装 Codex 无关。
