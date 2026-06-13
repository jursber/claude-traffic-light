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
import sys
import traceback
import logging
import atexit

from claude_tl.config import COMMANDS, STATE_DIR, PRIORITY
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
            # BaseException 捕获包括 SystemExit、KeyboardInterrupt 在内的一切异常
            log.error("致命异常 (%s):\n%s", type(e).__name__, traceback.format_exc())
            if link:
                try:
                    link.close()
                except Exception:
                    pass
            time.sleep(ERROR_RETRY_INTERVAL)


if __name__ == "__main__":
    main()
