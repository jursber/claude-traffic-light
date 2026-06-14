from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUI_PATH = ROOT / "tools" / "tl_hook_light_gui.py"


def _load_gui_module():
    spec = importlib.util.spec_from_file_location("tl_hook_light_gui_for_test", GUI_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_validate_agent_program_path_accepts_matching_file_and_directory(tmp_path: Path) -> None:
    gui = _load_gui_module()

    cursor_exe = tmp_path / "Cursor.exe"
    cursor_exe.write_text("", encoding="utf-8")
    ok, msg, norm = gui.validate_agent_program_path("cursor", str(cursor_exe))
    assert ok is True
    assert msg == "已校验"
    assert norm == str(cursor_exe)

    codex_dir = tmp_path / "codex-install"
    codex_dir.mkdir()
    (codex_dir / "codex.cmd").write_text("", encoding="utf-8")
    ok, msg, norm = gui.validate_agent_program_path("codex", str(codex_dir))
    assert ok is True
    assert msg == "已校验"
    assert norm == str(codex_dir)


def test_validate_agent_program_path_rejects_empty_missing_and_wrong_agent(tmp_path: Path) -> None:
    gui = _load_gui_module()

    ok, msg, norm = gui.validate_agent_program_path("claude", "")
    assert (ok, msg, norm) == (False, "未选择", "")

    missing = tmp_path / "Claude.exe"
    ok, msg, norm = gui.validate_agent_program_path("claude", str(missing))
    assert ok is False
    assert msg == "路径不存在"
    assert norm == str(missing)

    cursor_exe = tmp_path / "Cursor.exe"
    cursor_exe.write_text("", encoding="utf-8")
    ok, msg, norm = gui.validate_agent_program_path("codex", str(cursor_exe))
    assert ok is False
    assert msg == "名称不匹配"
    assert norm == str(cursor_exe)


def test_first_existing_agent_candidate_prefers_path_lookup(monkeypatch, tmp_path: Path) -> None:
    gui = _load_gui_module()

    codex_cmd = tmp_path / "codex.cmd"
    codex_cmd.write_text("", encoding="utf-8")

    def fake_which(name: str) -> str | None:
        return str(codex_cmd) if name == "codex.cmd" else None

    monkeypatch.setattr(gui.shutil, "which", fake_which)
    assert gui._first_existing_agent_candidate("codex") == str(codex_cmd)


def test_group_priority_comboboxes_are_retained() -> None:
    gui = _load_gui_module()

    assert gui.PRIORITY_LABELS == tuple(str(i) for i in range(1, 13))
    source = GUI_PATH.read_text(encoding="utf-8")
    assert '"prio_cb": prio_cb' in source
    assert '"mode_cb": mode_cb' in source
    assert "ttk.Combobox(" in source
    assert source.count("ttk.Combobox(") == 1
    assert "cb = ttk.Combobox(parent, **kwargs)" in source
    assert "_bind_popdown_listbox_mousewheel_break" in source
    assert "_any_combobox_popup_open" in source
    assert 'cb.tk.call("bind", widget, event_name, "break")' in source
    assert 'text="重置"' in source
    assert "def _reset_to_default" in source
    assert "messagebox.askyesno" in source


def test_cleanup_stale_daemon_runtime_files_removes_dead_pid_and_lock(monkeypatch, tmp_path: Path) -> None:
    gui = _load_gui_module()
    pid_file = tmp_path / "daemon.pid"
    lock_file = tmp_path / "daemon.lock"
    pid_file.write_text("999999", encoding="utf-8")
    lock_file.write_text("stale", encoding="utf-8")

    monkeypatch.setattr(gui, "_DAEMON_PID_FILE", pid_file)
    monkeypatch.setattr(gui, "_DAEMON_LOCK_FILE", lock_file)
    monkeypatch.setattr(gui, "pid_alive", lambda _pid: False)

    gui._cleanup_stale_daemon_runtime_files()

    assert not pid_file.exists()
    assert not lock_file.exists()


def test_cleanup_stale_daemon_runtime_files_keeps_live_pid(monkeypatch, tmp_path: Path) -> None:
    gui = _load_gui_module()
    pid_file = tmp_path / "daemon.pid"
    lock_file = tmp_path / "daemon.lock"
    pid_file.write_text("123", encoding="utf-8")
    lock_file.write_text("live", encoding="utf-8")

    monkeypatch.setattr(gui, "_DAEMON_PID_FILE", pid_file)
    monkeypatch.setattr(gui, "_DAEMON_LOCK_FILE", lock_file)
    monkeypatch.setattr(gui, "pid_alive", lambda pid: pid == 123)

    gui._cleanup_stale_daemon_runtime_files()

    assert pid_file.exists()
    assert lock_file.exists()
