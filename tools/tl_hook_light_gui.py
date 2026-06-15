#!/usr/bin/env python3
"""
VibeCodingLight — Hook × 灯光效果配置台（Tkinter）

- Tab「基础设置」：Agent、灯控后台状态、串口刷新/连接/断开（与测试模式无关的一致逻辑）、开机启动、试灯。
- 单实例运行；子进程无控制台窗口；从 cmd 启动时可自动脱离黑框控制台。
- Tab「Claude」「Codex」「Cursor」：按 hook_light_catalog 列出事件行；配置存 config/tl_hook_light_gui.json。

用法（仓库根目录）:
  Windows 推荐无黑窗: pythonw tools/tl_hook_light_gui.py
  或双击 tools/tl_hook_light_gui.pyw（由系统关联 pythonw）
  或: python tools/tl_hook_light_gui.py（会先隐藏控制台再脱离；仍建议 pythonw）
"""

from __future__ import annotations

import sys

# 打包后(PyInstaller)本 exe 同时充当 hook / daemon：在加载 GUI、隐藏控制台之前，
# 先识别 `exe <子命令> [参数]` 并转发到 claude_tl 统一入口，然后退出。
# 必须在 import tkinter 之前完成：既让 hook 进程无需加载 GUI(更快)，也保证 stdin 干净可读。
_CLI_SUBCOMMANDS = frozenset(
    {
        "daemon",
        "daemon-unified",
        "start-daemon",
        "start-daemon-unified",
        "set-state",
        "set-state-unified",
        "set-alert",
        "switch-agent",
    }
)


def _maybe_run_cli_subcommand() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in _CLI_SUBCOMMANDS:
        return
    try:
        from claude_tl.__main__ import main as _cli
    except ModuleNotFoundError:
        from pathlib import Path as _Path

        _src = _Path(__file__).resolve().parents[1] / "src"
        if _src.is_dir() and str(_src) not in sys.path:
            sys.path.insert(0, str(_src))
        from claude_tl.__main__ import main as _cli
    _cli()
    raise SystemExit(0)


_maybe_run_cli_subcommand()


# 必须在 import tkinter / subprocess 等之前执行：用 python.exe 从资源管理器或 cmd 启动时，
# 否则会先出现带 venv 路径标题的黑控制台，再 FreeConsole 也晚一拍。
def _win_detach_console_if_any() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        k = ctypes.windll.kernel32
        u = ctypes.windll.user32
        hwnd = k.GetConsoleWindow()
        if hwnd:
            # 先隐藏再 FreeConsole：仅 FreeConsole 时仍可能在大量 import 期间闪出标题为 python.exe 的黑窗
            u.ShowWindow(hwnd, 0)  # SW_HIDE
            k.FreeConsole()
    except Exception:
        pass


_win_detach_console_if_any()

import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from tkinter import BOTH, LEFT, StringVar, TclError, W, X, filedialog, messagebox, ttk
import tkinter as tk

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import serial
import serial.tools.list_ports

from claude_tl.config import BAUD_RATE, ESP32_VID
from claude_tl.gui_proto_ipc import submit_gui_proto_hex
from claude_tl.proc_util import pid_alive
from claude_tl.switch_agent import load_config, switch_agent
from claude_tl.hook_light_catalog import (
    HookCatalogEntry,
    claude_hook_gui_sections,
    codex_hook_gui_sections,
    cursor_hook_gui_sections,
    default_hook_gui_row,
    default_tl_hook_light_gui_document,
)
from claude_tl.tl_transport import find_esp32_port, transport_mode
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
from claude_tl.light_effects import (
    GROUP_STATE_LABELS,
    GROUP_STATE_ORDER,
    config_path as effects_config_path,
    group_state_for_wire,
)

# GUI 与 daemon 共用同一配置文件路径（单一真相源）
CONFIG_PATH = effects_config_path()

AGENT_ORDER = ("claude", "codex", "cursor")
AGENT_LABELS = {"claude": "Claude", "codex": "Codex", "cursor": "Cursor"}
AGENT_APP_NAMES = {
    "claude": ("claude.exe", "claude.cmd", "claude.bat", "claude", "claude-code.exe", "claude-code.cmd"),
    "codex": ("codex.exe", "codex.cmd", "codex.bat", "codex"),
    "cursor": ("Cursor.exe", "cursor.exe"),
}
PRIORITY_LABELS = tuple(str(i) for i in range(1, 13))
_COMBOBOX_KEEPALIVE_ATTR = "_vcl_combobox_refs"

_AUTOSTART_DIR = (
    Path(os.environ.get("APPDATA", ""))
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs"
    / "Startup"
)
_AUTOSTART_VBS = _AUTOSTART_DIR / "VibeCodingLight-unified-daemon.vbs"
# 旧版写入的是 .bat（经 cmd 执行，登录时易闪黑窗）；开启开机启动时会改写为 .vbs 并删除旧 .bat
_LEGACY_AUTOSTART_BAT = _AUTOSTART_DIR / "VibeCodingLight-unified-daemon.bat"

EFFECT_LABELS = ("无", "常亮", "闪烁", "呼吸")
EFFECT_TO_KEY = {"无": "none", "常亮": "solid", "闪烁": "blink", "呼吸": "breath"}
KEY_TO_LABEL = {v: k for k, v in EFFECT_TO_KEY.items()}

# Windows：子进程不弹黑色控制台；单实例句柄在退出时释放
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_SINGLE_MUTEX_HANDLE: object | None = None
_SINGLE_LOCK_SOCK: socket.socket | None = None


def _subprocess_no_window_kw() -> dict:
    if sys.platform == "win32" and _CREATE_NO_WINDOW:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        return {"creationflags": _CREATE_NO_WINDOW, "startupinfo": si}
    return {}


def _clean_path_text(raw: str) -> str:
    return raw.strip().strip('"')


def _path_name_ok(agent: str, p: Path) -> bool:
    names = {n.lower() for n in AGENT_APP_NAMES[agent]}
    return p.name.lower() in names


def validate_agent_program_path(agent: str, raw: str) -> tuple[bool, str, str]:
    """Return (valid, display_message, normalized_path)."""
    text = _clean_path_text(raw)
    if not text:
        return False, "未选择", ""
    p = Path(text).expanduser()
    if p.is_file():
        if _path_name_ok(agent, p):
            return True, "已校验", str(p)
        return False, "名称不匹配", str(p)
    if p.is_dir():
        for name in AGENT_APP_NAMES[agent]:
            child = p / name
            if child.is_file():
                return True, "已校验", str(p)
        return False, "目录无程序", str(p)
    return False, "路径不存在", str(p)


def _first_existing_agent_candidate(agent: str) -> str:
    for name in AGENT_APP_NAMES[agent]:
        found = shutil.which(name)
        if found:
            ok, _msg, norm = validate_agent_program_path(agent, found)
            if ok:
                return norm

    home = Path.home()
    env_paths = {
        key: Path(value)
        for key in ("LOCALAPPDATA", "APPDATA", "ProgramFiles", "ProgramFiles(x86)")
        if (value := os.environ.get(key))
    }
    candidates: list[Path] = []
    if agent == "cursor":
        local = env_paths.get("LOCALAPPDATA")
        if local:
            candidates.extend(
                [
                    local / "Programs" / "Cursor" / "Cursor.exe",
                    local / "Programs" / "cursor" / "Cursor.exe",
                ]
            )
    if agent == "claude":
        local = env_paths.get("LOCALAPPDATA")
        if local:
            candidates.extend(
                [
                    local / "Programs" / "Claude" / "Claude.exe",
                    local / "AnthropicClaude" / "Claude.exe",
                ]
            )
    appdata = env_paths.get("APPDATA")
    if appdata:
        for name in AGENT_APP_NAMES[agent]:
            candidates.append(appdata / "npm" / name)
    for base in (home / ".local" / "bin", home / "scoop" / "shims"):
        for name in AGENT_APP_NAMES[agent]:
            candidates.append(base / name)

    for p in candidates:
        ok, _msg, norm = validate_agent_program_path(agent, str(p))
        if ok:
            return norm
    return ""


def _remember_combobox(owner: tk.Misc, cb: ttk.Combobox) -> ttk.Combobox:
    refs = getattr(owner, _COMBOBOX_KEEPALIVE_ATTR, None)
    if refs is None:
        refs = []
        setattr(owner, _COMBOBOX_KEEPALIVE_ATTR, refs)
    refs.append(cb)
    return cb


def _combobox_popdown_window(cb: ttk.Combobox) -> str:
    return str(cb.tk.call("ttk::combobox::PopdownWindow", str(cb)))


def _combobox_popup_is_mapped(cb: ttk.Combobox) -> bool:
    try:
        popdown = _combobox_popdown_window(cb)
        return bool(int(cb.tk.call("winfo", "ismapped", popdown)))
    except tk.TclError:
        return False


