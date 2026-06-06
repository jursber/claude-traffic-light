"""
守护进程 - 红绿灯的核心控制器

工作原理：
  1. 启动后打开串口，一直持有（不会每次开关）
  2. 每 50ms 扫描一次状态目录，读取所有 CC 终端的状态文件
  3. 按优先级选出最紧急的状态
  4. 通过串口发送对应指令给 ESP32C3
  5. 只有状态变化时才发指令，避免重复发送

为什么用守护进程？
  如果每个 hook 都自己开串口发指令，会有两个问题：
  1. Python 启动慢（~300ms），灯有明显延迟
  2. 多个 hook 同时开串口会冲突
  守护进程常驻后台，串口一直开着，hook 只需要写一个几字节的小文件。
"""

import os
import time
import json
import serial
import sys

from config import SERIAL_PORT, BAUD_RATE, COMMANDS, STATE_DIR, PRIORITY, HEARTBEAT_TIMEOUT, ACTIVE_STATES

# 轮询间隔（秒），50ms 响应足够快，人眼感觉不到延迟
POLL_INTERVAL = 0.05

# 进程 ID 文件，用于检测守护进程是否在运行
PID_FILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_traffic_light_daemon.pid")


def read_all_states() -> dict:
    """
    读取状态目录下所有 session 的状态文件。

    文件格式：JSON，包含 state（状态名）和 timestamp（时间戳）
    心跳超时机制：活跃状态（working/thinking/model/alert）如果超过
    HEARTBEAT_TIMEOUT 秒没有更新，自动降级为 idle。

    Returns:
        {session_id: state_name} 的字典
    """
    states = {}
    if not os.path.exists(STATE_DIR):
        return states
    now = time.time()
    for name in os.listdir(STATE_DIR):
        if name.endswith(".tmp"):
            continue  # 跳过临时文件
        path = os.path.join(STATE_DIR, name)
        try:
            with open(path, "r") as f:
                raw = f.read().strip()

            # 兼容旧格式（纯文本）和新格式（JSON）
            if raw.startswith("{"):
                data = json.loads(raw)
                state = data.get("state", "")
                ts = data.get("ts", 0)
            else:
                state = raw
                ts = 0  # 旧格式没有时间戳，不超时

            if state not in COMMANDS:
                continue

            # 心跳超时检测：活跃状态超过 TIMEOUT 秒没更新 → 降级为 idle
            if state in ACTIVE_STATES and ts > 0:
                if now - ts > HEARTBEAT_TIMEOUT:
                    state = "idle"  # 会话可能已崩溃，降级

            states[name] = state
        except (OSError, json.JSONDecodeError):
            continue  # 文件可能刚被删除或格式错误，忽略
    return states


def highest_priority(states: dict) -> str:
    """
    从所有终端的状态中，选出优先级最高的那个。

    优先级规则定义在 config.py 的 PRIORITY 中：
    alert(1) > working(2) > model(3) > thinking(4) > idle(5) > off(6)

    例如：终端 A 在干活（working=2），终端 B 需要授权（alert=1）
          → 返回 "alert"，因为 1 < 2

    Returns:
        优先级最高的状态名，没有状态时返回 "off"
    """
    if not states:
        return "off"
    return min(states.values(), key=lambda s: PRIORITY.get(s, 99))


def main():
    # 写入 PID 文件，让 start_daemon.py 可以检测我们是否在运行
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    # 确保状态目录存在
    os.makedirs(STATE_DIR, exist_ok=True)

    # ----------------------------------------------------------
    # 打开串口
    # ----------------------------------------------------------
    # dsrdtr=False + 手动设置 dtr/rts = False，防止触发 ESP32C3 复位
    # 这是踩坑记录第 3 条的经验
    print(f"正在打开 {SERIAL_PORT}（自动检测）...", flush=True)
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1, dsrdtr=False)
        ser.dtr = False
        ser.rts = False
    except serial.SerialException as e:
        print(f"无法打开 {SERIAL_PORT}: {e}", flush=True)
        sys.exit(1)

    print("守护进程已启动。", flush=True)

    # ----------------------------------------------------------
    # 主循环：轮询状态文件，发送串口指令
    # ----------------------------------------------------------
    last_cmd = None  # 上一次发送的指令，避免重复发送
    try:
        while True:
            # 1. 读取所有终端的状态
            states = read_all_states()

            # 2. 选出优先级最高的状态
            best = highest_priority(states)

            # 3. 映射到串口指令
            cmd = COMMANDS.get(best, "O")

            # 4. 只有状态变化时才发送（减少串口流量）
            if cmd != last_cmd:
                ser.write(cmd.encode("ascii"))
                ser.flush()
                last_cmd = cmd

            # 5. 等待下一次轮询
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        pass  # Ctrl+C 正常退出
    finally:
        # ----------------------------------------------------------
        # 清理：关闭串口，删除 PID 文件
        # ----------------------------------------------------------
        try:
            ser.write(COMMANDS["off"].encode("ascii"))  # 关灯
            ser.flush()
        except Exception:
            pass
        ser.close()
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
