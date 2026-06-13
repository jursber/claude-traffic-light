"""
Windows 服务版本的守护进程

运行在 Session 0，完全独立于用户会话。
关闭窗口、注销用户都不会影响服务运行。

安装：以管理员身份运行 python daemon_service.py install
启动：python daemon_service.py start
停止：python daemon_service.py stop
卸载：python daemon_service.py remove
"""

import win32serviceutil
import win32service
import win32event
import servicemanager
import os
import sys
import time

# 将项目目录添加到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SERIAL_PORT, BAUD_RATE, COMMANDS, STATE_DIR, PRIORITY


class TrafficLightDaemon(win32serviceutil.ServiceFramework):
    """
    Windows 服务：红绿灯守护进程

    功能：
    1. 打开串口，保持连接
    2. 每 50ms 读取所有 session 的状态文件
    3. 按优先级选出最紧急的状态
    4. 通过串口发送指令给 ESP32C3
    """

    _svc_name_ = "ClaudeTrafficLight"
    _svc_display_name_ = "Claude Traffic Light Daemon"
    _svc_description_ = "Claude Code 红绿灯守护进程 - 控制 ESP32C3 硬件灯光"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.running = True

    def SvcStop(self):
        """服务停止时调用。"""
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.running = False
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        """服务启动时调用。"""
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )
        self.main()

    def read_all_states(self):
        """读取所有 session 的状态文件。"""
        states = {}
        if not os.path.exists(STATE_DIR):
            return states
        for name in os.listdir(STATE_DIR):
            if name.endswith(".tmp"):
                continue
            path = os.path.join(STATE_DIR, name)
            try:
                with open(path, "r") as f:
                    state = f.read().strip()
                if state in COMMANDS:
                    states[name] = state
            except OSError:
                continue
        return states

    def highest_priority(self, states):
        """选出优先级最高的状态。"""
        if not states:
            return "off"
        return min(states.values(), key=lambda s: PRIORITY.get(s, 99))

    def main(self):
        """主循环。"""
        import serial

        # 确保状态目录存在
        os.makedirs(STATE_DIR, exist_ok=True)

        # 等待串口可用
        ser = None
        while self.running:
            try:
                ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1, dsrdtr=False)
                ser.dtr = False
                ser.rts = False
                break
            except serial.SerialException:
                time.sleep(5)  # 串口不可用，等待重试

        if not ser:
            return

        # 主循环
        last_cmd = None
        while self.running:
            try:
                states = self.read_all_states()
                best = self.highest_priority(states)
                cmd = COMMANDS.get(best, "O")

                if cmd != last_cmd:
                    ser.write(cmd.encode("ascii"))
                    ser.flush()
                    last_cmd = cmd

                # 等待 50ms 或收到停止信号
                result = win32event.WaitForSingleObject(self.stop_event, 50)
                if result == win32event.WAIT_OBJECT_0:
                    break

            except Exception:
                time.sleep(1)  # 出错后等待重试

        # 清理
        try:
            ser.write(COMMANDS["off"].encode("ascii"))
            ser.flush()
        except Exception:
            pass
        ser.close()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # 作为服务启动
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(TrafficLightDaemon)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        # 命令行操作
        win32serviceutil.HandleCommandLine(TrafficLightDaemon)