def _bind_popdown_listbox_mousewheel_break(cb: ttk.Combobox) -> None:
    """Disable wheel handling inside ttk.Combobox popdown listboxes.

    On Windows Tk, wheel events over a combobox popdown can interact badly with
    the app-wide MouseWheel binding used for Canvas scrolling. We prefer a
    stable dropdown over wheel scrolling inside that short list.
    """
    try:
        popdown = _combobox_popdown_window(cb)
    except tk.TclError:
        return
    stack = [popdown]
    seen: set[str] = set()
    while stack:
        widget = stack.pop()
        if widget in seen:
            continue
        seen.add(widget)
        try:
            cls = str(cb.tk.call("winfo", "class", widget))
        except tk.TclError:
            continue
        if cls == "Listbox":
            for event_name in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                try:
                    cb.tk.call("bind", widget, event_name, "break")
                except tk.TclError:
                    pass
        try:
            children = cb.tk.splitlist(cb.tk.call("winfo", "children", widget))
        except tk.TclError:
            children = ()
        stack.extend(str(child) for child in children)


def make_combobox(owner: tk.Misc, parent: tk.Misc, **kwargs) -> ttk.Combobox:
    """Create every ttk.Combobox through one guarded path.

    Keeping a Python-side reference and ignoring mouse-wheel on closed combos avoids
    Windows Tk popup edge cases inside Canvas/Notebook layouts.
    """
    postcommand = kwargs.pop("postcommand", None)
    cb = ttk.Combobox(parent, **kwargs)
    _remember_combobox(owner, cb)

    def _ignore_wheel(_event: tk.Event) -> str:
        return "break"

    def _guard_popdown_after_post() -> None:
        try:
            cb.after_idle(lambda: _bind_popdown_listbox_mousewheel_break(cb))
        except tk.TclError:
            pass

    def _postcommand() -> None:
        if callable(postcommand):
            postcommand()
        _guard_popdown_after_post()

    def _safe_post(_event: tk.Event) -> None:
        try:
            cb.winfo_exists()
        except tk.TclError:
            return
        _guard_popdown_after_post()

    try:
        cb.configure(postcommand=_postcommand)
    except tk.TclError:
        pass

    cb.bind("<MouseWheel>", _ignore_wheel, add="+")
    cb.bind("<<ComboboxSelected>>", lambda _e: cb.selection_clear(), add="+")
    cb.bind("<Button-1>", _safe_post, add="+")
    cb.bind("<Alt-Down>", _safe_post, add="+")
    cb.bind("<F4>", _safe_post, add="+")
    return cb


def _cleanup_stale_daemon_runtime_files() -> None:
    try:
        pid = int(_DAEMON_PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid = 0
    if pid and pid_alive(pid):
        return
    for p in (_DAEMON_PID_FILE, _DAEMON_LOCK_FILE):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _try_free_console_win32() -> None:
    """main() 内再调一次（与文件头早脱钩双保险）。"""
    _win_detach_console_if_any()


def _single_instance_acquire() -> bool:
    """若已有实例在运行则返回 False（由调用方弹窗并退出）。"""
    global _SINGLE_MUTEX_HANDLE, _SINGLE_LOCK_SOCK
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ERROR_ALREADY_EXISTS = 183
        CreateMutexW = kernel32.CreateMutexW
        CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        CreateMutexW.restype = wintypes.HANDLE
        kernel32.SetLastError(0)
        h = CreateMutexW(None, False, "Local\\VibeCodingLight-HookLightGui-SingleInstance")
        if int(kernel32.GetLastError()) == ERROR_ALREADY_EXISTS:
            if h:
                kernel32.CloseHandle(h)
            return False
        _SINGLE_MUTEX_HANDLE = h
        return True
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 52417))
        s.listen(1)
    except OSError:
        return False
    _SINGLE_LOCK_SOCK = s
    return True


def _single_instance_release() -> None:
    global _SINGLE_MUTEX_HANDLE, _SINGLE_LOCK_SOCK
    if sys.platform == "win32" and _SINGLE_MUTEX_HANDLE:
        try:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(_SINGLE_MUTEX_HANDLE)
        except Exception:
            pass
        _SINGLE_MUTEX_HANDLE = None
    if _SINGLE_LOCK_SOCK is not None:
        try:
            _SINGLE_LOCK_SOCK.close()
        except OSError:
            pass
        _SINGLE_LOCK_SOCK = None


def _pythonw_executable() -> str:
    p = Path(sys.executable)
    if p.name.lower() == "python.exe":
        pw = p.parent / "pythonw.exe"
        if pw.is_file():
            return str(pw)
    return str(p)


def _autostart_enabled() -> bool:
    return _AUTOSTART_VBS.is_file() or _LEGACY_AUTOSTART_BAT.is_file()


def _vb_string_literal(s: str) -> str:
    return s.replace('"', '""')


def _write_autostart_bat(enable: bool) -> None:
    """写入启动文件夹：无窗口 .vbs（推荐）；关闭时删除 .vbs 与旧版 .bat。"""
    if not enable:
        for p in (_AUTOSTART_VBS, _LEGACY_AUTOSTART_BAT):
            try:
                p.unlink()
            except OSError:
                pass
        return
    _AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
    from claude_tl.launcher import is_frozen

    if is_frozen():
        # 打包：开机自启直接拉起 exe 自身的 daemon 子命令，不依赖 Python/.py
        exe = str(Path(sys.executable).resolve())
        root = str(Path(sys.executable).resolve().parent)
        e = _vb_string_literal(exe)
        r = _vb_string_literal(root)
        body = "\r\n".join(
            [
                "' Auto-generated by VibeCodingLight — do not edit",
                "Option Explicit",
                "Dim shell, root, exe",
                "Set shell = CreateObject(\"WScript.Shell\")",
                f'exe = "{e}"',
                f'root = "{r}"',
                "shell.CurrentDirectory = root",
                "shell.Run Chr(34) & exe & Chr(34) & \" daemon-unified\", 0, False",
                "",
            ]
        )
    else:
        root = str(_ROOT.resolve())
        daemon = str((_ROOT / "daemon_unified.py").resolve())
        pyw = _pythonw_executable()
        r = _vb_string_literal(root)
        d = _vb_string_literal(daemon)
        p = _vb_string_literal(pyw)
        # Chr(34) = 双引号；窗口样式 0 = 隐藏；不经 cmd.exe，避免登录闪黑框
        body = "\r\n".join(
            [
                "' Auto-generated by VibeCodingLight tl_hook_light_gui — do not edit",
                "Option Explicit",
                "Dim shell, fso, root, pyw, daemon",
                "Set shell = CreateObject(\"WScript.Shell\")",
                "Set fso = CreateObject(\"Scripting.FileSystemObject\")",
                f'root = "{r}"',
                f'pyw = "{p}"',
                f'daemon = "{d}"',
                "shell.CurrentDirectory = root",
                "If fso.FileExists(pyw) Then",
                "  shell.Run Chr(34) & pyw & Chr(34) & \" \" & Chr(34) & daemon & Chr(34), 0, False",
                "Else",
                "  shell.Run \"pythonw.exe \" & Chr(34) & daemon & Chr(34), 0, False",
                "End If",
                "",
            ]
        )
    _AUTOSTART_VBS.write_text(body, encoding="utf-8")
    try:
        _LEGACY_AUTOSTART_BAT.unlink()
    except OSError:
        pass


