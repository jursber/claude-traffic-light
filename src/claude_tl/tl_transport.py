"""
硬件传输层：USB 串口（默认）或 BLE GATT（CC_TL_TRANSPORT=ble）。

BLE 在独立线程里维持连接并处理写入，与 daemon 主线程的同步接口对接。
"""

from __future__ import annotations

import asyncio
import logging
import os
import queue
import threading
import time
from typing import Optional

import serial
import serial.tools.list_ports

from claude_tl.config import BAUD_RATE, BLE_CHAR_UUID, BLE_DEVICE_NAME, ESP32_VID

log = logging.getLogger("tl_transport")


def transport_mode() -> str:
    """读取 CC_TL_TRANSPORT；在极少数 Windows 环境下 os.environ 访问可能抛 OSError(WinError 87)。"""
    try:
        v = os.environ.get("CC_TL_TRANSPORT", "serial")
    except OSError:
        return "serial"
    if not v:
        return "serial"
    return str(v).lower().strip() or "serial"


def find_esp32_port() -> Optional[str]:
    for port in serial.tools.list_ports.comports():
        if port.vid == ESP32_VID:
            return port.device
    return None


def open_serial(port: str) -> serial.Serial:
    ser = serial.Serial(port, BAUD_RATE, timeout=1, dsrdtr=False)
    ser.dtr = False
    ser.rts = False
    return ser


class SerialLink:
    """USB 串口，行为与原先 daemon 内联逻辑一致。"""

    def __init__(self, ser: serial.Serial) -> None:
        self._ser = ser

    def wait_connected(self) -> None:
        return None

    def send_raw(self, data: bytes) -> bool:
        try:
            self._ser.write(data)
            self._ser.flush()
            return True
        except (serial.SerialException, OSError):
            return False

    def send(self, cmd: str) -> bool:
        return self.send_raw(cmd.encode("ascii"))

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass


class BleLink:
    """
    通过 bleak 连接 CC-TrafficLight，向可写特征发送单字节命令。
    内部 asyncio 循环跑在单独线程中。
    """

    def __init__(self) -> None:
        self._name = BLE_DEVICE_NAME
        self._char_uuid = BLE_CHAR_UUID
        self._cmd_queue: queue.Queue[bytes] = queue.Queue(maxsize=32)
        self._connected = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._import_error: Optional[str] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._thread_main, name="ble-tl", daemon=True)
        self._thread.start()

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run_loop())
        finally:
            loop.close()

    async def _run_loop(self) -> None:
        try:
            from bleak import BleakClient, BleakScanner
        except ImportError as e:
            self._import_error = "请安装 bleak: pip install bleak — %s" % e
            log.error(self._import_error)
            return

        backoff = 2  # 初始重连间隔（秒）
        BACKOFF_MAX = 30  # 最大退避间隔
        BACKOFF_FACTOR = 2  # 退避倍数

        while not self._stop.is_set():
            try:
                device = await BleakScanner.find_device_by_name(self._name, timeout=20.0)
                if device is None:
                    log.info("BLE 扫描未找到设备名 %s，%ds 后重试", self._name, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * BACKOFF_FACTOR, BACKOFF_MAX)
                    continue

                async with BleakClient(device, timeout=30.0) as client:
                    if not client.is_connected:
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * BACKOFF_FACTOR, BACKOFF_MAX)
                        continue
                    self._drain_queue()
                    self._connected.set()
                    backoff = 2  # 连接成功，重置退避
                    log.info("BLE 已连接: %s (%s)", self._name, device.address)

                    loop = asyncio.get_event_loop()

                    while client.is_connected and not self._stop.is_set():
                        cmd = await loop.run_in_executor(None, self._blocking_get_cmd)
                        if cmd is None:
                            continue
                        try:
                            await client.write_gatt_char(
                                self._char_uuid,
                                cmd,
                                response=False,
                            )
                        except Exception as ex:
                            log.warning("BLE 写入失败，将重连: %s", ex)
                            break
            except asyncio.CancelledError:
                raise
            except Exception as ex:
                log.warning("BLE 会话异常: %s", ex)
            finally:
                self._connected.clear()
                self._drain_queue()

            if not self._stop.is_set():
                log.info("BLE 断开，%ds 后重连…", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * BACKOFF_FACTOR, BACKOFF_MAX)

    def _blocking_get_cmd(self) -> Optional[bytes]:
        try:
            return self._cmd_queue.get(timeout=0.15)
        except queue.Empty:
            return None

    def _drain_queue(self) -> None:
        while True:
            try:
                self._cmd_queue.get_nowait()
            except queue.Empty:
                break

    def wait_connected(self) -> None:
        while True:
            if self._import_error:
                raise RuntimeError(self._import_error)
            if self._thread and not self._thread.is_alive() and not self._connected.is_set():
                raise RuntimeError("BLE 连接线程已退出，请查看日志中的错误信息")
            if self._connected.wait(timeout=1.0):
                return
            log.info("等待 BLE 设备 %s ...", self._name)

    def send_raw(self, data: bytes) -> bool:
        if not self._connected.is_set():
            return False
        try:
            self._cmd_queue.put_nowait(data)
            return True
        except queue.Full:
            log.warning("BLE 命令队列已满，丢弃")
            return False

    def send(self, cmd: str) -> bool:
        return self.send_raw(cmd.encode("ascii"))

    def close(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)


def wait_for_serial_link(reconnect_interval: float) -> SerialLink:
    while True:
        port = find_esp32_port()
        if port is not None:
            try:
                return SerialLink(open_serial(port))
            except Exception:
                pass
        time.sleep(reconnect_interval)


def wait_for_transport(reconnect_interval: float):
    """
    阻塞直到有可用的传输对象。
    - serial: 与原先一致，等到 USB 串口出现
    - ble: 后台线程开始扫描/连接，本函数等到首次 GATT 连接成功
    """
    mode = transport_mode()
    if mode == "ble":
        link = BleLink()
        link.start()
        link.wait_connected()
        return link
    return wait_for_serial_link(reconnect_interval)


def send_cmd(link, cmd: str, last_cmd: Optional[str]):
    """
    发送单字符命令。与原先 daemon 语义一致：
    - 若 cmd 与 last_cmd 相同则跳过
    - 失败时返回 (None, last_cmd) 表示需重连
    """
    if cmd == last_cmd:
        return link, last_cmd
    if link.send(cmd):
        return link, cmd
    try:
        link.close()
    except Exception:
        pass
    return None, last_cmd
