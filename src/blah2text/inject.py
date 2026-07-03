"""Inject text at the cursor of whatever app has focus.

Two methods, chosen by config:
  * "clipboard" — put text on the clipboard, send Ctrl+V, restore the old
    clipboard text afterwards. Fast for long text; needs the target app to
    support paste.
  * "type" — synthesize each character with ctypes SendInput and
    KEYEVENTF_UNICODE. Slower, but works in apps that ignore paste
    (including many terminals) and is layout-independent.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import time

# --- Win32 SendInput plumbing -------------------------------------------

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_RETURN = 0x0D
VK_V = 0x56

# Foreground processes that get Ctrl+Shift+V instead of Ctrl+V. These
# terminals intercept the chord themselves and feed the clipboard to the
# inner program as typed input, so pasting works even when that program
# (Claude Code, vim, a REPL) has no Ctrl+V binding of its own.
DEFAULT_TERMINAL_PROCESSES = (
    "wezterm-gui.exe",
    "windowsterminal.exe",
    "alacritty.exe",
    "mintty.exe",
    "hyper.exe",
    "ghostty.exe",
)

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


def _key_input(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return inp


def _send_inputs(events: list[INPUT]) -> None:
    arr = (INPUT * len(events))(*events)
    sent = ctypes.windll.user32.SendInput(len(events), arr,
                                          ctypes.sizeof(INPUT))
    if sent != len(events):
        raise OSError(f"SendInput injected {sent}/{len(events)} events")


def _type_unicode(text: str) -> None:
    """Type text as KEYEVENTF_UNICODE events (handles emoji via surrogates)."""
    events: list[INPUT] = []
    for ch in text:
        if ch in ("\n", "\r"):
            events.append(_key_input(vk=VK_RETURN))
            events.append(_key_input(vk=VK_RETURN, flags=KEYEVENTF_KEYUP))
            continue
        raw = ch.encode("utf-16-le")
        for i in range(0, len(raw), 2):
            unit = int.from_bytes(raw[i:i + 2], "little")
            events.append(_key_input(scan=unit, flags=KEYEVENTF_UNICODE))
            events.append(_key_input(scan=unit,
                                     flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    if events:
        _send_inputs(events)


def _send_ctrl_v(shift: bool = False) -> None:
    events = [_key_input(vk=VK_CONTROL)]
    if shift:
        events.append(_key_input(vk=VK_SHIFT))
    events.append(_key_input(vk=VK_V))
    events.append(_key_input(vk=VK_V, flags=KEYEVENTF_KEYUP))
    if shift:
        events.append(_key_input(vk=VK_SHIFT, flags=KEYEVENTF_KEYUP))
    events.append(_key_input(vk=VK_CONTROL, flags=KEYEVENTF_KEYUP))
    _send_inputs(events)


def _foreground_process_name() -> str:
    """Executable name (lowercase) of the app that owns the focused window."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,
                                  False, pid.value)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf,
                                               ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1].lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


# --- Clipboard handling (pywin32) ----------------------------------------

def _open_clipboard(retries: int = 5):
    """Open the clipboard, retrying briefly if another app holds it."""
    import win32clipboard
    for attempt in range(retries):
        try:
            win32clipboard.OpenClipboard()
            return win32clipboard
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(0.05)


def _get_clipboard_text() -> str | None:
    import win32con
    clip = _open_clipboard()
    try:
        if clip.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return clip.GetClipboardData(win32con.CF_UNICODETEXT)
        return None  # non-text contents: we can't save/restore those
    finally:
        clip.CloseClipboard()


def _set_clipboard_text(text: str) -> None:
    import win32con
    clip = _open_clipboard()
    try:
        clip.EmptyClipboard()
        clip.SetClipboardData(win32con.CF_UNICODETEXT, text)
    finally:
        clip.CloseClipboard()


def _paste_clipboard(text: str, restore: bool = True,
                     terminal_processes=DEFAULT_TERMINAL_PROCESSES) -> None:
    use_shift = _foreground_process_name() in {
        p.lower() for p in terminal_processes
    }
    saved = _get_clipboard_text() if restore else None
    _set_clipboard_text(text)
    time.sleep(0.05)          # let the clipboard update settle
    _send_ctrl_v(shift=use_shift)
    time.sleep(0.15)          # let the target app read it before restoring
    if restore and saved is not None:
        _set_clipboard_text(saved)


# --- Public entry point ---------------------------------------------------

def inject(text: str, method: str = "clipboard",
           restore_clipboard: bool = True,
           terminal_processes=DEFAULT_TERMINAL_PROCESSES) -> None:
    """Insert text at the focused app's cursor via the configured method."""
    if not text:
        return
    if method == "type":
        _type_unicode(text)
    elif method == "clipboard":
        _paste_clipboard(text, restore=restore_clipboard,
                         terminal_processes=terminal_processes)
    else:
        raise ValueError(f"unknown inject method: {method!r} "
                         "(expected 'clipboard' or 'type')")
