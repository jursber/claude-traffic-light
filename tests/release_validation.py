#!/usr/bin/env python3
"""Run the repeatable pre-release validation suite and write reports."""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"
JSON_REPORT = REPORT_DIR / "release_validation_report.json"
MD_REPORT = REPORT_DIR / "RELEASE_VALIDATION_REPORT.md"


def _run(name: str, cmd: list[str], timeout: int = 180) -> dict[str, Any]:
    started = time.perf_counter()
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    try:
        result = subprocess.run(
            cmd,
            cwd=ROOT,
            env=env,
            capture_output=True,
            timeout=timeout,
        )
        stdout = _decode_output(result.stdout)
        stderr = _decode_output(result.stderr)
        return {
            "name": name,
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "duration_s": round(time.perf_counter() - started, 3),
            "cmd": subprocess.list2cmdline(cmd),
            "stdout_tail": stdout[-6000:],
            "stderr_tail": stderr[-6000:],
        }
    except subprocess.TimeoutExpired as exc:
        stdout = _decode_output(exc.stdout)
        stderr = _decode_output(exc.stderr)
        return {
            "name": name,
            "ok": False,
            "returncode": None,
            "duration_s": round(time.perf_counter() - started, 3),
            "cmd": subprocess.list2cmdline(cmd),
            "stdout_tail": stdout[-6000:],
            "stderr_tail": stderr[-6000:],
            "error": f"timeout after {timeout}s",
        }


def _decode_output(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    for encoding in ("utf-8", "gbk", "mbcs"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            pass
    return data.decode("utf-8", errors="replace")


def _build_static_checks() -> dict[str, Any]:
    required = [
        ROOT / "packaging" / "build_win.ps1",
        ROOT / "packaging" / "vibelight.spec",
        ROOT / "config" / "tl_hook_light_gui.json",
        ROOT / "docs" / "BUILD_AND_DISTRIBUTE.md",
        ROOT / "docs" / "UNIFIED_README.md",
        ROOT / "docs" / "TROUBLESHOOTING.md",
        ROOT / "extras" / "legacy_hooks" / "hooks_traffic_light.json",
    ]
    missing = [str(p.relative_to(ROOT)) for p in required if not p.exists()]

    root_md = sorted(p.name for p in ROOT.glob("*.md"))
    unexpected_root_md = [name for name in root_md if name != "README.md"]

    return {
        "name": "static_layout",
        "ok": not missing and not unexpected_root_md,
        "missing": missing,
        "unexpected_root_markdown": unexpected_root_md,
    }


def _python_syntax_check(name: str, path: Path) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        return {
            "name": name,
            "ok": True,
            "duration_s": round(time.perf_counter() - started, 3),
            "path": str(path.relative_to(ROOT)),
        }
    except SyntaxError as exc:
        return {
            "name": name,
            "ok": False,
            "duration_s": round(time.perf_counter() - started, 3),
            "path": str(path.relative_to(ROOT)),
            "error": str(exc),
        }


def _exe_smoke_checks() -> dict[str, Any]:
    started = time.perf_counter()
    exe = ROOT / "dist" / "VibeLight" / "VibeLight.exe"
    if not exe.is_file():
        return {
            "name": "exe_smoke",
            "ok": False,
            "duration_s": round(time.perf_counter() - started, 3),
            "error": "dist/VibeLight/VibeLight.exe not found",
        }

    status = _run("exe_status", [str(exe), "switch-agent", "status"], timeout=60)
    invalid = _run("exe_invalid_state", [str(exe), "set-state-unified", "not_a_real_state"], timeout=60)
    return {
        "name": "exe_smoke",
        "ok": status.get("ok") and invalid.get("returncode") != 0,
        "duration_s": round(time.perf_counter() - started, 3),
        "status": status,
        "invalid_state": invalid,
    }


def _read_active_agent_snapshot() -> str | None:
    path = ROOT / "active_agent.json"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _restore_active_agent(snapshot: str | None) -> None:
    if snapshot is None:
        return
    try:
        (ROOT / "active_agent.json").write_text(snapshot, encoding="utf-8")
    except OSError:
        pass


def _write_reports(results: list[dict[str, Any]]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    overall = all(item.get("ok") for item in results)
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "overall_ok": overall,
        "results": results,
    }
    JSON_REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Release Validation Report",
        "",
        f"- Overall: {'PASS' if overall else 'FAIL'}",
        f"- Generated: {payload['generated_at']}",
        "",
        "| Check | Result | Duration |",
        "|---|---:|---:|",
    ]
    for item in results:
        duration = item.get("duration_s", "-")
        lines.append(f"| `{item['name']}` | {'PASS' if item.get('ok') else 'FAIL'} | {duration} |")
    lines.extend(
        [
            "",
            "Detailed command output tails are stored in `reports/release_validation_report.json`.",
            "",
        ]
    )
    MD_REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true", help="also run packaging/build_win.ps1")
    args = parser.parse_args()

    py_files = [
        "src",
        "tools",
        "daemon.py",
        "daemon_unified.py",
        "set_state.py",
        "set_state_unified.py",
        "set_alert_and_defer.py",
        "start_daemon.py",
        "start_daemon_unified.py",
        "switch_agent.py",
    ]
    active_agent_snapshot = _read_active_agent_snapshot()
    try:
        results: list[dict[str, Any]] = [
            _build_static_checks(),
            _python_syntax_check("pyinstaller_spec_syntax", ROOT / "packaging" / "vibelight.spec"),
            _run("compileall", [sys.executable, "-m", "compileall", "-q", *py_files], timeout=180),
            _run("pytest", [sys.executable, "-m", "pytest", "-q", "--tb=short"], timeout=240),
            _run("e2e_selftest_batch", [sys.executable, "tools/e2e_selftest.py", "--batch"], timeout=240),
            _run("build_script_syntax", ["powershell", "-NoProfile", "-NonInteractive", "-Command", "$ErrorActionPreference='Stop'; [scriptblock]::Create((Get-Content -Raw -LiteralPath 'packaging\\build_win.ps1')) | Out-Null"], timeout=60),
        ]
        if args.build:
            results.append(
                _run(
                    "pyinstaller_build",
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "packaging\\build_win.ps1", "-Clean"],
                    timeout=900,
                )
            )
            results.append(_exe_smoke_checks())
    finally:
        _restore_active_agent(active_agent_snapshot)

    _write_reports(results)
    for item in results:
        print(f"[{'OK' if item.get('ok') else 'FAIL'}] {item['name']}")
    print(f"JSON report: {JSON_REPORT}")
    print(f"Markdown report: {MD_REPORT}")
    return 0 if all(item.get("ok") for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