def _make_tray_image(size: int = 64):
    from PIL import Image, ImageDraw

    im = Image.new("RGBA", (size, size), (18, 22, 40, 255))
    d = ImageDraw.Draw(im)
    # 氛围灯 + 代码感「花括号」轮廓
    d.rounded_rectangle((4, 4, size - 4, size - 4), radius=10, outline=(120, 200, 255, 200), width=2)
    d.ellipse((size // 2 - 18, 14, size // 2 + 18, 38), fill=(70, 220, 180, 230))
    d.ellipse((size // 2 - 10, 36, size // 2 + 10, 56), fill=(255, 200, 90, 255))
    d.line((14, size // 2 + 8, 22, size // 2 + 8), fill=(180, 190, 220, 255), width=2)
    d.line((size - 22, size // 2 + 8, size - 14, size // 2 + 8), fill=(180, 190, 220, 255), width=2)
    return im


def find_esp_ports() -> list[str]:
    """枚举串口：优先 VID=ESP32，其次常见 USB 转串描述，再退回全部。"""
    esp: list[str] = []
    usbish: list[str] = []
    for p in serial.tools.list_ports.comports():
        dev = p.device
        if p.vid == ESP32_VID:
            esp.append(dev)
        elif "USB" in (p.description or "").upper() or "CH340" in (p.description or "") or "CP210" in (p.description or ""):
            usbish.append(dev)
    if esp or usbish:
        return list(dict.fromkeys([*sorted(set(esp)), *sorted(set(usbish))]))
    return sorted({p.device for p in serial.tools.list_ports.comports()})


def _clamp_period_ms(v: int, default: int) -> int:
    if v <= 0:
        return default
    return max(PERIOD_MIN_MS, min(PERIOD_MAX_MS, v))


_DAEMON_PID_FILE = Path(os.environ.get("LOCALAPPDATA", "")) / "Temp" / "cc_traffic_light_daemon.pid"
_DAEMON_LOCK_FILE = Path(os.environ.get("LOCALAPPDATA", "")) / "Temp" / "cc_traffic_light_daemon.lock"


def _unlink_daemon_pid_file_best_effort() -> None:
    try:
        _DAEMON_PID_FILE.unlink()
    except OSError:
        pass


def _daemon_process_running() -> bool:
    """
    判断 PID 文件指向的灯控守护进程是否仍在跑。

    必须用 proc_util.pid_alive()，绝不能用 os.kill(pid, 0)——在 Windows 上后者会
    通过 TerminateProcess 直接杀死目标进程（曾导致「状态短暂变绿后被杀回未运行」）。
    """
    try:
        pid = int(_DAEMON_PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    if pid_alive(pid):
        return True
    _unlink_daemon_pid_file_best_effort()
    return False


def _wait_daemon_pid_file(timeout_sec: float = 3.0, interval: float = 0.15) -> bool:
    """子进程写入 PID 需要时间；在 timeout 内轮询，减少误报「仍未检测到灯控进程」。"""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if _daemon_process_running():
            return True
        time.sleep(interval)
    return _daemon_process_running()


def _stop_unified_daemon_silent() -> bool:
    """结束统一守护进程（无控制台）。返回当前是否已不在运行（含原本未运行）。"""
    try:
        pid = int(_DAEMON_PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True
    if not pid_alive(pid):
        _unlink_daemon_pid_file_best_effort()
        return True
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F", "/T"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **_subprocess_no_window_kw(),
            )
        else:
            try:
                os.kill(pid, 15)
            except OSError:
                return False
    except OSError:
        return False
    time.sleep(0.35)
    return not _daemon_process_running()


def _ensure_daemon_released_for_serial(max_rounds: int = 8) -> bool:
    """多次尝试结束灯控后台，直到进程消失或达上限。成功释放返回 True。"""
    for _ in range(max_rounds):
        if not _daemon_process_running():
            time.sleep(0.45)
            return True
        _stop_unified_daemon_silent()
        time.sleep(0.35)
    return not _daemon_process_running()


def _start_unified_daemon_silent() -> bool:
    """后台启动 unified daemon（无控制台）。开发模式用 pythonw+脚本，打包模式用 exe 子命令。失败返回 False。"""
    try:
        from claude_tl.launcher import daemon_spawn_argv

        argv = daemon_spawn_argv()
        subprocess.Popen(
            argv,
            cwd=str(_ROOT.resolve()),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **_subprocess_no_window_kw(),
        )
        return True
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def _compose_hw_indicator() -> tuple[str, str]:
    """灯控后台 + 传输/硬件；单行尽量短，不换行。"""
    dm = _daemon_process_running()
    mode = transport_mode()
    if dm:
        core = "灯控：运行中（后台占串口/BLE 写灯）"
    else:
        core = "灯控：未运行（可点「启动灯控」，或新开 Agent 会话由 hook 自启）"
    if mode == "ble":
        tail = "｜BLE"
        fg = "#1a6620" if dm else "#555555"
    else:
        port = find_esp32_port()
        tail = f"｜ESP32：{port}" if port else "｜未检测到 ESP32"
        if dm and port:
            fg = "#1a6620"
        elif dm:
            fg = "#6a8f00"
        elif port:
            fg = "#a06000"
        else:
            fg = "#555555"
    return core + tail, fg


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

    def on_mousewheel(self, event: tk.Event) -> None:
        """由主窗口统一路由调用；内容不足一屏时不滚动，避免 Codex 短表顶空白。"""
        try:
            self.update_idletasks()
            ch = self._inner.winfo_height()
            vh = self._canvas.winfo_height()
            if ch <= vh + 2:
                return
        except tk.TclError:
            return
        if sys.platform == "darwin":
            self._canvas.yview_scroll(int(-1 * event.delta), "units")
        else:
            d = event.delta // 120
            if d == 0 and getattr(event, "delta", 0) != 0:
                d = -1 if event.delta > 0 else 1
            self._canvas.yview_scroll(int(-1 * d), "units")

    def _on_canvas_cfg(self, e: tk.Event) -> None:
        self._canvas.itemconfig(self._win_id, width=e.width)

    @property
    def body(self) -> ttk.Frame:
        return self._inner


class HookAgentPanel(ttk.Frame):
    """单 Agent：表头 + 分组 + 可滚动行（列对齐）。"""

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        sections: list[tuple[str, tuple[HookCatalogEntry, ...]]],
    ):
        super().__init__(parent, padding=4)
        self._rows: list[dict[str, object]] = []
        self._group_vars: dict[str, dict] = {}

        ttk.Label(self, text=title, font=("TkDefaultFont", 10, "bold")).pack(anchor=W)
        ttk.Label(
            self,
            text=(
                "按「状态组」分层：组标题行可一键统一设置整组灯效，组内每个 hook 也能单独配。"
                "配置写入 config/tl_hook_light_gui.json（窗口底部「保存全部」即热生效）。"
                "●=switch_agent 默认写入 IDE hooks；○=仅作配置参考。"
            ),
            foreground="gray",
            wraplength=880,
            justify=LEFT,
        ).pack(anchor=W, padx=2, pady=(0, 4))

        self._scroll = ScrollableRows(self)
        self._scroll.pack(fill=BOTH, expand=True)
        body = self._scroll.body

        for c, w in enumerate((2, 3, 1, 0, 0, 0, 1)):
            body.grid_columnconfigure(c, weight=w, uniform="hookcols")

        headers = ("中文名", "Hook 事件名", "灯光", "绿", "黄", "红", "优先级")
        for col, h in enumerate(headers):
            sticky = "w" if col < 3 else "ew"
            anc = "w" if col < 3 else "center"
            ttk.Label(body, text=h, font=("TkDefaultFont", 9, "bold"), anchor=anc).grid(
                row=0, column=col, padx=6, pady=6, sticky=sticky
            )

        # 扁平化所有 hook，再按「状态组」重新分桶：第一级=状态组，组内=各 hook
        all_entries: list = []
        for _sec, entries in sections:
            all_entries.extend(entries)

        buckets: dict[str, list] = {k: [] for k in GROUP_STATE_ORDER}
        buckets["_other"] = []
        for ent in all_entries:
            buckets[self._group_key(ent)].append(ent)

        ordered = [(k, GROUP_STATE_LABELS[k]) for k in GROUP_STATE_ORDER]
        ordered.append(("_other", "其他 · 会话开始/结束、系统或未接线（一般不单独配灯）"))

        row_idx = 1
        for gkey, glabel in ordered:
            ents = buckets.get(gkey) or []
            if not ents:
                continue
            row_idx = self._append_group_header(body, row_idx, gkey, glabel)
            for ent in ents:
                r = self._append_row(body, row_idx, ent)
                r["group"] = gkey
                self._rows.append(r)
                row_idx += 1

    @staticmethod
    def _group_key(ent) -> str:
        """hook → 它所属的状态组键（GROUP_STATE_ORDER 之一或 '_other'）。"""
        if not getattr(ent, "wired", False):
            return "_other"
        if ent.wire_kind == "alert":
            return "alert"
        if ent.wire_kind == "set_state":
            gs = group_state_for_wire(ent.wire_state)
            return gs if gs in GROUP_STATE_ORDER else "_other"
        return "_other"

    def _append_group_header(self, body: ttk.Frame, row_idx: int, gkey: str, glabel: str) -> int:
        """画状态组标题；状态组额外给一行「组统一」控件 + 应用按钮。返回下一可用行号。"""
        ttk.Label(
            body,
            text=f"▼ {glabel}",
            foreground="#1a4d80",
            font=("TkDefaultFont", 9, "bold"),
        ).grid(row=row_idx, column=0, columnspan=7, padx=6, pady=(12, 2), sticky="w")
        if gkey not in GROUP_STATE_ORDER:
            return row_idx + 1

        ctl = ttk.Frame(body)
        ctl.grid(row=row_idx + 1, column=0, columnspan=7, padx=20, pady=(0, 4), sticky="w")
        ttk.Label(ctl, text="组统一：").pack(side=LEFT)
        mv = tk.StringVar(value="闪烁")
        gv = tk.BooleanVar(value=False)
        yv = tk.BooleanVar(value=False)
        rv = tk.BooleanVar(value=False)
        pv = tk.StringVar(value="6")
        mode_cb = make_combobox(self, ctl, textvariable=mv, values=EFFECT_LABELS, width=6, state="readonly")
        mode_cb.pack(side=LEFT, padx=2)
        for t, var in (("绿", gv), ("黄", yv), ("红", rv)):
            ttk.Checkbutton(ctl, text=t, variable=var).pack(side=LEFT)
        ttk.Label(ctl, text="优先级").pack(side=LEFT, padx=(8, 2))
        prio_cb = make_combobox(self, ctl, textvariable=pv, values=PRIORITY_LABELS, width=4, state="readonly")
        prio_cb.pack(side=LEFT)
        ttk.Button(ctl, text="应用到本组", command=lambda k=gkey: self._apply_group_to_rows(k)).pack(
            side=LEFT, padx=8
        )
        self._group_vars[gkey] = {
            "mode": mv,
            "g": gv,
            "y": yv,
            "r": rv,
            "prio": pv,
            "mode_cb": mode_cb,
            "prio_cb": prio_cb,
        }
        return row_idx + 2

    def _apply_group_to_rows(self, gkey: str) -> None:
        """把「组统一」控件的值批量写到该组内所有 hook 行（用户仍可逐行再调）。"""
        gv = self._group_vars.get(gkey)
        if not gv:
            return
        for r in self._rows:
            if r.get("group") != gkey:
                continue
            r["effect"].set(gv["mode"].get())  # type: ignore[union-attr]
            r["g"].set(gv["g"].get())  # type: ignore[union-attr]
            r["y"].set(gv["y"].get())  # type: ignore[union-attr]
            r["r"].set(gv["r"].get())  # type: ignore[union-attr]
            r["prio"].set(gv["prio"].get())  # type: ignore[union-attr]
            self._sync_row_prio_state(r)

    @staticmethod
    def _row_light_inactive(r: dict[str, object]) -> bool:
        lab = r["effect"].get()  # type: ignore[union-attr]
        key = EFFECT_TO_KEY.get(lab, "none")
        m = (MASK_G if r["g"].get() else 0) | (MASK_Y if r["y"].get() else 0) | (MASK_R if r["r"].get() else 0)  # type: ignore[union-attr]
        return key == "none" or m == 0

    def _sync_row_prio_state(self, r: dict[str, object]) -> None:
        cb = r["prio_cb"]  # type: ignore[assignment]
        inactive = self._row_light_inactive(r)
        if inactive:
            r["prio"].set("12")  # type: ignore[union-attr]
            try:
                cb.state(["disabled"])  # type: ignore[attr-defined]
            except (tk.TclError, AttributeError):
                try:
                    cb.configure(state=tk.DISABLED)
                except tk.TclError:
                    pass
        else:
            try:
                cb.state(["!disabled", "readonly"])  # type: ignore[attr-defined]
            except (tk.TclError, AttributeError):
                try:
                    cb.configure(state="readonly")
                except tk.TclError:
                    pass

    def _append_row(self, body: ttk.Frame, row_idx: int, ent: HookCatalogEntry) -> dict[str, object]:
        d0 = default_hook_gui_row(ent)
        zh_label = ttk.Label(body, text=str(d0.get("zh") or ent.zh_default), anchor="w")
        pfx = "● " if ent.wired else "○ "
        mid = ent.event if not ent.matcher else f"{ent.event}\n[{ent.matcher}]"
        ev_text = pfx + mid
        eff = tk.StringVar(value=KEY_TO_LABEL.get(str(d0.get("effect", "none")), "无"))
        m0 = int(d0.get("mask", 0))
        vg = tk.BooleanVar(value=bool(m0 & MASK_G))
        vy = tk.BooleanVar(value=bool(m0 & MASK_Y))
        vr = tk.BooleanVar(value=bool(m0 & MASK_R))
        prio = tk.StringVar(value=str(int(d0.get("priority", 12))))

        zh_label.grid(row=row_idx, column=0, padx=6, pady=3, sticky="ew")
        ttk.Label(body, text=ev_text, justify=LEFT, anchor="w").grid(
            row=row_idx, column=1, padx=6, pady=3, sticky="ew"
        )
        eff_cb = make_combobox(
            self,
            body,
            textvariable=eff,
            values=EFFECT_LABELS,
            width=8,
            state="readonly",
        )
        eff_cb.grid(row=row_idx, column=2, padx=6, pady=3, sticky="ew")
        ttk.Checkbutton(body, text="", variable=vg).grid(row=row_idx, column=3, padx=6, pady=3)
        ttk.Checkbutton(body, text="", variable=vy).grid(row=row_idx, column=4, padx=6, pady=3)
        ttk.Checkbutton(body, text="", variable=vr).grid(row=row_idx, column=5, padx=6, pady=3)
        prio_cb = make_combobox(
            self,
            body,
            textvariable=prio,
            values=PRIORITY_LABELS,
            width=4,
            state="readonly",
        )
        prio_cb.grid(row=row_idx, column=6, padx=6, pady=3, sticky="ew")

        row: dict[str, object] = {
            "event": ent.event,
            "zh_label": zh_label,
            "zh_default": ent.zh_default,
            "effect": eff,
            "effect_cb": eff_cb,
            "g": vg,
            "y": vy,
            "r": vr,
            "prio": prio,
            "prio_cb": prio_cb,
        }

        def _sync(*_a: object) -> None:
            self._sync_row_prio_state(row)

        eff.trace_add("write", _sync)
        vg.trace_add("write", _sync)
        vy.trace_add("write", _sync)
        vr.trace_add("write", _sync)
        self._sync_row_prio_state(row)
        return row

    def _row_to_dict(self, r: dict[str, object]) -> dict:
        lab = r["effect"].get()  # type: ignore[union-attr]
        zh_w = r["zh_label"]  # type: ignore[assignment]
        zh = zh_w.cget("text").strip() if hasattr(zh_w, "cget") else ""
        mask = (MASK_G if r["g"].get() else 0) | (MASK_Y if r["y"].get() else 0) | (MASK_R if r["r"].get() else 0)  # type: ignore[union-attr]
        eff_key = EFFECT_TO_KEY.get(lab, "none")
        prio_val = 12 if (eff_key == "none" or mask == 0) else int(r["prio"].get())  # type: ignore[union-attr]
        return {
            "event": r["event"],
            "zh": zh,
            "effect": eff_key,
            "mask": mask,
            "priority": prio_val,
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
            zd = str(r.get("zh_default", ""))  # type: ignore[arg-type]
            txt = (d.get("zh") or zd).strip()
            r["zh_label"].config(text=txt)  # type: ignore[union-attr]
            key = d.get("effect", "none")
            r["effect"].set(KEY_TO_LABEL.get(key, "无"))  # type: ignore[union-attr]
            m = int(d.get("mask", 0))
            r["g"].set(bool(m & MASK_G))  # type: ignore[union-attr]
            r["y"].set(bool(m & MASK_Y))
            r["r"].set(bool(m & MASK_R))
            eff_key = str(d.get("effect", "none"))
            mask = m
            if eff_key == "none" or mask == 0:
                r["prio"].set("12")  # type: ignore[union-attr]
            else:
                p = int(d.get("priority", 12))
                r["prio"].set(str(max(1, min(12, p))))  # type: ignore[union-attr]
            self._sync_row_prio_state(r)


class TrafficHookLightApp(ttk.Frame):
    def __init__(self, master: tk.Misc):
        super().__init__(master, padding=6)
        self.pack(fill=BOTH, expand=True)
        self._ser: serial.Serial | None = None

        self._duty_g = tk.IntVar(value=255)
        self._duty_y = tk.IntVar(value=255)
        self._duty_r = tk.IntVar(value=255)
        self._blink_period = tk.StringVar(value="800")
        self._breath_period = tk.StringVar(value="2000")

        self._test_g = tk.BooleanVar(value=True)
        self._test_y = tk.BooleanVar(value=True)
        self._test_r = tk.BooleanVar(value=True)
        self._test_mode_radio = tk.StringVar(value="BLINK")

        self._agent_busy = False
        self._daemon_start_busy = False
        self._agent_var = tk.StringVar(value=str(load_config().get("active", "claude")))
        self._agent_path_vars = {agent: tk.StringVar(value="") for agent in AGENT_ORDER}
        self._agent_path_state: dict[str, bool] = {agent: False for agent in AGENT_ORDER}
        self._agent_path_status: dict[str, ttk.Label] = {}
        self._agent_radios: dict[str, ttk.Radiobutton] = {}
        self._agent_tabs: dict[str, ttk.Frame] = {}
        self._status = ttk.Label(self, text="就绪", foreground="gray")

        self._daemon_stopped_for_serial = False

        self._autostart = tk.BooleanVar(value=True)

        nb = ttk.Notebook(self)
        nb.pack(fill=BOTH, expand=True)
        self._nb = nb
        f0 = ttk.Frame(nb, padding=6)
        f1 = ttk.Frame(nb, padding=6)
        f2 = ttk.Frame(nb, padding=6)
        f3 = ttk.Frame(nb, padding=6)
        nb.add(f0, text="基础设置")
        nb.add(f1, text="Claude")
        nb.add(f2, text="Codex")
        nb.add(f3, text="Cursor")
        self._agent_tabs = {"claude": f1, "codex": f2, "cursor": f3}
        nb.bind("<<NotebookTabChanged>>", self._on_notebook_tab)

        self._build_basic_tab(f0)
        self._claude_panel = HookAgentPanel(f1, "Claude Code — Hook 与灯光", claude_hook_gui_sections())
        self._claude_panel.pack(fill=BOTH, expand=True)
        self._codex_panel = HookAgentPanel(f2, "Codex — Hook 与灯光", codex_hook_gui_sections())
        self._codex_panel.pack(fill=BOTH, expand=True)
        self._cursor_panel = HookAgentPanel(f3, "Cursor — Hook 与灯光（~/.cursor/hooks.json）", cursor_hook_gui_sections())
        self._cursor_panel.pack(fill=BOTH, expand=True)

        bf = ttk.Frame(self)
        bf.pack(fill=X, pady=4)
        ttk.Button(bf, text="保存全部（基础+Claude+Codex+Cursor）", command=self._save_all).pack(side=LEFT, padx=2)
        ttk.Button(bf, text="重置", command=self._reset_to_default).pack(side=LEFT, padx=2)

        self._status.pack(fill=X)

        top = self.winfo_toplevel()
        top.bind_all("<MouseWheel>", self._global_mousewheel, add="+")

        self._load_all()

    def _global_mousewheel(self, event: tk.Event) -> str | None:
        """滚轮交给指针下（含 winfo_containing）的 ScrollableRows，避免事件落在隐藏 Tab 上。"""
        if self._any_combobox_popup_open():
            return "break"
        try:
            my_top = self.winfo_toplevel()
            w = my_top.winfo_containing(event.x_root, event.y_root)
        except tk.TclError:
            return None
        if w is None or str(w) == "":
            return None
        cur: tk.Misc | None = w
        while cur is not None:
            if isinstance(cur, ScrollableRows):
                try:
                    if cur.winfo_toplevel() == my_top:
                        cur.on_mousewheel(event)
                        return "break"
                except tk.TclError:
                    return None
            cur = getattr(cur, "master", None)
        return None

    def _any_combobox_popup_open(self) -> bool:
        owners = [self, self._claude_panel, self._codex_panel, self._cursor_panel]
        for owner in owners:
            for cb in getattr(owner, _COMBOBOX_KEEPALIVE_ATTR, []):
                if _combobox_popup_is_mapped(cb):
                    return True
        return False

    def _on_notebook_tab(self, _event: tk.Event | None = None) -> None:
        for pan in (self._claude_panel, self._codex_panel, self._cursor_panel):
            try:
                pan._scroll._canvas.yview_moveto(0)
            except tk.TclError:
                pass

    def _schedule_hw_poll(self) -> None:
        self.after(400, self._update_hw_indicator)

    def _update_hw_indicator(self) -> None:
        stop_poll = False
        try:
            txt, fg = _compose_hw_indicator()
            self._hw_indicator.config(text=txt, foreground=fg)
        except tk.TclError:
            stop_poll = True
        except OSError:
            try:
                self._hw_indicator.config(text="灯控/硬件：检测异常", foreground="gray")
            except tk.TclError:
                stop_poll = True
        if not stop_poll:
            try:
                self.after(2500, self._update_hw_indicator)
            except tk.TclError:
                pass

    def _log(self, s: str) -> None:
        try:
            st = getattr(self, "_status", None)
            if st is not None:
                st.config(text=s)
        except TclError:
            pass

    def _on_autostart_toggle(self) -> None:
        try:
            _write_autostart_bat(self._autostart.get())
            self._log("已开启开机启动（启动文件夹无窗口 .vbs）" if self._autostart.get() else "已关闭开机启动")
        except OSError as e:
            messagebox.showerror("开机启动", str(e))
            self._autostart.set(_autostart_enabled())

    def _refresh_agent_path_state(self, agent: str) -> bool:
        ok, msg, norm = validate_agent_program_path(agent, self._agent_path_vars[agent].get())
        self._agent_path_state[agent] = ok
        if norm:
            self._agent_path_vars[agent].set(norm)
        lab = self._agent_path_status.get(agent)
        if lab is not None:
            lab.config(text=msg, foreground=("#1a6620" if ok else "#a33"))
        self._apply_agent_availability()
        return ok

    def _refresh_all_agent_path_states(self) -> None:
        for agent in AGENT_ORDER:
            self._refresh_agent_path_state(agent)

    def _apply_agent_availability(self) -> None:
        current_tab = None
        try:
            current_tab = self._nb.select()
        except tk.TclError:
            pass
        for agent in AGENT_ORDER:
            enabled = bool(self._agent_path_state.get(agent))
            rb = self._agent_radios.get(agent)
            if rb is not None:
                rb.configure(state=(tk.NORMAL if enabled else tk.DISABLED))
            tab = self._agent_tabs.get(agent)
            if tab is not None:
                self._nb.tab(tab, state=("normal" if enabled else "disabled"))
                if not enabled and current_tab == str(tab):
                    self._nb.select(0)

    def _browse_agent_path(self, agent: str) -> None:
        suffixes = sorted({Path(name).suffix for name in AGENT_APP_NAMES[agent] if Path(name).suffix})
        pattern = " ".join(f"*{suffix}" for suffix in suffixes) or "*.*"
        chosen = filedialog.askopenfilename(
            title=f"选择 {AGENT_LABELS[agent]} 程序位置",
            filetypes=[("Program files", pattern), ("All files", "*.*")],
        )
        if not chosen:
            return
        self._agent_path_vars[agent].set(chosen)
        self._refresh_agent_path_state(agent)

    def _find_agent_path(self, agent: str) -> None:
        found = _first_existing_agent_candidate(agent)
        if found:
            self._agent_path_vars[agent].set(found)
            self._refresh_agent_path_state(agent)
            self._log(f"已找到 {AGENT_LABELS[agent]} 程序位置：{found}")
            return
        self._refresh_agent_path_state(agent)
        messagebox.showwarning(
            "程序位置",
            f"未自动找到 {AGENT_LABELS[agent]}。请点击“浏览”手动选择对应程序文件。",
        )

    def _on_agent_change(self) -> None:
        if self._agent_busy:
            return
        want = self._agent_var.get()
        if not self._agent_path_state.get(want):
            self._agent_var.set(str(load_config().get("active", "claude")))
            messagebox.showwarning("Agent 切换", f"请先在“程序位置”中选择并校验 {AGENT_LABELS.get(want, want)}。")
            return
        self._start_agent_switch(want)

    def _start_agent_switch(self, agent: str) -> None:
        self._agent_busy = True
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
        self._agent_busy = False
        if err:
            messagebox.showerror("Agent 切换", err)
            self._agent_var.set(str(load_config().get("active", "claude")))
        elif not ok:
            messagebox.showwarning("Agent 切换", "切换未成功（请查看控制台输出）")
            self._agent_var.set(str(load_config().get("active", "claude")))
        else:
            self._log(
                "已切换：active_agent 与 IDE hooks 已更新；灯控会立即改读对应状态目录（无需重启本程序）。"
                "若某个已打开的 IDE 里灯仍不跟它走，请新开对话或重启该 IDE 以加载 hooks。"
            )
            try:
                txt, fg = _compose_hw_indicator()
                self._hw_indicator.config(text=txt, foreground=fg)
            except (tk.TclError, OSError):
                pass

    def _build_basic_tab(self, f: ttk.Frame) -> None:
        row1 = ttk.Frame(f)
        row1.pack(fill=X, pady=2)
        ag_fr = ttk.Frame(row1)
        ag_fr.pack(side=LEFT)
        ttk.Label(ag_fr, text="Agent").pack(side=LEFT, padx=(0, 4))
        rb = ttk.Radiobutton(
            ag_fr,
            text="Claude",
            variable=self._agent_var,
            value="claude",
            command=self._on_agent_change,
        )
        rb.pack(side=LEFT)
        self._agent_radios["claude"] = rb
        rb = ttk.Radiobutton(
            ag_fr,
            text="Codex",
            variable=self._agent_var,
            value="codex",
            command=self._on_agent_change,
        )
        rb.pack(side=LEFT, padx=4)
        self._agent_radios["codex"] = rb
        rb = ttk.Radiobutton(
            ag_fr,
            text="Cursor",
            variable=self._agent_var,
            value="cursor",
            command=self._on_agent_change,
        )
        rb.pack(side=LEFT, padx=4)
        self._agent_radios["cursor"] = rb
        self._hw_indicator = ttk.Label(row1, text="检测中…", justify=LEFT)
        self._hw_indicator.pack(side=LEFT, padx=8, fill=X, expand=True)

        row2 = ttk.Frame(f)
        row2.pack(fill=X, pady=2)
        ttk.Label(row2, text="端口").pack(side=LEFT)
        self._port_var = StringVar()
        self._port_combo = make_combobox(self, row2, textvariable=self._port_var, width=10)
        self._port_combo.pack(side=LEFT, padx=4)
        ttk.Button(row2, text="刷新", command=self._on_refresh_clicked).pack(side=LEFT)
        ttk.Button(row2, text="启动灯控", command=self._on_start_daemon_clicked).pack(side=LEFT, padx=(4, 0))
        ttk.Checkbutton(
            row2,
            text="开机启动（统一守护）",
            variable=self._autostart,
            command=self._on_autostart_toggle,
        ).pack(side=LEFT, padx=(16, 4))

        path_lf = ttk.LabelFrame(f, text="程序位置", padding=6)
        path_lf.pack(fill=X, pady=(6, 2))
        ttk.Label(
            path_lf,
            text="选择并校验 Claude / Codex / Cursor 的程序位置。校验通过后，对应 Agent 选项和页签才会开放。",
            foreground="#555",
            wraplength=900,
            justify=LEFT,
        ).pack(fill=X, anchor=W, pady=(0, 4))
        for agent in AGENT_ORDER:
            row = ttk.Frame(path_lf)
            row.pack(fill=X, pady=2)
            ttk.Label(row, text=AGENT_LABELS[agent], width=8).pack(side=LEFT)
            ent = ttk.Entry(row, textvariable=self._agent_path_vars[agent], width=58)
            ent.pack(side=LEFT, fill=X, expand=True, padx=(0, 4))
            ent.bind("<FocusOut>", lambda _e, a=agent: self._refresh_agent_path_state(a))
            ent.bind("<Return>", lambda _e, a=agent: self._refresh_agent_path_state(a))
            ttk.Button(row, text="浏览", command=lambda a=agent: self._browse_agent_path(a)).pack(side=LEFT, padx=2)
            ttk.Button(row, text="查找", command=lambda a=agent: self._find_agent_path(a)).pack(side=LEFT, padx=2)
            lab = ttk.Label(row, text="未选择", width=10, foreground="#a33")
            lab.pack(side=LEFT, padx=(6, 0))
            self._agent_path_status[agent] = lab

        test_lf = ttk.LabelFrame(
            f,
            text="试灯（测试模式专属：仅本机临时验证灯效，不影响 hook 配置）",
            padding=6,
        )
        test_lf.pack(fill=X, pady=6)

        # 需求2：串口「连接/断开」放进试灯组，并明确这是测试模式专属、会独占串口
        r_conn = ttk.Frame(test_lf)
        r_conn.pack(fill=X, pady=(0, 4))
        ttk.Label(r_conn, text="串口直连：", font=("TkDefaultFont", 9, "bold")).pack(side=LEFT)
        ttk.Button(r_conn, text="连接", command=self._serial_connect).pack(side=LEFT, padx=4)
        ttk.Button(r_conn, text="断开", command=self._serial_disconnect).pack(side=LEFT, padx=2)
        ttk.Label(
            r_conn,
            text="（连接=本程序独占串口、暂停后台守护，仅供试灯；此时灯不随 Agent 状态变化。试完务必「断开」归还后台）",
            foreground="#a06000",
            font=("TkDefaultFont", 8),
        ).pack(side=LEFT, padx=6)

        self._conn_line = ttk.Label(
            test_lf,
            text="本地串口：未连接",
            foreground="gray",
            font=("TkDefaultFont", 9),
            justify=LEFT,
        )
        self._conn_line.pack(fill=X, anchor=W, pady=(0, 4))

        self._on_refresh_clicked(initial=True)
        self._schedule_hw_poll()

        r2 = ttk.Frame(test_lf)
        r2.pack(fill=X)
        for txt, var in (("绿", self._test_g), ("黄", self._test_y), ("红", self._test_r)):
            ttk.Checkbutton(r2, text=txt, variable=var).pack(side=LEFT, padx=4)
        ttk.Label(r2, text="模式").pack(side=LEFT, padx=(12, 2))
        for val, lab in (
            ("OFF", "全灭"),
            ("SOLID", "常亮"),
            ("BLINK", "同步闪烁"),
            ("BREATH", "呼吸"),
        ):
            ttk.Radiobutton(r2, text=lab, variable=self._test_mode_radio, value=val).pack(side=LEFT, padx=2)
        ttk.Button(r2, text="发送", command=self._test_send).pack(side=LEFT, padx=10)

        r3 = ttk.LabelFrame(f, text="亮度与周期（扩展帧；与后续 hook 驱动共用数值）", padding=6)
        r3.pack(fill=X, pady=4, before=path_lf)

        def row_scale(parent: ttk.Frame, label: str, var: tk.IntVar) -> None:
            fr = ttk.Frame(parent)
            fr.pack(fill=X, pady=2)
            ttk.Label(fr, text=label, width=10).pack(side=LEFT)
            sc = ttk.Scale(fr, from_=0, to=255, variable=var, orient="horizontal")
            sc.pack(side=LEFT, fill=X, expand=True, padx=4)
            val_lab = ttk.Label(fr, width=4, anchor="e")

            def upd(*_a: object) -> None:
                try:
                    val_lab.configure(text=str(int(float(var.get()))))
                except (ValueError, tk.TclError):
                    val_lab.configure(text="0")

            var.trace_add("write", upd)
            upd()
            val_lab.pack(side=LEFT)

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

        usage_text = (
            "切换任一Agent后，后台配置即刻生效，通常无需关闭当前窗口或重启灯控程序。"
            "若灯光未按预设配置运行，多为软件未重载钩子（hooks），新建会话或重启该 IDE 通常可解决。"
            " 点击「连接」调试灯光后接口被接管，程序无法正常指示真实状态；若持续弹出访问拒绝提示，先行关闭 Arduino、串口调试助手等占用端口的程序，问题依旧无法排查时，重新插拔 USB 设备即可释放串口。\n"
            "项目地址  jursber/claude-traffic-light https://github.com/jursber/claude-traffic-light"
        )
        foot_tech = (
            "【技术说明】active_agent.json 决定当前由哪套 IDE 的 hooks 把状态写入「哪一个」Temp 子目录；"
            "unified_daemon 每次合并灯态前都会重新读该文件，因此切换 Agent 后，灯控会立刻改读新目录，无需重启本 GUI 或守护进程。"
            "switch_agent 会改写 ~/.claude、~/.codex、~/.cursor 下的 hook 配置：只有当前选中的 Agent 会保留红绿灯 hook。"
        )
        foot_plain = (
            "【白话】你在上面换 Claude / Codex / Cursor，后台马上改成「只听当前选中的这一套」的文件夹，灯也会跟着这套走，"
            "一般不用关这个窗口、也不用重启灯控程序。"
            "如果某个 IDE 里灯还不跟它走，多半是那个软件还没重新加载 hooks，试「新开一条对话」或重启该 IDE 即可。"
            "点「连接」试灯时，必须把灯控后台占用的串口让出来；若仍提示「拒绝访问」，请先关掉 Arduino、串口助手等其它占用同一 COM 口的程序，再点刷新后连接。"
            " 仍无法判断时，可拔插 USB 让串口释放，或见 docs/SERIAL_PORT_TROUBLESHOOTING.md。"
        )
        lf_foot = ttk.LabelFrame(f, text="使用说明", padding=(8, 6))
        lf_foot.pack(fill=BOTH, expand=False, pady=(10, 0))
        foot_box = tk.Text(
            lf_foot,
            height=5,
            wrap="word",
            font=("Microsoft YaHei UI", 10) if sys.platform == "win32" else ("TkDefaultFont", 10),
            relief="flat",
            highlightthickness=0,
            padx=6,
            pady=6,
            bg="#fafafa",
            fg="#1a1a1a",
        )
        foot_box.pack(fill=BOTH, expand=True)
        foot_box.insert("1.0", usage_text)
        foot_box.configure(state=tk.DISABLED)


    def _sync_connection_status_text(self) -> None:
        try:
            if self._ser is not None and getattr(self._ser, "is_open", False):
                p = self._port_var.get().strip() or getattr(self._ser, "port", "?")
                self._conn_line.config(text=f"本地串口：已连接 {p}（本程序独占）", foreground="#1a6620")
            else:
                self._conn_line.config(text="本地串口：未连接（试灯可走 IPC，由后台发灯）", foreground="gray")
        except tk.TclError:
            pass

    def _on_refresh_clicked(self, initial: bool = False) -> None:
        ps = find_esp_ports()
        self._port_combo["values"] = ps
        if ps and not self._port_var.get().strip():
            self._port_var.set(ps[0])
        self._sync_connection_status_text()
        try:
            txt, fg = _compose_hw_indicator()
            self._hw_indicator.config(text=txt, foreground=fg)
        except (tk.TclError, OSError):
            pass
        if not initial:
            self._log("已刷新串口列表与连接状态")

    def _on_start_daemon_clicked(self) -> None:
        """不依赖 IDE hook，手动拉起 unified_daemon（与 sessionStart 等价）。"""
        if self._daemon_start_busy:
            return
        if _daemon_process_running():
            self._log("灯控后台已在运行")
            self._on_refresh_clicked()
            return

        self._daemon_start_busy = True
        self._log("正在启动灯控…")

        def worker() -> None:
            err: str | None = None
            spawned = False
            try:
                spawned = _start_unified_daemon_silent()
                if spawned:
                    _wait_daemon_pid_file(3.0, 0.15)
            except Exception as e:
                err = str(e)

            def done() -> None:
                self._daemon_start_busy = False
                try:
                    if err:
                        try:
                            messagebox.showerror("灯控", err)
                        except tk.TclError:
                            pass
                        self._on_refresh_clicked()
                        return
                    if not spawned:
                        try:
                            messagebox.showerror(
                                "灯控",
                                "未能创建灯控子进程（请确认本机 pythonw 与仓库根目录下 daemon_unified.py 可用）。",
                            )
                        except tk.TclError:
                            pass
                        self._on_refresh_clicked()
                        return
                    if spawned:
                        ok = _daemon_process_running()
                        if not ok:
                            time.sleep(0.25)
                            ok = _daemon_process_running()
                        if not ok:
                            logf = Path(os.environ.get("LOCALAPPDATA", "")) / "Temp" / "cc_traffic_light_daemon.log"
                            try:
                                messagebox.showwarning(
                                    "灯控",
                                    "仍未检测到灯控进程。常见原因：① 单例锁仍被占用（见日志末尾「文件锁」）② 进程已起但尚未写入 PID（少见）③ 启动即退出。\n"
                                    f"日志：{logf}\n"
                                    "若确认没有灯控在跑，可删除：%TEMP%\\cc_traffic_light_daemon.lock 后再点「启动灯控」。",
                                )
                            except tk.TclError:
                                pass
                    self._on_refresh_clicked()
                except (tk.TclError, OSError):
                    self._on_refresh_clicked()

            try:
                self.after(0, done)
            except tk.TclError:
                self._daemon_start_busy = False

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_ports(self) -> None:
        """兼容旧调用：等同刷新端口列表。"""
        ps = find_esp_ports()
        self._port_combo["values"] = ps
        if ps and not self._port_var.get().strip():
            self._port_var.set(ps[0])

    def _send_off_best_effort(self) -> None:
        """全灭：有本机串口则直发，否则写 IPC 请求给守护进程。"""
        frame = build_set_lighting_frame(MODE_OFF, 0, 1000, 0, 0, 0)
        if self._ser is not None and getattr(self._ser, "is_open", False):
            try:
                self._ser.write(frame)
                self._ser.flush()
            except (OSError, PermissionError):
                pass
        else:
            try:
                submit_gui_proto_hex(frame.hex())
            except OSError:
                pass

    def _open_serial_locked(self, p: str, attempts: int = 14):
        """打开并独占串口；多次重试后仍失败则抛出最后一个异常。

        ESP32 原生 USB-CDC（VID 303A）偶发复位/重新枚举，打开或写入会瞬时失败，
        重试一次往往即可成功。保持 dtr/rts=False，避免对 UART 桥型板子误触发复位。
        """
        last_err: Exception | None = None
        for _ in range(max(1, attempts)):
            try:
                try:
                    ser = serial.Serial(
                        port=p,
                        baudrate=BAUD_RATE,
                        timeout=0.3,
                        dsrdtr=False,
                        exclusive=True,  # type: ignore[call-arg]
                    )
                except TypeError:
                    ser = serial.Serial(p, BAUD_RATE, timeout=0.3, dsrdtr=False)
                ser.dtr = False
                ser.rts = False
                return ser
            except (OSError, PermissionError) as e:
                last_err = e
                time.sleep(0.28)
        raise last_err if last_err is not None else OSError(f"无法打开 {p}")

    def _serial_write_with_retry(self, frame: bytes, retries: int = 2) -> bool:
        """向本机独占串口写一帧；句柄因 USB 重枚举失效时自动重开并重试。"""
        for _ in range(max(1, retries + 1)):
            ser = self._ser
            if ser is None or not getattr(ser, "is_open", False):
                p = self._port_var.get().strip()
                if not p:
                    return False
                try:
                    self._ser = self._open_serial_locked(p, attempts=6)
                    ser = self._ser
                except (OSError, PermissionError):
                    time.sleep(0.2)
                    continue
            try:
                ser.write(frame)
                ser.flush()
                return True
            except (OSError, PermissionError):
                try:
                    ser.close()
                except (OSError, PermissionError):
                    pass
                self._ser = None
                time.sleep(0.25)
        return False

    def _serial_connect(self) -> None:
        p = self._port_var.get().strip()
        if not p:
            messagebox.showwarning("串口", "请选择端口")
            return
        if self._ser is not None and getattr(self._ser, "is_open", False):
            self._sync_connection_status_text()
            self._log(f"串口已连接 {p}")
            return
        if transport_mode() == "ble":
            messagebox.showinfo("串口", "当前为 BLE 模式（CC_TL_TRANSPORT=ble），本页串口连接不适用。")
            self._sync_connection_status_text()
            return

        self._daemon_stopped_for_serial = False
        if _daemon_process_running():
            released = _ensure_daemon_released_for_serial()
            if not released:
                messagebox.showwarning(
                    "串口",
                    "无法结束灯控后台进程，串口仍可能被占用。\n"
                    "请在任务管理器中结束「pythonw / python + daemon_unified」相关进程后再试。",
                )
                return
            self._daemon_stopped_for_serial = True

        last_err: Exception | None = None
        self._ser = None
        try:
            self._ser = self._open_serial_locked(p, attempts=14)
            self._log(f"串口已连接 {p}")
        except (OSError, PermissionError) as e:
            last_err = e
        if last_err is not None:
            messagebox.showerror(
                "串口",
                f"多次尝试仍无法打开「{p}」：{last_err}\n\n"
                "常见原因：① 灯控后台或其它程序仍占用该 COM  ② 串口调试助手 / Arduino 监视器未关。\n"
                "请先关闭占用端口的软件，点「刷新」后再点「连接」。\n\n"
                "仍不知道是谁占着？可先拔插 USB、关掉 Arduino 串口监视器等，详见 docs/SERIAL_PORT_TROUBLESHOOTING.md。\n"
                "详细图文说明见仓库 docs/SERIAL_PORT_TROUBLESHOOTING.md。",
            )
            if self._daemon_stopped_for_serial:
                _start_unified_daemon_silent()
                self._daemon_stopped_for_serial = False
            self._ser = None
        self._sync_connection_status_text()

    def _serial_disconnect(self) -> bool:
        """熄灯、关串口；若曾为独占串口停过守护进程则后台拉起。返回是否执行了拉起守护进程。"""
        try:
            self._send_off_best_effort()
        except (OSError, PermissionError, TclError):
            pass
        if self._ser is not None:
            try:
                self._ser.close()
            except (OSError, PermissionError):
                pass
            self._ser = None
        restarted = False
        if self._daemon_stopped_for_serial:
            # 串口句柄已关闭→COM 已释放，拉起后台并确认其确实接管（最多重试 3 次）
            time.sleep(0.25)
            for _ in range(3):
                if _daemon_process_running():
                    break
                _start_unified_daemon_silent()
                if _wait_daemon_pid_file(2.0, 0.15):
                    break
            self._daemon_stopped_for_serial = False
            restarted = True
        self._sync_connection_status_text()
        self._log("已断开串口并已尝试全灭灯；若曾暂停后台，已尝试恢复灯控进程")
        return restarted

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
        if self._ser is not None and self._ser.is_open:
            if self._serial_write_with_retry(frame):
                self._log(f"试灯已通过本机串口发送 SET_LIGHTING {frame.hex()}")
                self._sync_connection_status_text()
                return
            self._sync_connection_status_text()
            messagebox.showerror(
                "串口",
                "试灯发送失败（已自动重连并重试）。\n\n"
                "本板是 ESP32 原生 USB（VID 303A），偶发会瞬时复位/重新枚举，导致串口句柄失效。\n"
                "请重试一次；若反复失败，可拔插 USB 后点「刷新」→「连接」再试。",
            )
            return
        try:
            submit_gui_proto_hex(frame.hex())
        except OSError as e:
            messagebox.showerror("发送", str(e))
            return
        self._log(
            f"已写入 cc_tl_gui_proto.json → unified_daemon 发送 {frame.hex()}；"
            "若灯不变请先启动 daemon_unified，或在本页点「连接」再发"
        )

    def _save_all(self) -> None:
        doc: dict = {"version": 1}
        doc["basic"] = {
            "port": self._port_var.get().strip(),
            "duty_g": int(self._duty_g.get()),
            "duty_y": int(self._duty_y.get()),
            "duty_r": int(self._duty_r.get()),
            "blink_period_ms": self._parse_nonneg_int(self._blink_period.get(), 800),
            "breath_period_ms": self._parse_nonneg_int(self._breath_period.get(), 2000),
            "boot_autostart_daemon": bool(self._autostart.get()),
            "agent_paths": {agent: self._agent_path_vars[agent].get().strip() for agent in AGENT_ORDER},
        }
        doc["claude"] = {"rows": self._claude_panel.collect()}
        doc["codex"] = {"rows": self._codex_panel.collect()}
        doc["cursor"] = {"rows": self._cursor_panel.collect()}
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
        messagebox.showinfo(
            "保存",
            f"已写入 {CONFIG_PATH}\n\n"
            "• 各 hook 的「模式/颜色/优先级」下一次该 hook 触发即按新配置点灯（无需重启灯控）。\n"
            "• 全局「周期/亮度」灯控后台会自动热重载。\n"
            "• 若你新增/改变了某个 hook 的接线，请在上方重新点一次当前 Agent（或切走再切回），"
            "以便把带 --event 的 hook 重新写入该 IDE 的 hooks 配置。",
        )

    def _reset_to_default(self) -> None:
        if not messagebox.askyesno(
            "重置配置",
            "此操作会全部重置用户自定义的基础设置、程序位置和各 Agent 灯效配置。\n\n是否继续？",
        ):
            return
        doc = default_tl_hook_light_gui_document()
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
        self._load_all(doc)
        messagebox.showinfo("重置配置", f"已重置为内置原始配置并写入：\n{CONFIG_PATH}")
        self._log("已重置为内置原始配置")

    def _load_all(self, source_doc: dict | None = None) -> None:
        doc = source_doc
        if doc is None:
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    doc = json.load(f)
            except (OSError, json.JSONDecodeError):
                doc = {}
        if not doc:
            doc = default_tl_hook_light_gui_document()
        b = doc.get("basic") or {}
        if b.get("port"):
            self._port_var.set(str(b["port"]))
        self._duty_g.set(int(b.get("duty_g", 255)))
        self._duty_y.set(int(b.get("duty_y", 255)))
        self._duty_r.set(int(b.get("duty_r", 255)))
        self._blink_period.set(str(int(b.get("blink_period_ms", 800))))
        self._breath_period.set(str(int(b.get("breath_period_ms", 2000))))
        agent_paths = b.get("agent_paths") or {}
        if isinstance(agent_paths, dict):
            for agent in AGENT_ORDER:
                self._agent_path_vars[agent].set(str(agent_paths.get(agent, "")))
        if "boot_autostart_daemon" in b:
            want = bool(b["boot_autostart_daemon"])
            if want != _autostart_enabled():
                _write_autostart_bat(want)
            self._autostart.set(_autostart_enabled())
        else:
            self._autostart.set(True)
            if not _autostart_enabled():
                try:
                    _write_autostart_bat(True)
                except OSError:
                    pass
        # 旧版为启动文件夹 .bat（经 cmd，登录易闪黑窗）；若仍只有 .bat，升级为无窗口 .vbs
        if bool(self._autostart.get()) and _LEGACY_AUTOSTART_BAT.is_file() and not _AUTOSTART_VBS.is_file():
            try:
                _write_autostart_bat(True)
                self._log("已将开机启动从 .bat 升级为无窗口 .vbs（避免登录时闪控制台）")
            except OSError:
                pass
        self._claude_panel.apply_rows((doc.get("claude") or {}).get("rows"))
        self._codex_panel.apply_rows((doc.get("codex") or {}).get("rows"))
        self._cursor_panel.apply_rows((doc.get("cursor") or {}).get("rows"))
        self._agent_var.set(str(load_config().get("active", "claude")))
        self._refresh_all_agent_path_states()
        self._sync_connection_status_text()
        self._on_refresh_clicked(initial=True)
        self._log(f"已加载 {CONFIG_PATH}" if doc else "无 tl_hook_light_gui.json，使用默认；已同步 active_agent")


def _install_tray_win32_double_click_open(root: tk.Tk, show_window) -> None:
    """pystray Windows 后端只对 WM_LBUTTONUP 调默认动作，不处理双击；此处补上 WM_LBUTTONDBLCLK。"""
    if sys.platform != "win32":
        return
    try:
        import pystray._win32 as pw
    except ImportError:
        return
    WM_LBUTTONDBLCLK = 0x0203
    orig = pw.Icon._on_notify

    def _on_notify(icon_self, wparam, lparam):
        if lparam == WM_LBUTTONDBLCLK:
            try:
                root.after(0, show_window)
            except tk.TclError:
                pass
            return
        return orig(icon_self, wparam, lparam)

    pw.Icon._on_notify = _on_notify  # type: ignore[method-assign]


def main() -> None:
    _cleanup_stale_daemon_runtime_files()
    try:
        import pystray
        from PIL import Image, ImageTk
    except ImportError as e:
        print("缺少依赖，请执行: pip install pystray Pillow", file=sys.stderr)
        raise SystemExit(1) from e

    if not _single_instance_acquire():
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None,
                "VibeCodingLight 已在运行，不能启动多个实例。\n请在系统托盘或任务栏打开现有窗口。",
                "VibeCodingLight",
                0x00000040,
            )
        else:
            print("VibeCodingLight 已在运行，不能启动多个实例。", file=sys.stderr)
        raise SystemExit(0)

    _try_free_console_win32()

    root = tk.Tk()
    root.title("VibeCodingLight")
    w, h = 920, 800
    root.geometry(f"{w}x{h}")
    root.minsize(w, h)
    root.maxsize(w, h)
    root.resizable(False, False)

    img64 = _make_tray_image(64)
    _rs = getattr(getattr(Image, "Resampling", Image), "LANCZOS", getattr(Image, "LANCZOS", 1))
    photo = ImageTk.PhotoImage(img64.resize((32, 32), resample=_rs))
    root.iconphoto(True, photo)
    root._vcl_icon_photo = photo

    tray_holder: dict[str, object] = {"icon": None}

    def show_window() -> None:
        root.deiconify()
        root.lift()
        try:
            root.attributes("-topmost", True)
            root.after(120, lambda: root.attributes("-topmost", False))
        except tk.TclError:
            pass

    def quit_app() -> None:
        ic = tray_holder.get("icon")
        if ic is not None:
            try:
                ic.stop()  # type: ignore[union-attr]
            except Exception:
                pass
        root.destroy()

    def hide_to_tray() -> None:
        root.withdraw()

    _install_tray_win32_double_click_open(root, show_window)

    if sys.platform == "win32":
        menu = pystray.Menu(
            pystray.MenuItem("打开主界面", lambda _icon: root.after(0, show_window)),
            pystray.MenuItem("退出", lambda _icon: root.after(0, quit_app)),
        )
    else:
        menu = pystray.Menu(
            pystray.MenuItem(
                "打开主界面",
                lambda _icon: root.after(0, show_window),
                default=True,
            ),
            pystray.MenuItem("退出", lambda _icon: root.after(0, quit_app)),
        )
    icon = pystray.Icon("vibecodinglight", img64, "VibeCodingLight", menu)
    tray_holder["icon"] = icon

    threading.Thread(target=icon.run, daemon=True).start()
    root.protocol("WM_DELETE_WINDOW", hide_to_tray)

    try:
        TrafficHookLightApp(root)
        root.mainloop()
    finally:
        ic = tray_holder.get("icon")
        if ic is not None:
            try:
                ic.stop()  # type: ignore[union-attr]
            except Exception:
                pass
        _single_instance_release()


if __name__ == "__main__":
    main()
