"""
手动集成测试：逐状态写文件，需先运行守护进程。

用法: python tests/test_all.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from claude_tl.config import COMMANDS, STATE_DIR


def write_state(state, session="test", ts=None):
    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, session)
    data = json.dumps({"state": state, "ts": ts or time.time()})
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(data)
    os.replace(tmp, path)


def clean_session(session):
    try:
        os.remove(os.path.join(STATE_DIR, session))
    except OSError:
        pass


def test(name, state, duration=2):
    print(f"  {name:15s} ({state:10s} -> '{COMMANDS[state]}') ... ", end="", flush=True)
    write_state(state)
    time.sleep(duration)
    print("OK")


def main():
    print("=" * 50)
    print("红绿灯全量测试（需 daemon 已运行）")
    print("=" * 50)
    print(f"状态目录: {STATE_DIR}\n")

    print("[测试 1] 灯光状态切换")
    tests = [
        ("绿灯闪烁（调模型）", "model"),
        ("绿灯常亮（干活中）", "working"),
        ("黄灯闪烁（思考中）", "thinking"),
        ("红灯闪烁（需要操作）", "alert"),
        ("红灯常亮（等输入）", "idle"),
        ("全灭（会话结束）", "off"),
    ]
    for name, state in tests:
        test(name, state, duration=2)

    print("\n[测试 2] 多终端优先级")
    print("  同时写入 idle 与 alert ... ", end="", flush=True)
    write_state("idle", "session_low")
    write_state("alert", "session_high")
    time.sleep(2)
    clean_session("session_low")
    clean_session("session_high")
    time.sleep(0.5)
    print("OK（应显示红灯闪烁）")

    print("\n[测试 3] 快速切换")
    for _ in range(3):
        for state in ["idle", "thinking", "working", "alert", "off"]:
            write_state(state)
            time.sleep(0.15)
    print("OK")

    write_state("off")
    clean_session("test")
    print("\n完成。")


if __name__ == "__main__":
    main()
