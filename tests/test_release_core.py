from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from claude_tl import light_effects as le
from claude_tl.hook_light_catalog import (
    CLAUDE_HOOK_CATALOG,
    CODEX_HOOK_CATALOG,
    CURSOR_HOOK_CATALOG,
    default_tl_hook_light_gui_document,
    iter_claude_wired_hook_groups,
    iter_codex_wired_hook_groups,
    iter_cursor_wired_hook_items,
)
from claude_tl.switch_agent import codex_hook_groups, reset_agent_state_dir
from claude_tl.vibelight.protocol import MASK_G, MASK_R, MASK_Y, MODE_BREATH, MODE_SYNC_BLINK, parse_frame


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _write_active_agent(home: Path, active: str = "cursor") -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "active_agent.json").write_text(
        json.dumps(
            {
                "active": active,
                "agents": {
                    "claude": {"state_dir": "cc_tl_states"},
                    "codex": {"state_dir": "codex_tl_states"},
                    "cursor": {"state_dir": "cursor_tl_states"},
                },
            }
        ),
        encoding="utf-8",
    )


def test_default_gui_document_matches_catalogs() -> None:
    doc = default_tl_hook_light_gui_document()
    expected = {
        "claude": CLAUDE_HOOK_CATALOG,
        "codex": CODEX_HOOK_CATALOG,
        "cursor": CURSOR_HOOK_CATALOG,
    }
    for agent, catalog in expected.items():
        rows = doc[agent]["rows"]
        assert [r["event"] for r in rows] == [e.event for e in catalog]
        assert all({"event", "zh", "effect", "mask", "priority"} <= set(r) for r in rows)


def test_pyproject_dependency_groups_match_runtime_roles() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "pyserial>=3.5" in data["project"]["dependencies"]
    assert not any(dep.startswith("bleak") for dep in data["project"]["dependencies"])
    optional = data["project"]["optional-dependencies"]
    assert "bleak>=0.21.0" in optional["ble"]
    assert "pystray>=0.19.5" in optional["gui"]
    assert "Pillow>=10.0.0" in optional["gui"]


def test_default_gui_document_uses_v2_priorities_with_thinking_breath() -> None:
    doc = default_tl_hook_light_gui_document()

    def by_event(agent: str) -> dict[str, dict]:
        return {row["event"]: row for row in doc[agent]["rows"]}

    claude = by_event("claude")
    codex = by_event("codex")
    cursor = by_event("cursor")

    assert doc["basic"]["breath_period_ms"] == 3000
    assert claude["PermissionRequest"] == {
        "event": "PermissionRequest",
        "zh": "权限请求",
        "effect": "blink",
        "mask": MASK_R,
        "priority": 1,
    }
    assert claude["UserPromptSubmit"]["effect"] == "breath"
    assert claude["UserPromptSubmit"]["mask"] == MASK_Y
    assert claude["UserPromptSubmit"]["priority"] == 2
    assert claude["PostToolUse"]["effect"] == "breath"
    assert claude["PostToolUse"]["mask"] == MASK_Y
    assert claude["PostToolUse"]["priority"] == 2
    assert codex["PostToolUse"]["effect"] == "breath"
    assert codex["PostToolUse"]["mask"] == MASK_Y
    assert codex["PostToolUse"]["priority"] == 2
    assert cursor["postToolUse"]["effect"] == "breath"
    assert cursor["postToolUse"]["mask"] == MASK_Y
    assert cursor["postToolUse"]["priority"] == 2


def test_wired_hook_commands_include_event_argument() -> None:
    def hook_command(script: str, state: str, *extra: str) -> str:
        return " ".join([script, state, *extra]).strip()

    def hook_group(command: str, matcher: str = "", timeout: int = 5) -> dict:
        return {"matcher": matcher, "hooks": [{"command": command, "timeout": timeout}]}

    claude = iter_claude_wired_hook_groups(hook_command, hook_group)
    codex = iter_codex_wired_hook_groups(hook_command, hook_group)
    cursor = iter_cursor_wired_hook_items(hook_command)

    for groups in (claude, codex):
        for event, event_groups in groups.items():
            for group in event_groups:
                command = group["hooks"][0]["command"]
                if "set_state_unified.py" in command:
                    assert f"--event {event}" in command

    for event, items in cursor.items():
        for item in items:
            command = item["command"]
            if "set_state_unified.py" in command:
                assert f"--event {event}" in command


