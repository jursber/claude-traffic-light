from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
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
from claude_tl.switch_agent import codex_hook_groups
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
