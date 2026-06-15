"""
红绿灯 Hook 事件目录 — 与 Claude Code / Codex / Cursor 官方文档对齐（GUI 全量列表 + switch_agent 接线子集）。

- Claude Code 事件表来源：https://code.claude.com/docs/en/hooks（「Hook lifecycle」表，2026-06 抓取）。
- Codex 事件来源：https://developers.openai.com/codex/hooks（matcher 表 + 正文；另含本仓库已使用的 SessionEnd）。
- Cursor 事件名与 `hooks.json` 键一致：https://cursor.com/docs/hooks（Agent / Tab / workspaceOpen；2026-06）。

V2.0（tag）除 hooks 外：依赖 **守护进程 + 状态文件**（hook 只调 `set_state*.py` 写 `%TEMP%` 下状态，由 daemon 占串口），见 `docs/UNIFIED_README.md` / `docs/TROUBLESHOOTING.md`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from claude_tl.config import PRIORITY
from claude_tl.vibelight.protocol import MASK_G, MASK_R, MASK_Y

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
    _ce("PostToolUse", "工具成功后", "单次工具成功返回后、下一次模型处理前", "", True, "set_state", "thinking"),
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


def _cr(
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
        doc_ref="Cursor",
    )


# Cursor：`~/.cursor/hooks.json` 或项目 `/.cursor/hooks.json`；事件键为 camelCase（与官方示例一致）
CURSOR_HOOK_CATALOG: tuple[HookCatalogEntry, ...] = (
    _cr("sessionStart", "会话开始", "Agent 会话开始", "", True, "daemon", ""),
    _cr("sessionEnd", "会话结束", "Agent 会话结束", "", True, "set_state", "off"),
    _cr("beforeSubmitPrompt", "提交提示前", "用户发送前；可拦截", "", True, "set_state", "prompt"),
    _cr("preToolUse", "工具调用前", "MCP/编辑等工具执行前", "", True, "set_state", "auto"),
    _cr("postToolUse", "工具成功后", "单次工具成功返回后", "", True, "set_state", "thinking"),
    _cr("postToolUseFailure", "工具失败后", "工具失败返回后", "", True, "set_state", "alert"),
    _cr("preCompact", "压缩上下文前", "Compaction 前", "", True, "set_state", "thinking"),
    _cr("stop", "回合停止", "本回合 agent 循环将结束", "", True, "set_state", "idle"),
    _cr("subagentStart", "子代理启动", "子 agent 创建时", "", True, "set_state", "thinking"),
    _cr("subagentStop", "子代理结束", "子 agent 结束时", "", True, "set_state", "working"),
    _cr(
        "beforeShellExecution",
        "Shell 执行前",
        "可返回 permission；默认不接线以免每条 shell 触发",
        "",
        False,
    ),
    _cr("afterShellExecution", "Shell 执行后", "审计/指标；仅观察", "", False),
    _cr(
        "beforeMCPExecution",
        "MCP 执行前",
        "可返回 permission；默认不接线以免每条 MCP 触发",
        "",
        False,
    ),
    _cr("afterMCPExecution", "MCP 执行后", "MCP 调用完成后", "", False),
    _cr("beforeReadFile", "读文件前", "可返回 permission（只读拦截）", "", False),
    _cr("afterFileEdit", "文件编辑后", "Agent 编辑文件后；fire-and-forget 常见", "", False),
    _cr("afterAgentResponse", "助手回复后", "助手消息生成完成后", "", False),
    _cr("afterAgentThought", "助手思考后", "思考阶段输出后", "", False),
    _cr("beforeTabFileRead", "Tab 补全读文件前", "行内 Tab 补全", "", False),
    _cr("afterTabFileEdit", "Tab 补全编辑后", "行内 Tab 补全", "", False),
    _cr("workspaceOpen", "工作区打开", "与 Agent 会话无关；无 session_id", "", False),
)


# set_state_unified 首参 → GUI 默认灯效（与 V2.0 `config.COMMANDS` + `PRIORITY` 语义对齐）
_STATE_TO_GUI: dict[str, tuple[str, int, str]] = {
    "prompt": ("breath", MASK_Y, "thinking"),
    "auto": ("solid", MASK_G, "working"),
    "thinking": ("breath", MASK_Y, "thinking"),
    "working": ("solid", MASK_G, "working"),
    "alert": ("blink", MASK_R, "alert"),
    "idle": ("solid", MASK_R, "idle"),
    "off": ("none", 0, "off"),
}


def default_hook_gui_row(e: HookCatalogEntry) -> dict[str, Any]:
    """
    单行默认灯光配置（与目录中 wire_kind / wire_state 及 V2 守护进程状态名一致）。
    凡「无灯效」或「未选任一 RGB」的行，优先级固定为 12（与 GUI 规则一致）。
    """

    def _finalize(d: dict[str, Any]) -> dict[str, Any]:
        if d.get("effect") == "none" or int(d.get("mask", 0)) == 0:
            d = dict(d)
            d["priority"] = 12
        return d

    if e.wire_kind == "daemon":
        return _finalize({"event": e.event, "zh": e.zh_default, "effect": "none", "mask": 0, "priority": 12})
    if e.wire_kind == "alert":
        return _finalize(
            {
                "event": e.event,
                "zh": e.zh_default,
                "effect": "blink",
                "mask": MASK_R,
                "priority": PRIORITY["alert"],
            }
        )
    if e.wire_kind == "set_state" and e.wire_state in _STATE_TO_GUI:
        eff, mask, pname = _STATE_TO_GUI[e.wire_state]
        return _finalize(
            {
                "event": e.event,
                "zh": e.zh_default,
                "effect": eff,
                "mask": mask,
                "priority": PRIORITY[pname],
            }
        )
    return _finalize({"event": e.event, "zh": e.zh_default, "effect": "none", "mask": 0, "priority": 12})


def default_tl_hook_light_gui_document() -> dict[str, Any]:
    """全新 `tl_hook_light_gui.json` 的完整默认文档（含 V2 对齐的 Claude/Codex 行）。"""
    return {
        "version": 1,
        "basic": {
            "port": "",
            "duty_g": 255,
            "duty_y": 255,
            "duty_r": 255,
            "blink_period_ms": 800,
            "breath_period_ms": 3000,
            "boot_autostart_daemon": True,
        },
        "claude": {"rows": [default_hook_gui_row(e) for e in CLAUDE_HOOK_CATALOG]},
        "codex": {"rows": [default_hook_gui_row(e) for e in CODEX_HOOK_CATALOG]},
        "cursor": {"rows": [default_hook_gui_row(e) for e in CURSOR_HOOK_CATALOG]},
    }


def claude_hook_gui_sections() -> list[tuple[str, tuple[HookCatalogEntry, ...]]]:
    """
    GUI 分组：「常用」= 目录中 wired 的默认接线；其余未接线事件按主题粗分。
    """
    wired = tuple(e for e in CLAUDE_HOOK_CATALOG if e.wired)
    rest = [e for e in CLAUDE_HOOK_CATALOG if not e.wired]
    out: list[tuple[str, tuple[HookCatalogEntry, ...]]] = []
    if wired:
        out.append(("常用（默认已接线）", wired))

    def take(names: frozenset[str]) -> tuple[HookCatalogEntry, ...]:
        nonlocal rest
        sel = tuple(e for e in rest if e.event in names)
        rest = [e for e in rest if e.event not in names]
        return sel

    buckets: list[tuple[str, frozenset[str]]] = [
        ("工作区与文件", frozenset({"CwdChanged", "FileChanged", "WorktreeCreate", "WorktreeRemove", "ConfigChange"})),
        ("任务与展示", frozenset({"TaskCreated", "TaskCompleted", "MessageDisplay", "TeammateIdle", "InstructionsLoaded"})),
    ]
    for title, names in buckets:
        chunk = take(names)
        if chunk:
            out.append((title, chunk))
    if rest:
        out.append(("其他（可选扩展）", tuple(rest)))
    return out


_CODEX_COMMON_EVENTS = frozenset(
    {
        "SessionStart",
        "UserPromptSubmit",
        "PreToolUse",
        "PermissionRequest",
        "PostToolUse",
        "PreCompact",
        "PostCompact",
        "SubagentStart",
        "SubagentStop",
        "Stop",
    }
)


def codex_hook_gui_sections() -> list[tuple[str, tuple[HookCatalogEntry, ...]]]:
    """官方文档列出的核心回合内事件 →「常用」；本仓库增补的 SessionEnd →「其他」。"""
    common = tuple(e for e in CODEX_HOOK_CATALOG if e.event in _CODEX_COMMON_EVENTS)
    other = tuple(e for e in CODEX_HOOK_CATALOG if e.event not in _CODEX_COMMON_EVENTS)
    out: list[tuple[str, tuple[HookCatalogEntry, ...]]] = []
    if common:
        out.append(("常用", common))
    if other:
        out.append(("其他", other))
    return out


_CURSOR_COMMON_EVENTS = frozenset(
    {
        "sessionStart",
        "sessionEnd",
        "beforeSubmitPrompt",
        "preToolUse",
        "postToolUse",
        "postToolUseFailure",
        "preCompact",
        "stop",
        "subagentStart",
        "subagentStop",
    }
)


def cursor_hook_gui_sections() -> list[tuple[str, tuple[HookCatalogEntry, ...]]]:
    """wired 子集 →「常用」；其余事件 →「其他（参考）」。"""
    common = tuple(e for e in CURSOR_HOOK_CATALOG if e.event in _CURSOR_COMMON_EVENTS)
    other = tuple(e for e in CURSOR_HOOK_CATALOG if e.event not in _CURSOR_COMMON_EVENTS)
    out: list[tuple[str, tuple[HookCatalogEntry, ...]]] = []
    if common:
        out.append(("常用（默认已接线）", common))
    if other:
        out.append(("其他（参考 / 可自扩展）", other))
    return out


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
            cmd = hook_command("set_state_unified.py", e.wire_state, "--event", e.event)
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
            cmd = hook_command("set_state_unified.py", e.wire_state, "--event", e.event)
            grp = hook_group(cmd, matcher=e.matcher or "", timeout=5)
        out.setdefault(e.event, []).append(grp)
    return out


def iter_cursor_wired_hook_items(hook_command: Callable[..., str]) -> dict[str, list[dict[str, Any]]]:
    """
    供 switch_agent 使用：Cursor `hooks.json` 为扁平列表项
    `{ "command": "...", "timeout": 秒, "matcher"?: "..." }`（见 Cursor 文档）。
    """
    out: dict[str, list[dict[str, Any]]] = {}
    for e in CURSOR_HOOK_CATALOG:
        if not e.wired:
            continue
        if e.wire_kind == "daemon":
            cmd = hook_command("start_daemon_unified.py", "")
            timeout = 10
        elif e.wire_kind == "alert":
            cmd = hook_command("set_alert_and_defer.py", "")
            timeout = 5
        else:
            cmd = hook_command("set_state_unified.py", e.wire_state, "--event", e.event)
            timeout = 5
        item: dict[str, Any] = {"command": cmd, "timeout": timeout}
        if e.matcher:
            item["matcher"] = e.matcher
        out.setdefault(e.event, []).append(item)
    return out
