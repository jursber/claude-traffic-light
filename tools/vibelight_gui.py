#!/usr/bin/env python3
"""
VibeLight 调试控制台 — Tkinter + 串口 / BLE 发送 v1 协议帧与旧版 ASCII。

用法（在仓库根目录）:
  pip install -r requirements.txt
  Windows 无黑框推荐: pythonw tools/vibelight_gui.py
  或双击 tools/vibelight_gui.pyw
  或: python tools/vibelight_gui.py（会先隐藏控制台再脱离；仍建议 pythonw）
"""

from __future__ import annotations

import sys


def _win_detach_console_if_any() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        k = ctypes.windll.kernel32
        u = ctypes.windll.user32
        hwnd = k.GetConsoleWindow()
        if hwnd:
            u.ShowWindow(hwnd, 0)  # SW_HIDE
            k.FreeConsole()
    except Exception:
        pass


_win_detach_console_if_any()

import asyncio
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import BOTH, LEFT, StringVar, TclError, W, X, messagebox, ttk

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import serial
import serial.tools.list_ports

from claude_tl.config import BAUD_RATE, BLE_CHAR_UUID, BLE_DEVICE_NAME, ESP32_VID
from claude_tl.vibelight.protocol import (
    MODE_BREATH,
    MODE_OFF,
    MODE_SOLID,
    MODE_SYNC_BLINK,
    MASK_G,
    MASK_R,
    MASK_Y,
    build_breath_curve_frame,
    build_set_lighting_frame,
)

CURVE_GUI_POINTS = 16


def _try_free_console_win32() -> None:
    _win_detach_console_if_any()


def default_linear_triangle(n: int) -> list[int]:
    """一个周期内线性 0→255→0，与固件 MODE_BREATH 三角包络一致。"""
    if n < 2:
        return [0] * max(8, n)
    out: list[int] = []
    for i in range(n):
        t = i / (n - 1)
        v = t * 2.0 if t <= 0.5 else (1.0 - t) * 2.0
        out.append(max(0, min(255, int(round(v * 255.0)))))
    return out


