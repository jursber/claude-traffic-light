"""
命令行入口：python -m claude_tl <子命令> [参数...]

安装可编辑包后可在任意目录使用；子命令与根目录 .py 启动器对应。
"""

from __future__ import annotations

import sys


def _usage() -> None:
    print(
        """用法: python -m claude_tl <子命令> [参数...]

子命令:
  daemon              经典守护进程（仅 Claude 状态目录）
  daemon-unified      统一守护进程（Claude + Codex）
  start-daemon        通过计划任务拉起经典守护进程
  start-daemon-unified 直接启动 unified 守护（SessionStart hook）
  set-state           经典 set_state
  set-state-unified   统一 set_state
  set-alert           PermissionRequest 专用
  switch-agent        claude | codex | status

示例:
  python -m claude_tl daemon-unified
  python -m claude_tl set-state-unified thinking
""",
        file=sys.stderr,
    )


def main() -> None:
    if len(sys.argv) < 2:
        _usage()
        sys.exit(2)

    cmd = sys.argv[1]
    rest = sys.argv[2:]
    prog = sys.argv[0]
    sys.argv = [prog + " " + cmd] + rest

    if cmd == "daemon":
        from claude_tl.daemon import main as m

        m()
    elif cmd == "daemon-unified":
        from claude_tl.unified_daemon import main as m

        m()
    elif cmd == "start-daemon":
        from claude_tl.start_daemon import main as m

        m()
    elif cmd == "start-daemon-unified":
        from claude_tl.start_daemon_unified import main as m

        m()
    elif cmd == "set-state":
        from claude_tl.set_state import main as m

        m()
    elif cmd == "set-state-unified":
        from claude_tl.set_state_unified import main as m

        m()
    elif cmd == "set-alert":
        from claude_tl.set_alert_and_defer import main as m

        m()
    elif cmd == "switch-agent":
        from claude_tl.switch_agent import main as m

        m()
    else:
        print("未知子命令:", cmd, file=sys.stderr)
        _usage()
        sys.exit(2)


if __name__ == "__main__":
    main()
