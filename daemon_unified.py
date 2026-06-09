"""
统一守护进程 - 支持 Claude Code 和 OpenAI Codex

功能：
  1. 根据 active_agent.json 配置确定当前激活的 agent
  2. 读取对应 agent 的状态目录
  3. 通过串口发送指令给 ESP32C3

容错设计：
  - 外层无限重启循环
  - 串口断开自动重连
  - 单次循环出错不影响下一次
  - 日志写入文件
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
import msvcrt

# 添加项目目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import ESP32_VID, BAUD_RATE, COMMANDS, PRIORITY

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

# ============================================================
# 配置常量
# ============================================================
POLL_INTERVAL = 0.05
RECONNECT_INTERVAL = 2
ERROR_RETRY_INTERVAL = 1
STATE_FILE_TTL = 1800  # 30 分钟

# 进程 ID 文件
PID_FILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_traffic_light_daemon.pid")

# 文件锁文件
LOCK_FILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_traffic_light_daemon.lock")

# 配置文件
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "active_agent.json")


def load_config():
    """加载 active_agent.json 配置"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"active": "claude", "agents": {}}


def get_state_dir():
    """根据当前激活的 agent 获取状态目录"""
    config = load_config()
    active = config.get("active", "claude")
    agents = config.get("agents", {})

    if active in agents:
        state_dir_name = agents[active].get("state_dir", "cc_tl_states")
    else:
        state_dir_name = "cc_tl_states"

    return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", state_dir_name)


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
    state_dir = get_state_dir()
    states = {}
    if not os.path.exists(state_dir):
        return states

    now = time.time()
    try:
        files = os.listdir(state_dir)
    except OSError:
        return states

    # 检查 _global_off 文件（10 秒内有效）
    global_off_path = os.path.join(state_dir, "_global_off")
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
                        os.remove(os.path.join(state_dir, name))
                    except OSError:
                        pass
                return {"_global_off": "off"}
        except (OSError, json.JSONDecodeError):
            pass

    # 读取所有 session 状态文件
    for name in files:
        if name.endswith(".tmp") or name == "_last_session":
            continue
        path = os.path.join(state_dir, name)
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


def acquire_lock():
    """
    用文件锁确保单实例。返回锁文件描述符（保持打开），或 None（已有实例）。
    """
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return fd
    except (IOError, OSError):
        return None


def main():
    """主入口：外层无限重启循环，保证进程永远不退出。"""

    # 单实例检查：用文件锁确保只有一个 daemon 运行
    lock_fd = acquire_lock()
    if lock_fd is None:
        sys.exit(0)

    log.info("守护进程启动, PID=%d", os.getpid())

    # 注册退出日志
    atexit.register(lambda: log.warning("守护进程退出, PID=%d", os.getpid()))

    # 写入 PID 文件
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    # 确保状态目录存在
    state_dir = get_state_dir()
    os.makedirs(state_dir, exist_ok=True)

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
            log.error("致命异常 (%s):\n%s", type(e).__name__, traceback.format_exc())
            if ser:
                try:
                    ser.close()
                except Exception:
                    pass
            time.sleep(ERROR_RETRY_INTERVAL)


if __name__ == "__main__":
    main()