def test_claude_post_tool_hook_never_uses_legacy_working_state() -> None:
    def hook_command(script: str, state: str, *extra: str) -> str:
        return " ".join([script, state, *extra]).strip()

    def hook_group(command: str, matcher: str = "", timeout: int = 5) -> dict:
        return {"matcher": matcher, "hooks": [{"command": command, "timeout": timeout}]}

    groups = iter_claude_wired_hook_groups(hook_command, hook_group)
    commands = [hook["command"] for group in groups["PostToolUse"] for hook in group["hooks"]]

    assert commands
    assert all(" thinking " in f" {command} " for command in commands)
    assert not any(" working " in f" {command} " for command in commands)


def test_switch_agent_removes_packaged_legacy_traffic_light_hooks() -> None:
    from claude_tl.switch_agent import remove_traffic_light_hooks

    legacy_state = "work" + "ing"
    legacy_event = "PostTool" + "Use"
    legacy_command = (
        rf"C:\Program Files\VibeLight\VibeLight.exe set-state-unified {legacy_state} --event {legacy_event}"
    )
    config = {
        "hooks": {
            "PostToolUse": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": legacy_command,
                        },
                        {"type": "command", "command": "echo keep-user-hook"},
                    ],
                }
            ]
        }
    }

    remove_traffic_light_hooks(config)

    hooks = config["hooks"]["PostToolUse"][0]["hooks"]
    assert hooks == [{"type": "command", "command": "echo keep-user-hook"}]


def test_codex_hooks_do_not_depend_on_bash_shell() -> None:
    groups = codex_hook_groups()
    for event_groups in groups.values():
        for group in event_groups:
            for hook in group["hooks"]:
                assert "shell" not in hook


def test_frame_for_runtime_uses_global_periods_and_color_duties() -> None:
    basic = {
        "blink_period_ms": 1234,
        "breath_period_ms": 2345,
        "duty_g": 10,
        "duty_y": 20,
        "duty_r": 30,
    }

    blink_y = parse_frame(le.frame_for_runtime("thinking", "blink", MASK_Y, basic))
    assert blink_y is not None
    assert blink_y == (MODE_SYNC_BLINK, MASK_Y, 1234, 0, 20, 0)

    breath_gy = parse_frame(le.frame_for_runtime("thinking", "breath", MASK_G | MASK_Y, basic))
    assert breath_gy is not None
    assert breath_gy == (MODE_BREATH, MASK_G | MASK_Y, 2345, 10, 20, 0)

    alert_default = parse_frame(le.frame_for_runtime("alert", None, None, basic))
    assert alert_default is not None
    assert alert_default[1] == MASK_R
    assert alert_default[5] == 30


def test_legacy_state_effect_period_is_clamped_to_protocol_minimum() -> None:
    effects = le.normalize_state_effects({"thinking": {"period_ms": 0}})
    assert effects["thinking"]["period_ms"] == 50


def test_highest_priority_prefers_per_hook_priority() -> None:
    from claude_tl.unified_daemon import highest_priority

    states = {
        "a": {"state": "idle", "priority": 1, "mode": "solid", "mask": MASK_R},
        "b": {"state": "alert", "priority": 9, "mode": "blink", "mask": MASK_R},
    }
    assert highest_priority(states)["state"] == "idle"


def test_set_state_unified_writes_event_light_with_cursor_fallback(tmp_path: Path) -> None:
    home = tmp_path / "home"
    local_appdata = tmp_path / "localappdata"
    _write_active_agent(home, "cursor")

    doc = default_tl_hook_light_gui_document()
    for row in doc["cursor"]["rows"]:
        if row["event"] == "postToolUse":
            row.update({"effect": "breath", "mask": MASK_Y, "priority": 2})
    config_dir = home / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "tl_hook_light_gui.json").write_text(json.dumps(doc), encoding="utf-8")

    env = {
        **os.environ,
        "CC_TL_HOME": str(home),
        "LOCALAPPDATA": str(local_appdata),
        "PYTHONPATH": str(SRC),
    }
    cmd = [sys.executable, str(ROOT / "set_state_unified.py"), "thinking", "--event", "postToolUse"]
    result = subprocess.run(cmd, input="{}", text=True, capture_output=True, cwd=ROOT, env=env, timeout=15)
    assert result.returncode == 0, result.stderr

    state_file = local_appdata / "Temp" / "cursor_tl_states" / "_anon"
    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert payload["state"] == "thinking"
    assert payload["mode"] == "breath"
    assert payload["mask"] == MASK_Y
    assert payload["priority"] == 2


