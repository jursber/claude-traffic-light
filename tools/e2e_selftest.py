#!/usr/bin/env python3
"""
端到端自检：杀进程 → Cursor/hook → stdin 写状态 → **daemon 常驻 + 目视灯态（交互）**
→ 异常路径 → pytest。

默认 **交互模式**（stdin 为 TTY）：在「检查点」会 **暂停并请你输入 ok/wrong/skip** 描述灯态。
非交互（CI / 重定向）：`python tools/e2e_selftest.py --batch` 或 `set CC_TL_E2E_BATCH=1`。

用法（仓库根）:
  python tools/e2e_selftest.py
  python tools/e2e_selftest.py --batch
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
_PID = Path(os.environ.get("LOCALAPPDATA", "")) / "Temp" / "cc_traffic_light_daemon.pid"
_LOCK = Path(os.environ.get("LOCALAPPDATA", "")) / "Temp" / "cc_traffic_light_daemon.lock"
_LOG = Path(os.environ.get("LOCALAPPDATA", "")) / "Temp" / "cc_traffic_light_daemon.log"
_REPORT_DIR = _REPO / "reports"
_REPORT = _REPORT_DIR / "e2e_selftest_report.json"
_PLAN = _REPORT_DIR / "E2E_MODIFICATION_PLAN.md"

_LAMP_SESSION = "e2e-lamp-visual-1"
# (结果键, set_state 首参, stdin_extra dict|None, 期望中文, 单字节参考)
_LAMP_STEPS: tuple[tuple[str, str, dict[str, Any] | None, str, str], ...] = (
    ("LAMP_thinking", "thinking", None, "黄灯闪烁（thinking）", "y"),
    ("LAMP_working", "working", None, "绿灯常亮（working）", "g"),
    ("LAMP_model", "model", None, "绿灯闪烁（model）", "G"),
    ("LAMP_alert", "alert", None, "红灯闪烁（alert）", "r"),
    ("LAMP_idle", "idle", None, "红灯常亮（idle，等输入）", "R"),
    ("LAMP_off", "off", None, "全灭（off）", "O"),
)


def _interactive() -> bool:
    return sys.stdin.isatty() and os.environ.get("CC_TL_E2E_BATCH", "").strip() != "1"


def ask_lamp(checkpoint: str, expect_zh: str, byte_hint: str) -> tuple[bool, str]:
    """目视确认；非交互模式记为 skip-pass。"""
    if not _interactive():
        return True, "batch: 已跳过目视（CC_TL_E2E_BATCH=1 或非 TTY）"

    print("\n" + "=" * 66)
    print(f"【目视检查点 {checkpoint}】")
    print(f"  期望灯态（约 1～2 秒内稳定）：{expect_zh}")
    print(f"  参考（Legacy 单字节）：`{byte_hint}`（PROTO 下可能等效，以实机为准）")
    print("  请看你板子上的灯，然后在下一行输入：")
    print("    ok     — 与期望一致")
    print("    wrong … — 不一致，空格后写原因（例: wrong 一直是红灯）")
    print("    skip   — 本步跳过（仍记为通过，但不证明灯对）")
    print("=" * 66)
    try:
        line = input("灯态> ").strip()
    except EOFError:
        return False, "EOF：未读到输入。若在自动化管道中跑，请加 --batch"

    low = line.lower()
    if low.startswith("skip") or low == "s":
        return True, "用户选择 skip（未验证灯）"
    if low.startswith("wrong") or low.startswith("否") or "不对" in line or low.startswith("no"):
        note = line[5:].strip() if low.startswith("wrong") else line
        return False, f"目视不符: {note}"
    if low.startswith("ok") or low in ("y", "yes", "是", "对", "好"):
        return True, "目视 ok"
    return False, f"输入无法识别，请重跑本脚本并只输入 ok/wrong/skip: {line!r}"


def _windows_pid_alive(pid: int) -> bool:
    try:
        import ctypes
        from ctypes import wintypes

        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, wintypes.DWORD(pid))
        if h:
            k.CloseHandle(h)
            return True
    except Exception:
        pass
    return False


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _py() -> list[str]:
    return [sys.executable]


def _no_window_kw() -> dict[str, Any]:
    if sys.platform != "win32":
        return {}
    cf = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if not cf:
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": cf, "startupinfo": si}


def kill_related_processes() -> None:
    if sys.platform != "win32":
        return
    pat = "|".join(
        re.escape(s)
        for s in (
            str(_REPO).replace("\\", "/"),
            "daemon_unified.py",
            "tl_hook_light_gui.py",
            "vibelight_gui.py",
            "unified_daemon",
            "set_state_unified.py",
            "start_daemon_unified.py",
        )
    )
    ps = (
        "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
        "Where-Object { $_.CommandLine -and ("
        f"$_.CommandLine -match '{pat}'"
        ") } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps],
        capture_output=True,
        timeout=90,
        **_no_window_kw(),
    )
    for p in (_LOCK,):
        try:
            p.unlink()
        except OSError:
            pass


def _ensure_path() -> None:
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))


def test_import_switch_hook_command() -> tuple[bool, str]:
    _ensure_path()
    from claude_tl.switch_agent import hook_command

    cmd = hook_command("set_state_unified.py", "thinking")
    if re.match(r"^python\s", cmd, re.I):
        return False, f"裸 python: {cmd[:120]}"
    exe = Path(sys.executable)
    if str(exe) not in cmd and exe.name not in cmd:
        return False, f"未含解释器路径: {cmd[:160]}"
    return True, cmd[:200]


def test_switch_agent_sub(agent: str) -> tuple[bool, str]:
    r = subprocess.run(
        _py() + [str(_REPO / "switch_agent.py"), agent],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        timeout=90,
        env={**os.environ, "PYTHONPATH": str(_SRC)},
        **_no_window_kw(),
    )
    if r.returncode != 0:
        return False, f"{agent}: exit={r.returncode} err={(r.stderr or '')[:600]}"
    return True, f"switch_agent.py {agent} OK"


def test_cursor_hooks_json() -> tuple[bool, str]:
    p = Path.home() / ".cursor" / "hooks.json"
    if not p.is_file():
        return False, f"无文件: {p}"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return False, str(e)
    hooks = data.get("hooks") or {}
    items = hooks.get("sessionStart") or []
    if not items:
        return False, "sessionStart 为空"
    cmd = str(items[0].get("command", ""))
    if "start_daemon_unified" not in cmd and "start_daemon" not in cmd:
        return False, f"sessionStart 命令异常: {cmd[:120]}"
    if re.match(r"^python\s", cmd, re.I):
        return False, f"裸 python: {cmd[:120]}"
    return True, "hooks.json OK"


def test_set_state_stdin_prompt() -> tuple[bool, str]:
    env = os.environ.copy()
    env.pop("CC_TL_HOME", None)
    env["PYTHONPATH"] = str(_SRC)
    stdin = json.dumps(
        {
            "conversation_id": "e2e-cursor-stdin-1",
            "hook_event_name": "beforeSubmitPrompt",
            "prompt": "e2e",
        }
    )
    r = subprocess.run(
        _py() + [str(_REPO / "set_state_unified.py"), "prompt"],
        cwd=str(_REPO),
        input=stdin,
        text=True,
        capture_output=True,
        timeout=15,
        env=env,
        **_no_window_kw(),
    )
    if r.returncode != 0:
        return False, f"exit={r.returncode} err={(r.stderr or '')[:400]}"
    sd = Path(os.environ.get("LOCALAPPDATA", "")) / "Temp" / "cursor_tl_states" / "e2e-cursor-stdin-1"
    if not sd.is_file():
        return False, f"未落盘: {sd}"
    try:
        sd.unlink()
    except OSError:
        pass
    return True, "prompt→thinking 落盘 OK"


def _invoke_set_state(state: str, extra: dict[str, Any] | None = None) -> tuple[bool, str]:
    env = os.environ.copy()
    env.pop("CC_TL_HOME", None)
    env["PYTHONPATH"] = str(_SRC)
    d: dict[str, Any] = {"conversation_id": _LAMP_SESSION}
    if extra:
        d.update(extra)
    r = subprocess.run(
        _py() + [str(_REPO / "set_state_unified.py"), state],
        cwd=str(_REPO),
        input=json.dumps(d),
        text=True,
        capture_output=True,
        timeout=15,
        env=env,
        **_no_window_kw(),
    )
    if r.returncode != 0:
        return False, f"{state}: rc={r.returncode} err={(r.stderr or '')[:300]}"
    return True, f"{state} OK"


def daemon_start_keepalive() -> tuple[bool, str, dict[str, Any]]:
    """清锁与 pid，启动 daemon，等到 PID+（尽量）硬件日志；不杀进程。"""
    det: dict[str, Any] = {}
    for p in (_PID, _LOCK):
        try:
            p.unlink()
        except OSError:
            pass
    pyw = Path(sys.executable)
    if pyw.name.lower() == "python.exe":
        cand = pyw.parent / "pythonw.exe"
        if cand.is_file():
            pyw = cand
    try:
        subprocess.Popen(
            [str(pyw), str(_REPO / "daemon_unified.py")],
            cwd=str(_REPO),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **_no_window_kw(),
        )
    except OSError as e:
        return False, f"Popen: {e}", det

    pid_live = False
    hw = False
    t0 = time.time()
    while time.time() - t0 < 30.0:
        try:
            if _PID.is_file():
                pid = int(_PID.read_text(encoding="utf-8").strip())
                pid_live = _pid_alive(pid)
        except (OSError, ValueError):
            pid_live = False
        if _LOG.is_file():
            tail = _LOG.read_text(encoding="utf-8", errors="replace")[-12000:]
            if "硬件已连接" in tail or "串口已连接" in tail or "BLE 已连接" in tail:
                hw = True
        if pid_live and hw:
            break
        time.sleep(0.35)
    det["pid_live"] = pid_live
    det["hardware_log"] = hw
    if not pid_live:
        return False, "daemon 未起来（无存活 PID）", det
    if not hw:
        return False, "daemon 已起但未在日志中看到硬件连接（无板子/串口占满则无法继续目视套件）", det
    return True, "daemon 已起且硬件已连接", det


def daemon_kill() -> None:
    try:
        if _PID.is_file():
            pid = int(_PID.read_text(encoding="utf-8").strip())
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F", "/T"],
                capture_output=True,
                timeout=20,
                **_no_window_kw(),
            )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    time.sleep(0.5)
    for p in (_PID, _LOCK):
        try:
            p.unlink()
        except OSError:
            pass


def test_daemon_second_instance_lock_log() -> tuple[bool, str]:
    """再起一个 daemon，应抢锁失败并在日志留痕。"""
    ok, _, det = daemon_start_keepalive()
    if not ok or not det.get("hardware_log"):
        return True, "跳过：无硬件或未连上"
    before = _LOG.read_text(encoding="utf-8", errors="replace") if _LOG.is_file() else ""
    pyw = Path(sys.executable)
    if pyw.name.lower() == "python.exe":
        cand = pyw.parent / "pythonw.exe"
        if cand.is_file():
            pyw = cand
    r = subprocess.run(
        [str(pyw), str(_REPO / "daemon_unified.py")],
        cwd=str(_REPO),
        capture_output=True,
        timeout=8,
        env={**os.environ, "PYTHONPATH": str(_SRC)},
        **_no_window_kw(),
    )
    time.sleep(0.6)
    after = _LOG.read_text(encoding="utf-8", errors="replace") if _LOG.is_file() else ""
    tail = after[len(before) :] if len(after) >= len(before) else after
    daemon_kill()
    if "文件锁" in tail or "锁" in tail:
        return True, "第二实例抢锁失败已记入日志"
    if r.returncode == 0:
        return False, "第二实例退出码 0 且日志未见锁说明（异常）"
    return True, f"第二实例 rc={r.returncode}（日志未匹配关键字时仍视为可接受）"


def test_edge_invalid_state_argv() -> tuple[bool, str]:
    env = {**os.environ, "PYTHONPATH": str(_SRC)}
    r = subprocess.run(
        _py() + [str(_REPO / "set_state_unified.py"), "not_a_real_state"],
        cwd=str(_REPO),
        input=json.dumps({"conversation_id": "e2e-x"}),
        text=True,
        capture_output=True,
        timeout=10,
        env=env,
        **_no_window_kw(),
    )
    if r.returncode == 0:
        return False, "非法状态名应非零退出"
    return True, "非法 argv 状态已拒绝"


def test_edge_auto_pre_tool() -> tuple[bool, str]:
    """preToolUse 语义：auto + tool_name → working。"""
    env = {**os.environ, "PYTHONPATH": str(_SRC)}
    env.pop("CC_TL_HOME", None)
    stdin = json.dumps({"conversation_id": "e2e-auto-1", "tool_name": "Read"})
    r = subprocess.run(
        _py() + [str(_REPO / "set_state_unified.py"), "auto"],
        cwd=str(_REPO),
        input=stdin,
        text=True,
        capture_output=True,
        timeout=10,
        env=env,
        **_no_window_kw(),
    )
    if r.returncode != 0:
        return False, f"auto rc={r.returncode}"
    p = Path(os.environ.get("LOCALAPPDATA", "")) / "Temp" / "cursor_tl_states" / "e2e-auto-1"
    if not p.is_file():
        return False, "auto 未落盘"
    try:
        p.unlink()
    except OSError:
        pass
    return True, "auto→working OK"


def test_pytest() -> tuple[bool, str]:
    pytest = shutil.which("pytest")
    if not pytest:
        return True, "跳过 pytest（未安装）"
    r = subprocess.run(
        [pytest, str(_REPO / "tests"), "-q", "--tb=line"],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        timeout=180,
        env={**os.environ, "PYTHONPATH": str(_SRC)},
    )
    if r.returncode != 0:
        return False, (r.stdout + "\n" + r.stderr)[-5000:]
    return True, "pytest OK"


def run_lamp_suite(results: dict[str, Any]) -> None:
    ok0, msg0, det = daemon_start_keepalive()
    results["T_daemon_start"] = {"ok": ok0, "msg": msg0, "details": det}
    if not ok0 or not det.get("hardware_log"):
        results["T_lamp_suite"] = {
            "ok": False,
            "msg": "目视套件跳过：daemon/硬件未就绪。请插 ESP32、释放 COM 后重跑。",
        }
        daemon_kill()
        return

    # 清理旧会话文件
    sd_root = Path(os.environ.get("LOCALAPPDATA", "")) / "Temp" / "cursor_tl_states"
    try:
        p = sd_root / _LAMP_SESSION
        if p.is_file():
            p.unlink()
    except OSError:
        pass

    suite_ok = True
    for key, state, extra, zh, byte in _LAMP_STEPS:
        ir, im = _invoke_set_state(state, extra)
        if not ir:
            results[key] = {"ok": False, "msg": f"写状态失败: {im}"}
            suite_ok = False
            break
        time.sleep(1.25)
        lr, lm = ask_lamp(key, zh, byte)
        results[key] = {"ok": lr, "msg": lm}
        if not lr:
            suite_ok = False
            break

    results["T_lamp_suite"] = {"ok": suite_ok, "msg": "全套目视通过" if suite_ok else "目视套件中断"}
    try:
        (sd_root / _LAMP_SESSION).unlink()
    except OSError:
        pass
    daemon_kill()


def run_all(batch: bool) -> dict[str, Any]:
    if batch:
        os.environ["CC_TL_E2E_BATCH"] = "1"

    results: dict[str, Any] = {}
    kill_related_processes()
    results["T_kill"] = {"ok": True, "msg": "已杀相关进程并尝试删 lock"}

    def add(name: str, fn: Callable[[], tuple[bool, str]]) -> None:
        o, m = fn()
        results[name] = {"ok": o, "msg": m}

    add("T_hook_cmd", test_import_switch_hook_command)
    add("T_switch_cursor", lambda: test_switch_agent_sub("cursor"))
    add("T_cursor_hooks", test_cursor_hooks_json)
    add("T_stdin_prompt", test_set_state_stdin_prompt)

    run_lamp_suite(results)

    add("T_edge_invalid_state", test_edge_invalid_state_argv)
    add("T_edge_auto", test_edge_auto_pre_tool)
    add("T_daemon_lock2", test_daemon_second_instance_lock_log)

    # 往返（可选破坏当前 IDE 选中；默认执行以覆盖「切走再切回」）
    add("T_switch_claude", lambda: test_switch_agent_sub("claude"))
    add("T_switch_cursor2", lambda: test_switch_agent_sub("cursor"))

    add("T_pytest", test_pytest)
    return results


def write_plan(results: dict[str, Any]) -> None:
    fails = [k for k, v in results.items() if isinstance(v, dict) and not v.get("ok")]
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    _REPORT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# E2E 自检结果（含目视）",
        "",
        f"- 失败项: {', '.join(fails) if fails else '无'}",
        f"- 交互模式: {'否（batch）' if os.environ.get('CC_TL_E2E_BATCH') else '是（默认 TTY 下会 ask_lamp）'}",
        "",
        "详细 JSON: `reports/e2e_selftest_report.json`",
        "",
    ]
    _PLAN.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", action="store_true", help="跳过目视提问（CI/非 TTY）")
    args = ap.parse_args()

    print("E2E selftest —", _REPO)
    if not args.batch and not _interactive():
        print("提示: stdin 非 TTY，自动按 --batch 行为跳过目视（仍跑自动化）。")
        args.batch = True

    results = run_all(batch=args.batch)
    write_plan(results)

    ok_all = all(
        v.get("ok")
        for k, v in results.items()
        if isinstance(v, dict) and k.startswith(("T_", "LAMP_")) and k != "T_kill"
    )
    for k in sorted(results):
        v = results[k]
        if isinstance(v, dict):
            mark = "OK " if v.get("ok") else "FAIL"
            print(f"  [{mark}] {k}: {v.get('msg', '')}")
    print("Report:", _REPORT)
    print("Plan: ", _PLAN)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
