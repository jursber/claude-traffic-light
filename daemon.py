"""
守护进程 - 红绿灯的核心控制器

容错设计：
  - 外层无限重启循环：任何未捕获异常都不会导致进程退出
  - 串口断开自动重连（USB 拔插、系统休眠唤醒等场景）
  - 单次循环出错不影响下一次
  - 日志写入文件，方便排查问题
"""

import os
import time
import json
import serial
import serial.tools.list_ports
import sys
import traceback
import logging
import atexit

from config import ESP32_VID, BAUD_RATE, COMMANDS, STATE_DIR, PRIORITY

# ============================================================
# 日志配置
# ============================================================
LOG_FILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_traffic_light_daemon.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("daemon")

# 轮询间隔（秒）
POLL_INTERVAL = 0.05

# 串口断开后，扫描重连的间隔（秒）
RECONNECT_INTERVAL = 2

# 出错后等待重试的间隔（秒）
ERROR_RETRY_INTERVAL = 1

# 状态文件过期时间（秒）：超过此时间未更新的文件自动删除
# 解决 session 崩溃后状态文件永远残留的问题
STATE_FILE_TTL = 1800  # 30 分钟

# 进程 ID 文件
PID_FILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_traffic_light_daemon.pid")


def find_esp32_port() -> str:
    """扫描所有 USB 端口，找到 ESP32C3。"""
    for port in serial.tools.list_ports.comports():
        if port.vid == ESP32_VID:
            return port.device
    return None


def open_serial(port: str) -> serial.Serial:
    """打开串口连接，禁用 DTR/RTS 防止触发 ESP32C3 复位。"""
    ser = serial.Serial(port, BAUD_RATE, timeout=1, dsrdtr=False)
    ser.dtr = False
    ser.rts = False
    return ser


def read_all_states() -> dict:
    """
    读取状态目录下所有 session 的状态文件。
    不做任何超时降级，忠实地返回 hook 写入的状态。
    """
    states = {}
    if not os.path.exists(STATE_DIR):
        return states

    now = time.time()
    try:
        files = os.listdir(STATE_DIR)
    except OSError:
        return states

    # 检查 _global_off 文件（10 秒内有效）
    global_off_path = os.path.join(STATE_DIR, "_global_off")
    if "_global_off" in files:
        try:
            with open(global_off_path, "r") as f:
                raw = f.read().strip()
            if raw.startswith("{"):
                data = json.loads(raw)
                ts = data.get("ts", 0)
            else:
                ts = 0
            if now - ts < 10:
                for name in files:
                    if name.endswith(".tmp") or name == "_global_off":
                        continue
                    try:
                        os.remove(os.path.join(STATE_DIR, name))
                    except OSError:
                        pass
                return {"_global_off": "off"}
        except (OSError, json.JSONDecodeError):
            pass

    # 读取所有 session 状态文件
    for name in files:
        if name.endswith(".tmp"):
            continue
        path = os.path.join(STATE_DIR, name)
        try:
            with open(path, "r") as f:
                raw = f.read().strip()
            if raw.startswith("{"):
                data = json.loads(raw)
                state = data.get("state", "")
                ts = data.get("ts", 0)
            else:
                state = raw
                ts = 0

            # 过期清理：超过 30 分钟未更新的非 off 文件自动删除
            if ts > 0 and now - ts > STATE_FILE_TTL and state != "off":
                try:
                    os.remove(path)
                except OSError:
                    pass
                continue

            if state in COMMANDS:
                states[name] = state
        except (OSError, json.JSONDecodeError):
            continue
    return states


def highest_priority(states: dict) -> str:
    """从所有终端的状态中，选出优先级最高的那个。"""
    if not states:
        return "off"
    return min(states.values(), key=lambda s: PRIORITY.get(s, 99))


def connect_serial():
    """尝试连接 ESP32C3，返回 serial 对象或 None。"""
    port = find_esp32_port()
    if port is None:
        return None
    try:
        return open_serial(port)
    except Exception:
        return None


def wait_for_connection():
    """阻塞等待 ESP32C3 连接，返回可用的 serial 对象。"""
    while True:
        ser = connect_serial()
        if ser is not None:
            return ser
        time.sleep(RECONNECT_INTERVAL)


def send_cmd(ser, cmd, last_cmd):
    """发送串口指令。如果断开，返回 (None, last_cmd)。"""
    if cmd == last_cmd:
        return ser, last_cmd
    try:
        ser.write(cmd.encode("ascii"))
        ser.flush()
        return ser, cmd
    except (serial.SerialException, OSError):
        try:
            ser.close()
        except Exception:
            pass
        return None, last_cmd


def run_once(ser):
    """
    主循环：轮询状态文件，发送串口指令。
    正常情况下永远不会返回（无限循环）。
    串口断开时抛出 ConnectionError，由外层处理重连。
    """
    last_cmd = None
    while True:
        try:
            states = read_all_states()
            best = highest_priority(states)
            cmd = COMMANDS.get(best, "O")

            if cmd != last_cmd:
                ser, last_cmd = send_cmd(ser, cmd, last_cmd)
                if ser is None:
                    raise ConnectionError("串口断开")

            time.sleep(POLL_INTERVAL)

        except ConnectionError:
            raise
        except Exception:
            # 单次循环出错，继续下一次
            log.warning("主循环异常（已恢复）: %s", traceback.format_exc())
            time.sleep(POLL_INTERVAL)


def is_another_running():
    """检查是否已有另一个 daemon 在运行。"""
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE, "r") as f:
            old_pid = int(f.read().strip())
        if old_pid == os.getpid():
            return False
        # 检查该 PID 是否还活着
        os.kill(old_pid, 0)  # 不发信号，只检查存在性
        return True
    except (OSError, ValueError):
        return False


def main():
    """主入口：外层无限重启循环，保证进程永远不退出。"""

    # 单实例检查：如果已有 daemon 在运行，直接退出
    if is_another_running():
        sys.exit(0)

    log.info("守护进程启动, PID=%d", os.getpid())

    # 注册退出日志（捕获被外部杀死的情况）
    atexit.register(lambda: log.warning("守护进程退出, PID=%d", os.getpid()))

    # 写入 PID 文件
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    os.makedirs(STATE_DIR, exist_ok=True)

    while True:
        ser = None
        try:
            ser = wait_for_connection()
            log.info("串口已连接")

            run_once(ser)

        except ConnectionError:
            log.warning("串口断开，等待重连...")
            if ser:
                try:
                    ser.close()
                except Exception:
                    pass
            time.sleep(RECONNECT_INTERVAL)

        except BaseException as e:
            # BaseException 捕获包括 SystemExit、KeyboardInterrupt 在内的一切异常
            log.error("致命异常 (%s):\n%s", type(e).__name__, traceback.format_exc())
            if ser:
                try:
                    ser.close()
                except Exception:
                    pass
            time.sleep(ERROR_RETRY_INTERVAL)


if __name__ == "__main__":
    main()
