"""
统一守护进程 - 支持 Claude Code、OpenAI Codex 与 Cursor

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
from claude_tl.gui_proto_ipc import gui_proto_request_path
from claude_tl import light_effects as le
from claude_tl.light_effects import (
    config_mtime as effects_config_mtime,
    config_path as effects_config_path,
)
from claude_tl.proc_util import pid_alive
from claude_tl.tl_transport import find_esp32_port, transport_mode, wait_for_transport

# ============================================================
# 日志配置
# ============================================================
LOG_FILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_traffic_light_daemon.log")
os.makedirs(os.path.dirname(LOG_FILE) or ".", exist_ok=True)

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

# 「活动态」最短显示时间：working/thinking/model/alert 在 agent 干活时常快速交替，
# 不做保护会一闪而过、人眼看不到黄/绿。让活动态至少保持 MIN_ACTIVE_HOLD_S，
# 只有优先级更高(更紧急、PRIORITY 数字更小)的状态才能提前打断。
MIN_ACTIVE_HOLD_S = 0.5
ACTIVE_HOLD_STATES = {"model", "working", "thinking", "alert"}

# 进程 ID 文件
PID_FILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_traffic_light_daemon.pid")

# 文件锁文件
LOCK_FILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_traffic_light_daemon.lock")

# 配置文件（仓库根或 CC_TL_HOME）
CONFIG_FILE = str(active_agent_path())

# 连接状态文件（供 GUI 读取硬件连接状态）
CONN_STATUS_FILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_tl_conn_status.json")


def write_conn_status(connected: bool, transport: str = "", port: str = "") -> None:
    """原子写入连接状态文件，供 GUI 轮询硬件是否在线。"""
    data = {"connected": connected, "transport": transport, "ts": time.time()}
    if port:
        data["port"] = port
    tmp = CONN_STATUS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, CONN_STATUS_FILE)
    except OSError:
        pass


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
                newer_state_exists = False
                for name in files:
                    if name.endswith(".tmp") or name.startswith("_"):
                        continue
                    try:
                        if os.path.getmtime(os.path.join(state_dir, name)) > ts:
                            newer_state_exists = True
                            break
                    except OSError:
                        pass
                if newer_state_exists:
                    try:
                        os.remove(global_off_path)
                    except OSError:
                        pass
                else:
                    for name in files:
                        if name.endswith(".tmp") or name.startswith("_"):
                            continue
                        try:
                            os.remove(os.path.join(state_dir, name))
                        except OSError:
                            pass
                    return {"_global_off": {"state": "off"}}
            else:
                try:
                    os.remove(global_off_path)
                except OSError:
                    pass
        except (OSError, json.JSONDecodeError):
            pass

    # 读取所有 session 状态文件
    for name in files:
        if name.endswith(".tmp") or name.startswith("_"):
            continue
        path = os.path.join(state_dir, name)
        try:
            mode = mask = priority = None
            with open(path, "r") as f:
                raw = f.read().strip()
            if raw.startswith("{"):
                data = json.loads(raw)
                state = data.get("state", "")
                ts = data.get("ts", 0)
                # per-hook 灯效（由 set_state_unified 按 (agent,event) 写入）；可缺省
                if "mode" in data:
                    mode = data.get("mode")
                if "mask" in data:
                    try:
                        mask = int(data.get("mask"))
                    except (TypeError, ValueError):
                        mask = None
                if "priority" in data:
                    try:
                        priority = int(data.get("priority"))
                    except (TypeError, ValueError):
                        priority = None
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
                mode = mask = priority = None
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
                states[name] = {"state": state, "mode": mode, "mask": mask, "priority": priority}
        except (OSError, json.JSONDecodeError):
            continue
    return states


def _entry_priority(entry: dict) -> int:
    """状态条目的优先级：优先用 hook 自配的优先级，否则回退全局 PRIORITY。"""
    pr = entry.get("priority")
    if isinstance(pr, int):
        return pr
    return PRIORITY.get(entry.get("state", "off"), 99)


def highest_priority(states: dict) -> dict:
    """从所有终端的状态条目中，选出优先级最高（数字最小）的那个条目。"""
    if not states:
        return {"state": "off", "mode": None, "mask": None, "priority": None}
    return min(states.values(), key=_entry_priority)


def drain_gui_proto(link) -> bool:
    """
    若存在 GUI 提交的 v1 原始帧（hex），经传输层写出后删除请求文件。
    返回是否尝试发送（成功或失败均删除文件，避免堆积）。
    """
    path = gui_proto_request_path()
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        hexs = (data.get("hex") or "").replace(" ", "")
        raw = bytes.fromhex(hexs)
        if raw and hasattr(link, "send_raw"):
            if not link.send_raw(raw):
                log.warning("GUI proto 帧写入传输层失败")
        elif raw:
            log.warning("当前传输层不支持 send_raw，丢弃 GUI proto")
    except (OSError, json.JSONDecodeError, ValueError):
        log.warning("GUI proto 请求无效:\n%s", traceback.format_exc())
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return True


def _send_frame(link, frame: bytes) -> None:
    """发送一帧；失败则关链路并抛 ConnectionError 交外层重连。"""
    if not link.send_raw(frame):
        try:
            link.close()
        except Exception:
            pass
        raise ConnectionError("硬件连接断开")


def run_once(link):
    """
    主循环：轮询状态文件，按「状态灯效」配置向硬件发送扩展帧（SET_LIGHTING）。
    正常情况下永远不会返回（无限循环）。
    连接断开时抛出 ConnectionError，由外层处理重连。

    灯效来源：
      - per-hook「模式/颜色/优先级」由 set_state_unified 写入状态文件；
      - 全局「周期/亮度」来自 config/tl_hook_light_gui.json 的 basic，支持热重载。
    """
    cfg_path = effects_config_path()
    basic = le.basic_light_params(le.load_gui_doc(cfg_path))
    cfg_mtime = effects_config_mtime(cfg_path)
    log.info("已加载全局灯参 %s: %s", cfg_path, basic)

    last_frame = None
    last_state = "off"
    last_switch = 0.0
    while True:
        try:
            # GUI 试灯（IPC 原始帧）：直接透传一帧；不强制重置，
            # 试灯效果会持续显示到下一次真实状态切换，符合「看一眼灯效」的预期。
            drain_gui_proto(link)

            # 配置热重载：文件 mtime 变动即重载全局灯参（周期/亮度），强制下一帧重发。
            # per-hook 的「模式+颜色+优先级」由 set_state 写进状态文件，无需在此重载。
            m = effects_config_mtime(cfg_path)
            if m != cfg_mtime:
                cfg_mtime = m
                basic = le.basic_light_params(le.load_gui_doc(cfg_path))
                last_frame = None
                log.info("全局灯参已热重载: %s", basic)

            states = read_all_states()
            best = highest_priority(states)
            best_state = best.get("state", "off")

            # 最短显示时间：保证活动态(黄/绿等)至少亮够 MIN_ACTIVE_HOLD_S，
            # 避免 working/thinking 高速交替时一闪而过、人眼看不到。
            # 更紧急的状态(如 alert)优先级更高，仍可立即打断。
            now = time.time()
            if (
                last_state in ACTIVE_HOLD_STATES
                and (now - last_switch) < MIN_ACTIVE_HOLD_S
                and PRIORITY.get(best_state, 99) >= PRIORITY.get(last_state, 99)
                and best_state != last_state
            ):
                time.sleep(POLL_INTERVAL)
                continue

            frame = le.frame_for_runtime(best_state, best.get("mode"), best.get("mask"), basic)

            if frame != last_frame:
                _send_frame(link, frame)
                if best_state != last_state:
                    log.info("灯态切换: %s -> %s (frame=%s)", last_state, best_state, frame.hex())
                last_frame = frame
                last_state = best_state
                last_switch = now

            time.sleep(POLL_INTERVAL)

        except ConnectionError:
            raise
        except Exception:
            # 单次循环出错，继续下一次
            log.warning("主循环异常（已恢复）: %s", traceback.format_exc())
            time.sleep(POLL_INTERVAL)


def acquire_lock():
    """
    用文件锁确保单实例。返回锁文件描述符（保持打开），或 None（已有实例或加锁失败）。
    加锁失败时必须关闭已打开的 fd，否则句柄泄漏且可能让排障更难。
    """
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
    except OSError:
        return None
    try:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return fd
    except (IOError, OSError):
        try:
            os.close(fd)
        except OSError:
            pass
        return None


def _pid_file_points_to_live_process() -> bool:
    """PID 文件存在且对应进程仍存活（用于判断是否真有另一实例在跑）。

    用 proc_util.pid_alive()，绝不能用 os.kill(pid, 0)：Windows 上那会杀死目标进程。
    """
    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return False
    return pid_alive(pid)


def main():
    """主入口：外层无限重启循环，保证进程永远不退出。"""

    # 单实例检查：用文件锁确保只有一个 daemon 运行
    lock_fd = acquire_lock()
    if lock_fd is None and not _pid_file_points_to_live_process():
        # 无存活 PID 却仍占锁：多为崩溃/杀进程后的陈旧状态，删锁后重试一次
        try:
            os.unlink(LOCK_FILE)
        except OSError:
            pass
        time.sleep(0.15)
        lock_fd = acquire_lock()

    if lock_fd is None:
        try:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(
                    f"{ts} [INFO] 守护进程未启动：文件锁已被占用（单实例）。"
                    "若已无灯控在运行，可删除 cc_traffic_light_daemon.lock 后再试。\n"
                )
        except OSError:
            pass
        sys.exit(0)

    # 尽早写入 PID，便于 GUI 在「等硬件」阶段也能判定进程已存在（原子替换，避免读到半截）
    pid_str = str(os.getpid())
    pid_tmp = PID_FILE + ".tmp"
    with open(pid_tmp, "w", encoding="utf-8") as f:
        f.write(pid_str)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    os.replace(pid_tmp, PID_FILE)

    log.info("守护进程启动, PID=%d", os.getpid())

    # 注册退出日志与状态清理
    def _on_exit():
        log.warning("守护进程退出, PID=%d", os.getpid())
        write_conn_status(False, "stopped")

    atexit.register(_on_exit)

    # 确保状态目录存在
    state_dir = get_state_dir()
    os.makedirs(state_dir, exist_ok=True)

    while True:
        link = None
        try:
            mode = transport_mode()
            write_conn_status(False, mode)
            link = wait_for_transport(RECONNECT_INTERVAL)
            port = find_esp32_port() if mode == "serial" else ""
            write_conn_status(True, mode, port or "")
            log.info("硬件已连接 (transport=%s)", mode)

            run_once(link)

        except ConnectionError:
            log.warning("硬件断开，等待重连...")
            write_conn_status(False, transport_mode())
            if link:
                try:
                    link.close()
                except Exception:
                    pass
            time.sleep(RECONNECT_INTERVAL)

        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            log.error("致命异常 (%s):\n%s", type(e).__name__, traceback.format_exc())
            write_conn_status(False, transport_mode())
            if link:
                try:
                    link.close()
                except Exception:
                    pass
            time.sleep(ERROR_RETRY_INTERVAL)


if __name__ == "__main__":
    main()
