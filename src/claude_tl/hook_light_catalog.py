"""
红绿灯 Hook 事件目录 — 与 Claude Code / Codex 官方文档对齐（GUI 全量列表 + switch_agent 接线子集）。

- Claude Code 事件表来源：https://code.claude.com/docs/en/hooks（「Hook lifecycle」表，2026-06 抓取）。
- Codex 事件来源：https://developers.openai.com/codex/hooks（matcher 表 + 正文；另含本仓库已使用的 SessionEnd）。

V2.0（tag）除 hooks 外：依赖 **守护进程 + 状态文件**（hook 只调 `set_state*.py` 写 `%TEMP%` 下状态，由 daemon 占串口），见 `UNIFIED_README.md` / `TROUBLESHOOTING.md`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

WireKind = Literal["none", "daemon", "alert", "set_state"]


@dataclass(frozen=True)
class HookCatalogEntry:
    """单条 Hook：GUI 展示全量；`wired` 为 True 时由 switch_agent 写入 settings/hooks.json。"""

    event: str
    zh_default: str
    notes: str = ""
    matcher: str = ""
    """写入 hook_group 的 matcher（空=全匹配；Notification 等为文档建议值）。"""
    wired: bool = False
    wire_kind: WireKind = "none"
    wire_state: str = ""
    """wire_kind==set_state 时传给 set_state_unified.py 的首参（prompt/auto/thinking/...）。"""
    doc_ref: str = "Claude"


def _ce(
    event: str,
    zh: str,
    notes: str,
    matcher: str = "",
    wired: bool = False,
    wire_kind: WireKind = "none",
    wire_state: str = "",
    doc_ref: str = "Claude",
) -> HookCatalogEntry:
    return HookCatalogEntry(
        event=event,
        zh_default=zh,
        notes=notes,
        matcher=matcher,
        wired=wired,
        wire_kind=wire_kind,
        wire_state=wire_state,
        doc_ref=doc_ref,
    )


# --- Claude：官方文档中的全部事件（wired 仅子集，避免 CwdChanged/FileChanged 等过高频默认接线）---
CLAUDE_HOOK_CATALOG: tuple[HookCatalogEntry, ...] = (
    _ce("SessionStart", "会话开始", "会话开始或恢复", "", True, "daemon", ""),
    _ce("Setup", "安装/维护模式", "`--init-only` / `--init` / `--maintenance`", "", True, "set_state", "idle"),
    _ce("UserPromptSubmit", "用户提交提示", "回车后、模型处理前", "", True, "set_state", "prompt"),
    _ce("UserPromptExpansion", "命令展开为提示", "用户输入命令展开成 prompt 前，可拦截", "", True, "set_state", "thinking"),
    _ce("PreToolUse", "工具调用前", "每次工具执行前，可拦截", "", True, "set_state", "auto"),
    _ce("PermissionRequest", "权限请求", "出现权限对话框", "", True, "alert", ""),
    _ce("PermissionDenied", "权限被拒绝", "自动模式拒绝工具后可 retry", "", True, "set_state", "alert"),
    _ce("PostToolUse", "工具成功后", "单次工具成功返回后", "", True, "set_state", "working"),
    _ce("PostToolUseFailure", "工具失败后", "单次工具失败返回后", "", True, "set_state", "alert"),
    _ce("PostToolBatch", "并行工具批结束", "一批并行工具结束后、下一次模型调用前", "", True, "set_state", "thinking"),
    _ce(
        "Notification",
        "通知",
        "系统通知（文档列多种 notification type）",
        "permission_prompt",
        True,
        "set_state",
        "alert",
    ),
    _ce("MessageDisplay", "助手消息展示", "助手文本展示过程中", "", False),
    _ce("SubagentStart", "子代理启动", "子 agent 创建时", "", True, "set_state", "thinking"),
    _ce("SubagentStop", "子代理结束", "子 agent 结束时", "", True, "set_state", "working"),
    _ce("TaskCreated", "任务创建", "`TaskCreate` 创建任务", "", False),
    _ce("TaskCompleted", "任务完成", "任务标记完成", "", False),
    _ce("Stop", "回合停止", "Claude 本回合回复结束", "", True, "set_state", "idle"),
    _ce("StopFailure", "停止失败/API 错", "因 API 错误结束回合", "", True, "set_state", "alert"),
    _ce("TeammateIdle", "队友即将空闲", "多代理场景", "", False),
    _ce("InstructionsLoaded", "规则/说明加载", "CLAUDE.md 或 .claude/rules 加载", "", False),
    _ce("ConfigChange", "配置变更", "settings 等在会话中变更", "", False),
    _ce("CwdChanged", "工作目录变更", "例如执行 cd；无 matcher", "", False),
    _ce("FileChanged", "监视文件变更", "需在 matcher 中写监视 glob/文件名", "", False),
    _ce("WorktreeCreate", "工作树创建", "`--worktree` / isolation", "", False),
    _ce("WorktreeRemove", "工作树移除", "会话结束或子代理结束", "", False),
    _ce("PreCompact", "压缩上下文前", "Compaction 前", "", True, "set_state", "thinking"),
    _ce("PostCompact", "压缩上下文后", "Compaction 完成后", "", True, "set_state", "idle"),
    _ce("Elicitation", "MCP 征求输入", "MCP 请求用户输入", "", True, "set_state", "alert"),
    _ce("ElicitationResult", "MCP 征求结果", "用户已响应 elicitation", "", True, "set_state", "idle"),
    _ce("SessionEnd", "会话结束", "会话终止", "", True, "set_state", "off"),
)


def _dx(
    event: str,
    zh: str,
    notes: str,
    matcher: str = "",
    wired: bool = False,
    wire_kind: WireKind = "none",
    wire_state: str = "",
) -> HookCatalogEntry:
    return HookCatalogEntry(
        event=event,
        zh_default=zh,
        notes=notes,
        matcher=matcher,
        wired=wired,
        wire_kind=wire_kind,
        wire_state=wire_state,
        doc_ref="Codex",
    )


# Codex：developers.openai.com/codex/hooks + 本仓库 SessionEnd
CODEX_HOOK_CATALOG: tuple[HookCatalogEntry, ...] = (
    _dx("SessionStart", "会话开始", "startup|resume|clear|compact", "", True, "daemon", ""),
    _dx("UserPromptSubmit", "用户提交提示", "matcher 被忽略", "", True, "set_state", "prompt"),
    _dx("PreToolUse", "工具调用前", "Bash / apply_patch / MCP 等", "", True, "set_state", "auto"),
    _dx("PermissionRequest", "权限请求", "审批前", "", True, "alert", ""),
    _dx("PostToolUse", "工具使用后", "工具输出完成后（与历史统一：thinking）", "", True, "set_state", "thinking"),
    _dx("PreCompact", "压缩前", "matcher: manual|auto", "", True, "set_state", "thinking"),
    _dx("PostCompact", "压缩后", "matcher: manual|auto", "", True, "set_state", "idle"),
    _dx("SubagentStart", "子代理启动", "子 agent 类型依实现", "", True, "set_state", "thinking"),
    _dx("SubagentStop", "子代理结束", "子 agent 结束", "", True, "set_state", "working"),
    _dx("Stop", "回合停止", "matcher 不支持", "", True, "set_state", "idle"),
    _dx("SessionEnd", "会话结束", "本仓库 hook 使用；部分官方示例未单列", "", True, "set_state", "off"),
)


def catalog_to_markdown_table(title: str, rows: tuple[HookCatalogEntry, ...]) -> str:
    lines = [f"### {title}", "", "| 事件名 | 默认中文名 | 说明 | matcher | 默认接线 |", "|---|---|---|---|---|"]
    for e in rows:
        w = "是" if e.wired else "否"
        m = f"`{e.matcher}`" if e.matcher else "—"
        lines.append(f"| `{e.event}` | {e.zh_default} | {e.notes} | {m} | {w} |")
    lines.append("")
    return "\n".join(lines)


def iter_claude_wired_hook_groups(
    hook_command: Callable[..., str],
    hook_group: Callable[..., dict],
) -> dict:
    """供 switch_agent 使用：仅 wired=True 的 Claude 条目。"""
    out: dict[str, list] = {}
    for e in CLAUDE_HOOK_CATALOG:
        if not e.wired:
            continue
        if e.wire_kind == "daemon":
            cmd = hook_command("start_daemon_unified.py", "")
            grp = hook_group(cmd, matcher=e.matcher or "", timeout=10)
        elif e.wire_kind == "alert":
            cmd = hook_command("set_alert_and_defer.py", "")
            grp = hook_group(cmd, matcher=e.matcher or "", timeout=5)
        else:
            cmd = hook_command("set_state_unified.py", e.wire_state)
            grp = hook_group(cmd, matcher=e.matcher or "", timeout=5)
        out.setdefault(e.event, []).append(grp)
    return out


def iter_codex_wired_hook_groups(
    hook_command: Callable[..., str],
    hook_group: Callable[..., dict],
) -> dict:
    out: dict[str, list] = {}
    for e in CODEX_HOOK_CATALOG:
        if not e.wired:
            continue
        if e.wire_kind == "daemon":
            cmd = hook_command("start_daemon_unified.py", "")
            grp = hook_group(cmd, matcher=e.matcher or "", timeout=10)
        elif e.wire_kind == "alert":
            cmd = hook_command("set_alert_and_defer.py", "")
            grp = hook_group(cmd, matcher=e.matcher or "", timeout=5)
        else:
            cmd = hook_command("set_state_unified.py", e.wire_state)
            grp = hook_group(cmd, matcher=e.matcher or "", timeout=5)
        out.setdefault(e.event, []).append(grp)
    return out