def test_read_all_states_uses_active_agent_directory_and_ignores_metadata(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    local_appdata = tmp_path / "localappdata"
    _write_active_agent(home, "codex")
    monkeypatch.setenv("CC_TL_HOME", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))

    import claude_tl.unified_daemon as daemon

    daemon = importlib.reload(daemon)
    state_dir = local_appdata / "Temp" / "codex_tl_states"
    state_dir.mkdir(parents=True)
    (state_dir / "_last_session").write_text("real-session", encoding="utf-8")
    (state_dir / "partial.tmp").write_text("ignored", encoding="utf-8")
    (state_dir / "real-session").write_text(
        json.dumps({"state": "working", "ts": 1893456000, "mode": "solid", "mask": MASK_G, "priority": 4}),
        encoding="utf-8",
    )

    states = daemon.read_all_states()
    assert list(states) == ["real-session"]
    assert states["real-session"]["state"] == "working"
    assert states["real-session"]["mask"] == MASK_G


def test_global_off_keeps_metadata_files(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    local_appdata = tmp_path / "localappdata"
    _write_active_agent(home, "claude")
    monkeypatch.setenv("CC_TL_HOME", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))

    import claude_tl.unified_daemon as daemon

    daemon = importlib.reload(daemon)
    state_dir = local_appdata / "Temp" / "cc_tl_states"
    state_dir.mkdir(parents=True)
    (state_dir / "_last_session").write_text("real-session", encoding="utf-8")
    (state_dir / "real-session").write_text(json.dumps({"state": "working", "ts": 1893456000}), encoding="utf-8")
    (state_dir / "_global_off").write_text(json.dumps({"state": "off", "ts": 1893456000}), encoding="utf-8")

    states = daemon.read_all_states()

    assert states == {"_global_off": {"state": "off"}}
    assert (state_dir / "_last_session").exists()
    assert not (state_dir / "real-session").exists()


def test_global_off_does_not_mask_newer_session_state(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    local_appdata = tmp_path / "localappdata"
    _write_active_agent(home, "claude")
    monkeypatch.setenv("CC_TL_HOME", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))

    import claude_tl.unified_daemon as daemon

    daemon = importlib.reload(daemon)
    state_dir = local_appdata / "Temp" / "cc_tl_states"
    state_dir.mkdir(parents=True)
    (state_dir / "_global_off").write_text(json.dumps({"state": "off", "ts": 1000}), encoding="utf-8")
    new_session = state_dir / "new-session"
    new_session.write_text(
        json.dumps({"state": "thinking", "ts": 1893456000, "mode": "breath", "mask": MASK_Y, "priority": 2}),
        encoding="utf-8",
    )
    os.utime(new_session, (2000, 2000))

    states = daemon.read_all_states()

    assert list(states) == ["new-session"]
    assert states["new-session"]["state"] == "thinking"
    assert states["new-session"]["mode"] == "breath"
    assert not (state_dir / "_global_off").exists()


def test_reset_agent_state_dir_clears_stale_sessions_and_writes_global_off(tmp_path: Path, monkeypatch) -> None:
    local_appdata = tmp_path / "localappdata"
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    cfg = {"agents": {"claude": {"state_dir": "cc_tl_states"}}}
    state_dir = local_appdata / "Temp" / "cc_tl_states"
    state_dir.mkdir(parents=True)
    (state_dir / "_last_session").write_text("real-session", encoding="utf-8")
    (state_dir / "old-session").write_text(json.dumps({"state": "working", "ts": 1}), encoding="utf-8")

    reset_agent_state_dir(cfg, "claude")

    assert (state_dir / "_last_session").exists()
    assert not (state_dir / "old-session").exists()
    off = json.loads((state_dir / "_global_off").read_text(encoding="utf-8"))
    assert off["state"] == "off"


def test_set_state_unified_rejects_pathlike_session_id(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    local_appdata = tmp_path / "localappdata"
    _write_active_agent(home, "claude")
    monkeypatch.setenv("CC_TL_HOME", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))

    import claude_tl.set_state_unified as set_state_unified

    set_state_unified = importlib.reload(set_state_unified)
    assert not set_state_unified.set_state("thinking", "../bad")
    assert not (local_appdata / "Temp" / "bad").exists()


def test_set_alert_and_defer_uses_active_agent_directory(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    local_appdata = tmp_path / "localappdata"
    _write_active_agent(home, "codex")
    monkeypatch.setenv("CC_TL_HOME", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))

    import claude_tl.set_state_unified as set_state_unified
    import claude_tl.set_alert_and_defer as alert

    importlib.reload(set_state_unified)
    alert = importlib.reload(alert)
    assert alert.set_state("alert", "session-1")
    assert (local_appdata / "Temp" / "codex_tl_states" / "session-1").exists()
    assert not (local_appdata / "Temp" / "cc_tl_states" / "session-1").exists()
