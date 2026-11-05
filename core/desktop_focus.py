"""Read-only foreground checks; never steal focus from the user's application."""
import ctypes
from ctypes import wintypes
import os


def external_window_focused():
    try:
        user32 = ctypes.windll.user32
        foreground = user32.GetForegroundWindow
        foreground.restype = wintypes.HWND
        get_pid = user32.GetWindowThreadProcessId
        get_pid.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        handle = foreground()
        pid = wintypes.DWORD()
        if not handle or not get_pid(handle, ctypes.byref(pid)):
            return False
        return pid.value != 0 and pid.value != os.getpid()
    except (AttributeError, OSError):
        return False
