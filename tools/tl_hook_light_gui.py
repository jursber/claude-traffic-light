#!/usr/bin/env python3
"""
红绿灯 Hook × 灯光效果配置台（Tkinter）

- Tab「基础设置」：串口、测试模式、与固件一致的绿/黄/红 + v1 扩展帧试发。
- Tab「Claude」「Codex」：按 hook_light_catalog 列出事件行，可配灯效/通道/优先级；配置存 config/tl_hook_light_gui.json。

用法（仓库根目录）:
  python tools/tl_hook_light_gui.py
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from tkinter import BOTH, LEFT, StringVar, TclError, W, X, messagebox, ttk
import tkinter as tk

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import serial
import serial.tools.list_ports

from claude_tl.config import BAUD_RATE, ESP32_VID
from claude_tl.switch_agent import load_config, switch_agent
from claude_tl.hook_light_catalog import (
    CLAUDE_HOOK_CATALOG,
    CODEX_HOOK_CATALOG,
    HookCatalogEntry,
)
from claude_tl.vibelight.protocol import (
    MODE_BREATH,
    MODE_OFF,
    MODE_SOLID,
    MODE_SYNC_BLINK,
    MASK_G,
    MASK_R,
    MASK_Y,
    PERIOD_MAX_MS,
    PERIOD_MIN_MS,
    build_set_lighting_frame,
)

CONFIG_PATH = _ROOT / "config" / "tl_hook_light_gui.json"
TEST_MODE_FLAG = _ROOT / "config" / ".gui_serial_test_mode"

EFFECT_LABELS = ("无", "常亮", "闪烁", "呼吸")
EFFECT_TO_KEY = {"无": "none", "常亮": "solid", "闪烁": "blink", "呼吸": "breath"}
KEY_TO_LABEL = {v: k for k, v in EFFECT_TO_KEY.items()}


def find_esp_ports() -> list[str]:
    ports: list[str] = []
    for p in serial.tools.list_ports.comports():
        if p.vid == ESP32_VID or "USB" in (p.description or ""):
            ports.append(p.device)
    if not ports:
        ports = [p.device for p in serial.tools.list_ports.comports()]
    return sorted(set(ports))


def _clamp_period_ms(v: int, default: int) -> int:
    if v <= 0:
        return default
    return max(PERIOD_MIN_MS, min(PERIOD_MAX_MS, v))


class ScrollableRows(ttk.Frame):
    """Canvas + 内层 Frame，用于 Hook 列表。"""

    def __init__(self, parent: tk.Misc, **kw):
        super().__init__(parent, **kw)
        self._canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self._scroll = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._inner = ttk.Frame(self._canvas)
        self._inner.bind(
            "<Configure>",
            lambda _e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._win_id = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._canvas.bind("<Configure>", self._on_canvas_cfg)
        self._canvas.configure(yscrollcommand=self._scroll.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._scroll.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        def _wheel(e: tk.Event) -> None:
            if sys.platform == "darwin":
                self._canvas.yview_scroll(int(-1 * e.delta), "units")
            else:
                self._canvas.yview_scroll(int(-1 * (e.delta // 120)), "units")

        def _bind_wheel(_e: tk.Event | None = None) -> None:
            self._canvas.bind_all("<MouseWheel>", _wheel)

        def _unbind_wheel(_e: tk.Event | None = None) -> None:
            self._canvas.unbind_all("<MouseWheel>")

        self._canvas.bind("<Enter>", _bind_wheel)
        self._canvas.bind("<Leave>", _unbind_wheel)

    def _on_canvas_cfg(self, e: tk.Event) -> None:
        self._canvas.itemconfig(self._win_id, width=e.width)

    @property
    def body(self) -> ttk.Frame:
        return self._inner


class HookAgentPanel(ttk.Frame):
    """单 Agent：表头 + 可滚动行。"""

    def __init__(self, parent: tk.Misc, title: str, catalog: tuple[HookCatalogEntry, ...]):
        super().__init__(parent, padding=4)
        self._catalog = catalog
        self._rows: list[dict[str, object]] = []

        ttk.Label(self, text=title, font=("TkDefaultFont", 10, "bold")).pack(anchor=W)
        ttk.Label(
            self,
            text="灯光/优先级另存 config/tl_hook_light_gui.json（守护进程读取尚未实现）。●=switch_agent 默认写入 IDE hooks；○=仅作配置参考。",
            foreground="gray",
            wraplength=900,
        ).pack(anchor=W, padx=4, pady=(0, 2))
        head = ttk.Frame(self)
        head.pack(fill=X, pady=(4, 2))
        specs = [
            ("中文名", 14),
            ("Hook 事件名", 22),
            ("灯光", 8),
            ("绿", 4),
            ("黄", 4),
            ("红", 4),
            ("优先级", 6),
        ]
        for i, (lab, w) in enumerate(specs):
            ttk.Label(head, text=lab, width=w).grid(row=0, column=i, padx=2, sticky=W)

        self._scroll = ScrollableRows(self)
        self._scroll.pack(fill=BOTH, expand=True)
        body = self._scroll.body
        for j, ent in enumerate(catalog):
            self._rows.append(self._append_row(body, j, ent))

        bf = ttk.Frame(self)
        bf.pack(fill=X, pady=6)
        ttk.Button(bf, text="保存本页到配置文件", command=self._save_tab).pack(side=LEFT, padx=2)
        ttk.Button(bf, text="从配置文件重载本页", command=self._load_tab).pack(side=LEFT, padx=2)

    def _append_row(self, body: ttk.Frame, row_idx: int, ent: HookCatalogEntry) -> dict[str, object]:
        zh = tk.StringVar(value=ent.zh_default)
        pfx = "● " if ent.wired else "○ "
        mid = ent.event if not ent.matcher else f"{ent.event}\n[{ent.matcher}]"
        ev_text = pfx + mid
        eff = tk.StringVar(value="无")
        vg = tk.BooleanVar(value=False)
        vy = tk.BooleanVar(value=False)
        vr = tk.BooleanVar(value=False)
        prio = tk.StringVar(value=str(min(12, row_idx + 3)))

        ttk.Entry(body, textvariable=zh, width=16).grid(row=row_idx, column=0, padx=2, pady=1, sticky=W)
        ttk.Label(body, text=ev_text, width=24, justify=LEFT).grid(row=row_idx, column=1, padx=2, pady=1, sticky=W)
        ttk.Combobox(
            body,
            textvariable=eff,
            values=EFFECT_LABELS,
            width=8,
            state="readonly",
        ).grid(row=row_idx, column=2, padx=2, pady=1, sticky=W)
        ttk.Checkbutton(body, text="", variable=vg).grid(row=row_idx, column=3, padx=2)
        ttk.Checkbutton(body, text="", variable=vy).grid(row=row_idx, column=4, padx=2)
        ttk.Checkbutton(body, text="", variable=vr).grid(row=row_idx, column=5, padx=2)
        ttk.Combobox(
            body,
            textvariable=prio,
            values=[str(i) for i in range(1, 13)],
            width=4,
            state="readonly",
        ).grid(row=row_idx, column=6, padx=2, sticky=W)

        return {
            "event": ent.event,
            "zh": zh,
            "effect": eff,
            "g": vg,
            "y": vy,
            "r": vr,
            "prio": prio,
        }

    def _row_to_dict(self, r: dict[str, object]) -> dict:
        lab = r["effect"].get()  # type: ignore[union-attr]
        return {
            "event": r["event"],
            "zh": r["zh"].get().strip(),  # type: ignore[union-attr]
            "effect": EFFECT_TO_KEY.get(lab, "none"),
            "mask": (MASK_G if r["g"].get() else 0)  # type: ignore[union-attr]
            | (MASK_Y if r["y"].get() else 0)
            | (MASK_R if r["r"].get() else 0),
            "priority": int(r["prio"].get()),  # type: ignore[union-attr]
        }

    def collect(self) -> list[dict]:
        return [self._row_to_dict(r) for r in self._rows]

    def apply_rows(self, rows: list[dict] | None) -> None:
        if not rows:
            return
        by_ev = {str(x.get("event")): x for x in rows}
        for r in self._rows:
            ev = r["event"]
            d = by_ev.get(ev)
            if not d:
                continue
            r["zh"].set(d.get("zh", ""))  # type: ignore[union-attr]
            key = d.get("effect", "none")
            r["effect"].set(KEY_TO_LABEL.get(key, "无"))  # type: ignore[union-attr]
            m = int(d.get("mask", 0))
            r["g"].set(bool(m & MASK_G))  # type: ignore[union-attr]
            r["y"].set(bool(m & MASK_Y))
            r["r"].set(bool(m & MASK_R))
            p = int(d.get("priority", 6))
            r["prio"].set(str(max(1, min(12, p))))

    def _load_full_doc(self) -> dict:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_tab(self) -> None:
        doc = self._load_full_doc()
        key = "claude" if self._catalog is CLAUDE_HOOK_CATALOG else "codex"
        doc.setdefault("version", 1)
        doc[key] = {"rows": self.collect()}
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
        messagebox.showinfo("保存", f"已写入 {CONFIG_PATH}")

    def _load_tab(self) -> None:
        doc = self._load_full_doc()
        key = "claude" if self._catalog is CLAUDE_HOOK_CATALOG else "codex"
        block = doc.get(key) or {}
        self.apply_rows(block.get("rows"))


class TrafficHookLightApp(ttk.Frame):
    def __init__(self, master: tk.Misc):
        super().__init__(master, padding=6)
        self.pack(fill=BOTH, expand=True)
        self._ser: serial.Serial | None = None
        self._test_mode = tk.BooleanVar(value=False)

        self._duty_g = tk.IntVar(value=255)
        self._duty_y = tk.IntVar(value=255)
        self._duty_r = tk.IntVar(value=255)
        self._blink_period = tk.StringVar(value="800")
        self._breath_period = tk.StringVar(value="2000")

        self._test_g = tk.BooleanVar(value=False)
        self._test_y = tk.BooleanVar(value=False)
        self._test_r = tk.BooleanVar(value=True)
        self._test_mode_radio = tk.StringVar(value="BLINK")

        self._test_disable_children: list[tk.Widget] = []

        self._agent_busy = False
        self._agent_var = tk.StringVar(value=str(load_config().get("active", "claude")))
        self._status = ttk.Label(self, text="就绪", foreground="gray")

        nb = ttk.Notebook(self)
        nb.pack(fill=BOTH, expand=True)
        f0 = ttk.Frame(nb, padding=6)
        f1 = ttk.Frame(nb, padding=6)
        f2 = ttk.Frame(nb, padding=6)
        nb.add(f0, text="基础设置")
        nb.add(f1, text="Claude")
        nb.add(f2, text="Codex")

        self._build_basic_tab(f0)
        self._claude_panel = HookAgentPanel(f1, "Claude Code — Hook 与灯光", CLAUDE_HOOK_CATALOG)
        self._claude_panel.pack(fill=BOTH, expand=True)
        self._codex_panel = HookAgentPanel(f2, "Codex — Hook 与灯光", CODEX_HOOK_CATALOG)
        self._codex_panel.pack(fill=BOTH, expand=True)

        bf = ttk.Frame(self)
        bf.pack(fill=X, pady=4)
        ttk.Button(bf, text="保存全部（基础+Claude+Codex）", command=self._save_all).pack(side=LEFT, padx=2)
        ttk.Button(bf, text="从文件重载全部", command=self._load_all).pack(side=LEFT, padx=2)

        self._status.pack(fill=X)

        self._update_test_lock_file()
        self._load_all()

    def _log(self, s: str) -> None:
        try:
            st = getattr(self, "_status", None)
            if st is not None:
                st.config(text=s)
        except TclError:
            pass

    def _on_agent_change(self) -> None:
        if self._agent_busy:
            return
        want = self._agent_var.get()
        if load_config().get("active", "claude") == want:
            self._log(f"当前已是 {want}")
            return
        self._start_agent_switch(want)

    def _start_agent_switch(self, agent: str) -> None:
        self._agent_busy = True
        self._agent_progress.start(10)
        self._log(f"正在切换 → {agent} …")

        def worker() -> None:
            err: str | None = None
            ok = False
            try:
                ok = switch_agent(agent)
            except Exception as e:
                err = str(e)
            self.after(0, lambda: self._agent_switch_done(ok, err))

        threading.Thread(target=worker, daemon=True).start()

    def _agent_switch_done(self, ok: bool, err: str | None) -> None:
        self._agent_progress.stop()
        self._agent_busy = False
        if err:
            messagebox.showerror("Agent 切换", err)
            self._agent_var.set(str(load_config().get("active", "claude")))
        elif not ok:
            messagebox.showwarning("Agent 切换", "切换未成功（请查看控制台输出）")
            self._agent_var.set(str(load_config().get("active", "claude")))
        else:
            self._log(f"已切换为 {self._agent_var.get()}；请重启 Claude Code / Codex 会话使 hooks 生效")

    def _build_basic_tab(self, f: ttk.Frame) -> None:
        r1 = ttk.Frame(f)
        r1.pack(fill=X, pady=2)
        ag_fr = ttk.Frame(r1)
        ag_fr.pack(side=LEFT)
        ttk.Label(ag_fr, text="Agent").pack(side=LEFT, padx=(0, 4))
        ttk.Radiobutton(
            ag_fr,
            text="Claude",
            variable=self._agent_var,
            value="claude",
            command=self._on_agent_change,
        ).pack(side=LEFT)
        ttk.Radiobutton(
            ag_fr,
            text="Codex",
            variable=self._agent_var,
            value="codex",
            command=self._on_agent_change,
        ).pack(side=LEFT, padx=4)
        self._agent_progress = ttk.Progressbar(r1, mode="indeterminate", length=120)
        self._agent_progress.pack(side=LEFT, padx=8)

        ttk.Separator(r1, orient="vertical").pack(side=LEFT, fill="y", padx=8, pady=2)
        ttk.Label(r1, text="端口").pack(side=LEFT)
        self._port_var = StringVar()
        self._port_combo = ttk.Combobox(r1, textvariable=self._port_var, width=16)
        self._port_combo.pack(side=LEFT, padx=4)
        ttk.Button(r1, text="刷新", command=self._refresh_ports).pack(side=LEFT)
        ttk.Button(r1, text="连接", command=self._serial_connect).pack(side=LEFT, padx=4)
        ttk.Button(r1, text="断开", command=self._serial_disconnect).pack(side=LEFT, padx=4)
        ttk.Checkbutton(
            r1,
            text="测试模式（仅本窗口「发送」写灯；建议停统一守护进程以免抢串口）",
            variable=self._test_mode,
            command=self._on_test_mode_toggle,
        ).pack(side=LEFT, padx=12)
        self._refresh_ports()

        test_lf = ttk.LabelFrame(f, text="测试模式", padding=6)
        test_lf.pack(fill=X, pady=6)
        r2 = ttk.Frame(test_lf)
        r2.pack(fill=X)
        for txt, var in (("绿", self._test_g), ("黄", self._test_y), ("红", self._test_r)):
            cb = ttk.Checkbutton(r2, text=txt, variable=var)
            cb.pack(side=LEFT, padx=4)
            self._test_disable_children.append(cb)
        ttk.Label(r2, text="模式").pack(side=LEFT, padx=(12, 2))
        for val, lab in (
            ("OFF", "全灭"),
            ("SOLID", "常亮"),
            ("BLINK", "同步闪烁"),
            ("BREATH", "呼吸"),
        ):
            rb = ttk.Radiobutton(r2, text=lab, variable=self._test_mode_radio, value=val)
            rb.pack(side=LEFT, padx=2)
            self._test_disable_children.append(rb)
        self._btn_test_send = ttk.Button(r2, text="发送", command=self._test_send)
        self._btn_test_send.pack(side=LEFT, padx=10)
        self._test_disable_children.append(self._btn_test_send)

        r3 = ttk.LabelFrame(f, text="亮度与周期（扩展帧；与测试/后续 hook 驱动共用数值）", padding=6)
        r3.pack(fill=X, pady=4)

        def row_scale(parent: ttk.Frame, label: str, var: tk.IntVar) -> None:
            fr = ttk.Frame(parent)
            fr.pack(fill=X, pady=2)
            ttk.Label(fr, text=label, width=10).pack(side=LEFT)
            sc = ttk.Scale(fr, from_=0, to=255, variable=var, orient="horizontal")
            sc.pack(side=LEFT, fill=X, expand=True, padx=4)
            ttk.Label(fr, textvariable=var, width=4).pack(side=LEFT)

        row_scale(r3, "绿亮度", self._duty_g)
        row_scale(r3, "黄亮度", self._duty_y)
        row_scale(r3, "红亮度", self._duty_r)

        pr = ttk.Frame(r3)
        pr.pack(fill=X, pady=4)
        ttk.Label(pr, text="闪烁周期 ms (int≥0)").pack(side=LEFT)
        self._spin_blink = ttk.Spinbox(pr, from_=0, to=60000, textvariable=self._blink_period, width=8)
        self._spin_blink.pack(side=LEFT, padx=4)
        ttk.Label(pr, text="呼吸周期 ms (int≥0)").pack(side=LEFT, padx=(12, 0))
        self._spin_breath = ttk.Spinbox(pr, from_=0, to=60000, textvariable=self._breath_period, width=8)
        self._spin_breath.pack(side=LEFT, padx=4)

        self._update_test_lock_file()
        self._apply_test_region_state()

    def _on_test_mode_toggle(self) -> None:
        self._update_test_lock_file()
        self._apply_test_region_state()

    def _update_test_lock_file(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self._test_mode.get():
                TEST_MODE_FLAG.write_text("1", encoding="utf-8")
                self._log("测试模式开：已写 config/.gui_serial_test_mode（供后续守护进程识别）")
            else:
                if TEST_MODE_FLAG.exists():
                    TEST_MODE_FLAG.unlink()
                self._log("测试模式关")
        except OSError as e:
            self._log(f"标志文件: {e}")

    def _apply_test_region_state(self) -> None:
        on = self._test_mode.get()
        for w in self._test_disable_children:
            try:
                if on:
                    w.state(["!disabled"])  # type: ignore[attr-defined]
                else:
                    w.state(["disabled"])  # type: ignore[attr-defined]
            except (tk.TclError, AttributeError):
                try:
                    w.configure(state=tk.NORMAL if on else tk.DISABLED)
                except tk.TclError:
                    pass

    def _refresh_ports(self) -> None:
        ps = find_esp_ports()
        self._port_combo["values"] = ps
        if ps and not self._port_var.get():
            self._port_var.set(ps[0])

    def _serial_connect(self) -> None:
        self._serial_disconnect()
        p = self._port_var.get().strip()
        if not p:
            messagebox.showwarning("串口", "请选择端口")
            return
        try:
            self._ser = serial.Serial(p, BAUD_RATE, timeout=0.3, dsrdtr=False)
            self._ser.dtr = False
            self._ser.rts = False
            self._log(f"串口已连接 {p}")
        except OSError as e:
            messagebox.showerror("串口", str(e))

    def _serial_disconnect(self) -> None:
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
            self._log("串口已断开")

    def _send_raw(self, data: bytes) -> bool:
        if not self._ser or not self._ser.is_open:
            messagebox.showwarning("发送", "请先连接串口")
            return False
        if not self._test_mode.get():
            messagebox.showwarning("发送", "请先开启「测试模式」再发送试灯指令")
            return False
        try:
            self._ser.write(data)
            self._ser.flush()
            return True
        except OSError as e:
            self._log(f"串口错误: {e}")
            return False

    def _parse_nonneg_int(self, s: str, default: int) -> int:
        try:
            v = int(str(s).strip())
            return v if v >= 0 else default
        except ValueError:
            return default

    def _test_send(self) -> None:
        mode_map = {"OFF": MODE_OFF, "SOLID": MODE_SOLID, "BLINK": MODE_SYNC_BLINK, "BREATH": MODE_BREATH}
        m = mode_map.get(self._test_mode_radio.get(), MODE_OFF)
        mask = (
            (MASK_G if self._test_g.get() else 0)
            | (MASK_Y if self._test_y.get() else 0)
            | (MASK_R if self._test_r.get() else 0)
        )
        if m != MODE_OFF and mask == 0:
            messagebox.showwarning("测试", "请至少勾选一盏灯（绿/黄/红）")
            return
        bp = self._parse_nonneg_int(self._blink_period.get(), 800)
        rp = self._parse_nonneg_int(self._breath_period.get(), 2000)
        if m == MODE_SYNC_BLINK:
            per = _clamp_period_ms(bp, 800)
        elif m == MODE_BREATH:
            per = _clamp_period_ms(rp, 2000)
        else:
            per = 1000
        dg = max(0, min(255, int(self._duty_g.get())))
        dy = max(0, min(255, int(self._duty_y.get())))
        dr = max(0, min(255, int(self._duty_r.get())))
        frame = build_set_lighting_frame(m, mask, per, dg, dy, dr)
        if self._send_raw(frame):
            self._log(f"测试已发 SET_LIGHTING {frame.hex()}")

    def _save_all(self) -> None:
        doc: dict = {"version": 1}
        doc["basic"] = {
            "port": self._port_var.get().strip(),
            "duty_g": int(self._duty_g.get()),
            "duty_y": int(self._duty_y.get()),
            "duty_r": int(self._duty_r.get()),
            "blink_period_ms": self._parse_nonneg_int(self._blink_period.get(), 800),
            "breath_period_ms": self._parse_nonneg_int(self._breath_period.get(), 2000),
            "test_mode": bool(self._test_mode.get()),
        }
        doc["claude"] = {"rows": self._claude_panel.collect()}
        doc["codex"] = {"rows": self._codex_panel.collect()}
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
        messagebox.showinfo("保存", f"已写入 {CONFIG_PATH}")

    def _load_all(self) -> None:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            doc = {}
        b = doc.get("basic") or {}
        if b.get("port"):
            self._port_var.set(str(b["port"]))
        self._duty_g.set(int(b.get("duty_g", 255)))
        self._duty_y.set(int(b.get("duty_y", 255)))
        self._duty_r.set(int(b.get("duty_r", 255)))
        self._blink_period.set(str(int(b.get("blink_period_ms", 800))))
        self._breath_period.set(str(int(b.get("breath_period_ms", 2000))))
        if "test_mode" in b:
            self._test_mode.set(bool(b["test_mode"]))
        self._update_test_lock_file()
        self._apply_test_region_state()
        self._claude_panel.apply_rows((doc.get("claude") or {}).get("rows"))
        self._codex_panel.apply_rows((doc.get("codex") or {}).get("rows"))
        self._agent_var.set(str(load_config().get("active", "claude")))
        self._log(f"已加载 {CONFIG_PATH}" if doc else "无 tl_hook_light_gui.json，使用默认；已同步 active_agent")


def main() -> None:
    root = tk.Tk()
    root.title("红绿灯 Hook × 灯光配置")
    root.geometry("920x680")
    TrafficHookLightApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
