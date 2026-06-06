"""
全量测试脚本 - 验证所有灯光状态、多终端优先级和心跳超时

使用方法：
  1. 先确保守护进程在运行（python daemon.py 或通过守护脚本）
  2. 运行本脚本：python test_all.py
  3. 观察灯的变化，确认每种状态都正确

测试内容：
  - 6 种灯光状态逐一切换（每种 2 秒）
  - 多终端优先级测试（两个终端同时存在时显示高优先级）
  - 心跳超时测试（模拟崩溃，验证自动降级为 idle）
  - 快速连续切换测试（验证不会卡死）
"""

import os
import json
import time

from config import COMMANDS, STATE_DIR, HEARTBEAT_TIMEOUT


def write_state(state, session="test", ts=None):
    """
    写入指定 session 的状态文件（JSON 格式）。
    ts 参数可指定时间戳，默认为当前时间。
    """
    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, session)
    data = json.dumps({"state": state, "ts": ts or time.time()})
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(data)
    os.replace(tmp, path)


def clean_session(session):
    """删除指定 session 的状态文件（测试完清理用）。"""
    try:
        os.remove(os.path.join(STATE_DIR, session))
    except OSError:
        pass


def test(name, state, duration=2):
    """单项测试：设置状态，等待指定时间让用户观察。"""
    print(f"  {name:15s} ({state:10s} -> '{COMMANDS[state]}') ... ", end="", flush=True)
    write_state(state)
    time.sleep(duration)
    print("OK")


def main():
    print("=" * 50)
    print("红绿灯全量测试")
    print("=" * 50)
    print(f"状态目录: {STATE_DIR}")
    print(f"心跳超时: {HEARTBEAT_TIMEOUT} 秒")
    print("请确保守护进程正在运行！\n")

    # ----------------------------------------------------------
    # 测试 1：6 种灯光状态逐一切换
    # ----------------------------------------------------------
    print("[测试 1] 灯光状态切换")
    tests = [
        ("绿灯闪烁（调模型）",   "model"),
        ("绿灯常亮（干活中）",   "working"),
        ("黄灯闪烁（思考中）",   "thinking"),
        ("红灯闪烁（需要操作）", "alert"),
        ("红灯常亮（等输入）",   "idle"),
        ("全灭（会话结束）",     "off"),
    ]
    for name, state in tests:
        test(name, state, duration=2)

    # ----------------------------------------------------------
    # 测试 2：多终端优先级
    # ----------------------------------------------------------
    print("\n[测试 2] 多终端优先级")
    print("  同时写入 idle(优先级5) 和 alert(优先级1) ... ", end="", flush=True)
    write_state("idle", "session_low")
    write_state("alert", "session_high")
    time.sleep(2)
    clean_session("session_low")
    clean_session("session_high")
    time.sleep(0.5)
    print("OK（应该显示红灯闪烁）")

    # ----------------------------------------------------------
    # 测试 3：心跳超时（模拟崩溃）
    # ----------------------------------------------------------
    print(f"\n[测试 3] 心跳超时（模拟崩溃，超时={HEARTBEAT_TIMEOUT}秒）")
    print("  写入 working 状态，时间戳设为 2 分钟前 ... ", end="", flush=True)
    # 写入一个"过期"的 working 状态（时间戳 = 2 分钟前）
    write_state("working", "crashed_session", ts=time.time() - 120)
    time.sleep(1)
    # 守护进程应该自动降级为 idle（因为心跳超时）
    # 验证：灯应该显示 idle（红灯常亮），而不是 working（绿灯常亮）
    print("OK（灯应该显示红灯常亮/idle，而不是绿灯/working）")
    clean_session("crashed_session")
    time.sleep(0.5)

    # ----------------------------------------------------------
    # 测试 4：快速连续切换
    # ----------------------------------------------------------
    print("\n[测试 4] 快速切换（验证不会卡死）")
    print("  快速循环切换 ... ", end="", flush=True)
    for _ in range(3):
        for state in ["idle", "thinking", "working", "alert", "off"]:
            write_state(state)
            time.sleep(0.15)
    print("OK")

    # ----------------------------------------------------------
    # 清理
    # ----------------------------------------------------------
    write_state("off")
    clean_session("test")
    print("\n" + "=" * 50)
    print("全部测试通过！")
    print("=" * 50)


if __name__ == "__main__":
    main()
