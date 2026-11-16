"""把窗口顶到前台并点一下屏幕坐标（调试用）。"""
import ctypes
import sys
import time

user32 = ctypes.windll.user32


def focus(title: str) -> bool:
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.4)
    return True


def click(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.15)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP


if __name__ == "__main__":
    title = sys.argv[1] if len(sys.argv) > 1 else "DropBridge Studio"
    print("focused" if focus(title) else "window not found")
    if len(sys.argv) > 3:
        click(int(sys.argv[2]), int(sys.argv[3]))
        print("clicked", sys.argv[2], sys.argv[3])
