"""跨平台「进程是否存活」探测工具。

⚠ 严重陷阱：在 Windows 上，CPython 的 os.kill(pid, sig) 是用
   OpenProcess(...) + TerminateProcess(handle, sig) 实现的。
   因此 os.kill(pid, 0) 并不是 Unix 那种「发送空信号探测存活」，
   而是会以退出码 0 直接【杀死】目标进程！

   本项目曾因在 GUI 里用 os.kill(pid, 0) 探测灯控守护进程，导致每次刷新
   状态时把刚启动的 daemon 杀掉（现象：状态短暂变绿后瞬间变回未运行）。

   任何「判断某 PID 是否还在运行」的需求，都必须使用本模块的 pid_alive()，
   切勿再写 os.kill(pid, 0)。
"""

from __future__ import annotations

import os
import sys


def pid_alive(pid: int) -> bool:
    """返回 PID 对应进程是否存活。绝不会杀死或影响目标进程。"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _pid_alive_windows(pid)
    return _pid_alive_posix(pid)


def _pid_alive_posix(pid: int) -> bool:
    try:
        os.kill(pid, 0)  # POSIX: 信号 0 仅做存在性/权限探测，不影响进程
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 进程存在但无权发信号
    except OSError:
        return False
    return True


def _pid_alive_windows(pid: int) -> bool:
    """用 OpenProcess + GetExitCodeProcess 探测，绝不调用 TerminateProcess。"""
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    ERROR_ACCESS_DENIED = 5

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    OpenProcess = kernel32.OpenProcess
    OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    OpenProcess.restype = wintypes.HANDLE

    GetExitCodeProcess = kernel32.GetExitCodeProcess
    GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    GetExitCodeProcess.restype = wintypes.BOOL

    CloseHandle = kernel32.CloseHandle
    CloseHandle.argtypes = [wintypes.HANDLE]
    CloseHandle.restype = wintypes.BOOL

    ctypes.set_last_error(0)
    handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # 句柄打不开：拒绝访问通常意味着进程存在但无权限；其它错误视为不存在
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if GetExitCodeProcess(handle, ctypes.byref(code)):
            return code.value == STILL_ACTIVE
        # 查询失败时保守认为仍在运行，避免误删 PID 文件
        return True
    finally:
        CloseHandle(handle)
