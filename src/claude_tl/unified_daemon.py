"""
统一守护进程 - 支持 Claude Code 和 OpenAI Codex

功能：
  1. 根据 active_agent.json 配置确定当前激活的 agent
  2. 读取对应 agent 的状态目录
  3. 通过 USB 串口或 BLE 向 ESP32-C3 发送灯控指令

容错设计：
  - 外层无限重启循环
  - 硬件连接断开自动重连
  - 单次循环出错不影响下一次
  - 日志写入文件
"""

import os
import time
import json
import sys
import traceback
import logging
import atexit
import msvcrt

from claude_tl._paths import active_agent_path
from claude_tl.config import COMMANDS, PRIORITY
from claude_tl.tl_transport import send_cmd as transport_send, transport_mode, wait_for_transport

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
ACTIVE_STATE_TTL = 3600  # 1 hour
ACTIVE_STATES = {"model", "working", "thinking"}
STATE_FILE_TTL = 1800  # 30 分钟

# 进程 ID 文件
PID_FILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_traffic_light_daemon.pid")

# 文件锁文件
LOCK_FILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_traffic_light_daemon.lock")

# 配置文件（仓库根或 CC_TL_HOME）
CONFIG_FILE = str(active_agent_path())


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


def write_state_file(path: str, state: str, ts: float = None) -> None:
    """Write a state file atomically."""
    data = json.dumps({"state": state, "ts": ts or time.time()})
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(data)
    os.replace(tmp, path)


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
                try:
                    ts = os.path.getmtime(path)
                except OSError:
                    ts = 0

            # 过期清理：超过 30 分钟未更新的非 off 文件自动删除
            if state in ACTIVE_STATES and ts > 0 and now - ts > ACTIVE_STATE_TTL:
                log.info("Session %s state %s expired after %.0fs; falling back to idle", name, state, now - ts)
                state = "idle"
                ts = now
                try:
                    write_state_file(path, state, ts)
                except OSError:
                    pass

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


def run_once(link):
    """
    主循环：轮询状态文件，向硬件发送指令（USB 串口或 BLE）。
    正常情况下永远不会返回（无限循环）。
    连接断开时抛出 ConnectionError，由外层处理重连。
    """
    last_cmd = None
    while True:
        try:
            states = read_all_states()
            best = highest_priority(states)
            cmd = COMMANDS.get(best, "O")

            if cmd != last_cmd:
                link, last_cmd = transport_send(link, cmd, last_cmd)
                if link is None:
                    raise ConnectionError("硬件连接断开")

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
        link = None
        try:
            link = wait_for_transport(RECONNECT_INTERVAL)
            log.info("硬件已连接 (transport=%s)", transport_mode())

            run_once(link)

        except ConnectionError:
            log.warning("硬件断开，等待重连...")
            if link:
                try:
                    link.close()
                except Exception:
                    pass
            time.sleep(RECONNECT_INTERVAL)

        except BaseException as e:
            log.error("致命异常 (%s):\n%s", type(e).__name__, traceback.format_exc())
            if link:
                try:
                    link.close()
                except Exception:
                    pass
            time.sleep(ERROR_RETRY_INTERVAL)


if __name__ == "__main__":
    main()