class BreathCurveEditor(ttk.LabelFrame):
    """可拖拽折线：等分一个周期，纵轴 0～255 视觉亮度（与扩展区 mask/周期/峰值一致）。"""

    ML, MR, MT, MB = 50, 24, 20, 38

    def __init__(self, app: "VibeLightApp"):
        super().__init__(app, text="自定义呼吸曲线（横轴=一个周期，纵轴=亮度）", padding=6)
        self._app = app
        self._n = CURVE_GUI_POINTS
        self._vals = default_linear_triangle(self._n)
        self._drag_i: int | None = None
        self._cw = 560
        self._ch = 220
        self._canvas = tk.Canvas(
            self,
            width=self._cw,
            height=self._ch,
            bg="#f4f4f4",
            highlightthickness=1,
            highlightbackground="#c0c0c0",
        )
        self._canvas.pack(fill=tk.X)
        self._canvas.bind("<Button-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)

        bf = ttk.Frame(self)
        bf.pack(fill=tk.X, pady=4)
        ttk.Button(bf, text="线性三角模板", command=self._preset_linear).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="首尾对齐（闭合）", command=self._preset_close_loop).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="发送曲线帧 (cmd=2)", command=self._send_curve).pack(side=tk.LEFT, padx=8)

        self._redraw()

    def _plot_geom(self) -> tuple[int, int, int, int]:
        self._canvas.update_idletasks()
        w = max(self._cw, int(self._canvas.winfo_width() or self._cw))
        h = max(self._ch, int(self._canvas.winfo_height() or self._ch))
        x0, y0 = self.ML, self.MT
        pw, ph = w - self.ML - self.MR, h - self.MT - self.MB
        if pw < 80:
            pw = 80
        if ph < 60:
            ph = 60
        return x0, y0, pw, ph

    def _ix_to_x(self, i: int, x0: int, pw: int) -> float:
        if self._n <= 1:
            return float(x0)
        return x0 + pw * i / (self._n - 1)

    def _val_to_y(self, v: int, y0: int, ph: int) -> float:
        v = max(0, min(255, v))
        return y0 + ph * (1.0 - v / 255.0)

    def _y_to_val(self, y: float, y0: int, ph: int) -> int:
        t = (y - y0) / float(ph) if ph else 0.0
        v = int(round(255.0 * (1.0 - t)))
        return max(0, min(255, v))

    def _redraw(self) -> None:
        c = self._canvas
        c.delete("all")
        x0, y0, pw, ph = self._plot_geom()
        c.create_rectangle(x0, y0, x0 + pw, y0 + ph, outline="#888888", width=1)
        c.create_text(x0 + pw // 2, y0 + ph + 22, text="时间 →", fill="#555555")
        c.create_text(18, y0 + ph // 2, text="亮\n度", fill="#555555", justify=tk.CENTER)
        for frac, lab in ((0.0, "0"), (0.5, "128"), (1.0, "255")):
            vy = y0 + ph * (1.0 - frac)
            c.create_line(x0, vy, x0 + pw, vy, fill="#e0e0e0", dash=(3, 4))
            c.create_text(x0 - 8, vy, text=lab, anchor=tk.E, fill="#888888", font=("TkDefaultFont", 8))

        pts: list[float] = []
        for i in range(self._n):
            xi = self._ix_to_x(i, x0, pw)
            yi = self._val_to_y(self._vals[i], y0, ph)
            pts.extend((xi, yi))
        if len(pts) >= 4:
            c.create_line(*pts, fill="#1a73e8", width=2, smooth=False)

        r = 7
        for i in range(self._n):
            xi = self._ix_to_x(i, x0, pw)
            yi = self._val_to_y(self._vals[i], y0, ph)
            c.create_oval(xi - r, yi - r, xi + r, yi + r, fill="#ffffff", outline="#1a73e8", width=2, tags=("knot", str(i)))

    def _hit_test(self, ex: float, ey: float) -> int | None:
        x0, y0, pw, ph = self._plot_geom()
        best: int | None = None
        best_d = 1e9
        for i in range(self._n):
            xi = self._ix_to_x(i, x0, pw)
            yi = self._val_to_y(self._vals[i], y0, ph)
            d = (xi - ex) ** 2 + (yi - ey) ** 2
            if d < best_d and abs(xi - ex) < 28:
                best_d = d
                best = i
        if best is not None and best_d <= 22 * 22:
            return best
        return None

    def _on_press(self, e: tk.Event) -> None:
        self._drag_i = self._hit_test(e.x, e.y)

    def _on_drag(self, e: tk.Event) -> None:
        if self._drag_i is None:
            return
        x0, y0, pw, ph = self._plot_geom()
        self._vals[self._drag_i] = self._y_to_val(float(e.y), y0, ph)
        self._redraw()

    def _on_release(self, _e: tk.Event | None = None) -> None:
        self._drag_i = None

    def _preset_linear(self) -> None:
        self._vals = default_linear_triangle(self._n)
        self._redraw()

    def _preset_close_loop(self) -> None:
        if self._n >= 2:
            self._vals[-1] = self._vals[0]
        self._redraw()

    def _send_curve(self) -> None:
        mask = (MASK_G if self._app._mask_g.get() else 0) | (MASK_Y if self._app._mask_y.get() else 0) | (MASK_R if self._app._mask_r.get() else 0)
        try:
            per = int(self._app._period_var.get())
        except ValueError:
            per = 3000
        dg = int(float(self._app._duty_g.get()))
        dy = int(float(self._app._duty_y.get()))
        dr = int(float(self._app._duty_r.get()))
        try:
            frame = build_breath_curve_frame(mask, per, dg, dy, dr, self._vals)
        except ValueError as err:
            messagebox.showerror("曲线", str(err))
            return
        if self._app._transport_send_raw(frame):
            self._app._log_msg(f"已发呼吸曲线帧 len={len(frame)} {frame[:16].hex()}…")


def find_esp_ports():
    ports = []
    for p in serial.tools.list_ports.comports():
        if p.vid == ESP32_VID or "USB" in (p.description or ""):
            ports.append(p.device)
    if not ports:
        ports = [p.device for p in serial.tools.list_ports.comports()]
    return sorted(set(ports))


class VibeLightApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=8)
        self.pack(fill=BOTH, expand=True)
        self._ser: serial.Serial | None = None
        self._ble_client = None
        self._ble_lock = threading.Lock()

        nb = ttk.Notebook(self)
        nb.pack(fill=BOTH, expand=True)
        f_serial = ttk.Frame(nb, padding=6)
        f_ble = ttk.Frame(nb, padding=6)
        nb.add(f_serial, text="USB 串口")
        nb.add(f_ble, text="BLE")

        self._build_serial_tab(f_serial)
        self._build_ble_tab(f_ble)
        self._build_common_controls()

    def _build_serial_tab(self, f):
        row = ttk.Frame(f)
        row.pack(fill=X)
        ttk.Label(row, text="端口").pack(side=LEFT)
        self._port_var = StringVar()
        self._port_combo = ttk.Combobox(row, textvariable=self._port_var, width=18)
        self._port_combo.pack(side=LEFT, padx=4)
        ttk.Button(row, text="刷新", command=self._refresh_ports).pack(side=LEFT)
        ttk.Button(row, text="连接", command=self._serial_connect).pack(side=LEFT, padx=4)
        ttk.Button(row, text="断开", command=self._serial_disconnect).pack(side=LEFT)
        self._refresh_ports()

    def _build_ble_tab(self, f):
        row = ttk.Frame(f)
        row.pack(fill=X)
        ttk.Label(row, text="设备名").pack(side=LEFT)
        self._ble_name_var = StringVar(value=BLE_DEVICE_NAME)
        ttk.Entry(row, textvariable=self._ble_name_var, width=20).pack(side=LEFT, padx=4)
        ttk.Button(row, text="扫描并连接", command=self._ble_connect_async).pack(side=LEFT, padx=4)
        ttk.Button(row, text="断开", command=self._ble_disconnect).pack(side=LEFT)

    def _build_common_controls(self):
        cf = ttk.LabelFrame(self, text="扩展协议 v1（SET_LIGHTING）", padding=6)
        cf.pack(fill=X, pady=6)

        mrow = ttk.Frame(cf)
        mrow.pack(fill=X)
        self._mask_g = tk.BooleanVar(value=True)
        self._mask_y = tk.BooleanVar(value=False)
        self._mask_r = tk.BooleanVar(value=False)
        ttk.Checkbutton(mrow, text="绿", variable=self._mask_g).pack(side=LEFT)
        ttk.Checkbutton(mrow, text="黄", variable=self._mask_y).pack(side=LEFT)
        ttk.Checkbutton(mrow, text="红", variable=self._mask_r).pack(side=LEFT)

        ttk.Label(cf, text="模式").pack(anchor=W)
        self._mode_var = StringVar(value="SOLID")
        mfr = ttk.Frame(cf)
        mfr.pack(fill=X)
        for val, lab in (
            ("OFF", "全灭"),
            ("SOLID", "常亮"),
            ("BLINK", "同步闪烁"),
            ("BREATH", "呼吸"),
        ):
            ttk.Radiobutton(mfr, text=lab, variable=self._mode_var, value=val).pack(side=LEFT, padx=2)

        prow = ttk.Frame(cf)
        prow.pack(fill=X, pady=4)
        ttk.Label(prow, text="周期 ms").pack(side=LEFT)
        self._period_var = StringVar(value="1000")
        ttk.Spinbox(prow, from_=50, to=60000, textvariable=self._period_var, width=8).pack(side=LEFT, padx=4)

        srow = ttk.Frame(cf)
        srow.pack(fill=X)
        ttk.Label(srow, text="绿亮度").grid(row=0, column=0, sticky=W)
        self._duty_g = ttk.Scale(srow, from_=0, to=255, orient="horizontal")
        self._duty_g.grid(row=0, column=1, sticky="ew")
        ttk.Label(srow, text="黄亮度").grid(row=1, column=0, sticky=W)
        self._duty_y = ttk.Scale(srow, from_=0, to=255, orient="horizontal")
        self._duty_y.grid(row=1, column=1, sticky="ew")
        ttk.Label(srow, text="红亮度").grid(row=2, column=0, sticky=W)
        self._duty_r = ttk.Scale(srow, from_=0, to=255, orient="horizontal")
        self._duty_r.grid(row=2, column=1, sticky="ew")
        srow.columnconfigure(1, weight=1)

        ttk.Button(cf, text="发送扩展帧", command=self._send_proto).pack(pady=4)

        self._curve_editor = BreathCurveEditor(self)
        self._curve_editor.pack(fill=X, pady=4)

        lf = ttk.LabelFrame(self, text="旧版 ASCII（单字节）", padding=6)
        lf.pack(fill=X, pady=4)
        bfr = ttk.Frame(lf)
        bfr.pack(fill=X)
        for lab, ch in (
            ("G 绿闪", "G"),
            ("g 绿常", "g"),
            ("y 黄闪", "y"),
            ("Y 黄常", "Y"),
            ("r 红闪", "r"),
            ("R 红常", "R"),
            ("O 全灭", "O"),
        ):
            ttk.Button(bfr, text=lab, command=lambda c=ch: self._send_ascii(c)).pack(side=LEFT, padx=2)

        pf = ttk.LabelFrame(self, text="一键预设（扩展帧）", padding=6)
        pf.pack(fill=X, pady=4)
        pgrid = ttk.Frame(pf)
        pgrid.pack(fill=X)
        presets = [
            ("三灯常亮(满)", MODE_SOLID, MASK_G | MASK_Y | MASK_R, 1000, 255, 255, 255),
            ("三灯同步闪", MODE_SYNC_BLINK, MASK_G | MASK_Y | MASK_R, 800, 220, 220, 220),
            ("三灯呼吸", MODE_BREATH, MASK_G | MASK_Y | MASK_R, 3600, 200, 200, 200),
            ("仅红呼吸", MODE_BREATH, MASK_R, 3000, 0, 0, 255),
            ("黄绿警闪", MODE_SYNC_BLINK, MASK_G | MASK_Y, 400, 255, 180, 0),
        ]
        for c, (name, mode, mask, per, dg, dy, dr) in enumerate(presets):
            ttk.Button(
                pgrid,
                text=name,
                command=lambda m=mode, k=mask, p=per, g=dg, y=dy, r=dr: self._send_preset(m, k, p, g, y, r),
            ).grid(row=0, column=c, padx=2)

        self._log = ttk.Label(self, text="就绪", foreground="gray")
        self._log.pack(fill=X, pady=4)

    def _log_msg(self, s: str):
        try:
            self._log.config(text=s)
        except TclError:
            pass

    def _refresh_ports(self):
        ps = find_esp_ports()
        self._port_combo["values"] = ps
        if ps and not self._port_var.get():
            self._port_var.set(ps[0])

    def _serial_connect(self):
        self._serial_disconnect()
        p = self._port_var.get().strip()
        if not p:
            messagebox.showwarning("串口", "请选择端口")
            return
        try:
            self._ser = serial.Serial(p, BAUD_RATE, timeout=0.3, dsrdtr=False)
            self._ser.dtr = False
            self._ser.rts = False
            self._log_msg(f"串口已连接 {p}")
        except OSError as e:
            messagebox.showerror("串口", str(e))

    def _serial_disconnect(self):
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
            self._log_msg("串口已断开")

    def _transport_send_raw(self, data: bytes) -> bool:
        if self._ser and self._ser.is_open:
            try:
                self._ser.write(data)
                self._ser.flush()
                return True
            except Exception as e:
                self._log_msg(f"串口错误: {e}")
                return False
        with self._ble_lock:
            cli = self._ble_client
        if cli is not None and cli.is_connected:
            try:

                async def _w():
                    await cli.write_gatt_char(BLE_CHAR_UUID, data, response=False)

                asyncio.run(_w())
                return True
            except Exception as e:
                self._log_msg(f"BLE 错误: {e}")
                return False
        messagebox.showwarning("发送", "请先连接 USB 串口或 BLE")
        return False

    def _send_proto(self):
        mode_map = {"OFF": MODE_OFF, "SOLID": MODE_SOLID, "BLINK": MODE_SYNC_BLINK, "BREATH": MODE_BREATH}
        m = mode_map.get(self._mode_var.get(), MODE_SOLID)
        mask = (MASK_G if self._mask_g.get() else 0) | (MASK_Y if self._mask_y.get() else 0) | (MASK_R if self._mask_r.get() else 0)
        try:
            per = int(self._period_var.get())
        except ValueError:
            per = 1000
        dg = int(float(self._duty_g.get()))
        dy = int(float(self._duty_y.get()))
        dr = int(float(self._duty_r.get()))
        frame = build_set_lighting_frame(m, mask, per, dg, dy, dr)
        if self._transport_send_raw(frame):
            self._log_msg(f"已发扩展帧 {frame.hex()}")

    def _send_preset(self, mode, mask, per, dg, dy, dr):
        frame = build_set_lighting_frame(mode, mask, per, dg, dy, dr)
        if self._transport_send_raw(frame):
            self._log_msg(f"预设已发 {frame.hex()}")

    def _send_ascii(self, c: str):
        if self._transport_send_raw(c.encode("ascii")):
            self._log_msg(f"已发 ASCII {c!r}")

    def _ble_connect_async(self):
        name = self._ble_name_var.get().strip() or BLE_DEVICE_NAME

        def worker():
            try:
                from bleak import BleakClient, BleakScanner

                async def run():
                    dev = await BleakScanner.find_device_by_name(name, timeout=15.0)
                    if dev is None:
                        self.after(0, lambda: messagebox.showerror("BLE", f"未找到 {name}"))
                        return
                    client = BleakClient(dev)
                    await client.connect()
                    if not client.is_connected:
                        self.after(0, lambda: messagebox.showerror("BLE", "连接失败"))
                        return
                    with self._ble_lock:
                        self._ble_client = client
                    self.after(0, lambda: self._log_msg(f"BLE 已连接 {dev.address}"))

                asyncio.run(run())
            except Exception:
                err = traceback.format_exc()
                self.after(0, lambda e=err: messagebox.showerror("BLE", e))

        threading.Thread(target=worker, daemon=True).start()

    def _ble_disconnect(self):
        c = None
        with self._ble_lock:
            c = self._ble_client
            self._ble_client = None
        if c is None:
            self._log_msg("BLE 未连接")
            return

        async def _d():
            if c.is_connected:
                await c.disconnect()

        try:
            asyncio.run(_d())
        except Exception:
            pass
        self._log_msg("BLE 已断开")


def main():
    _try_free_console_win32()
    root = tk.Tk()
    root.title("VibeLight 控制台")
    root.geometry("820x720")
    VibeLightApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
