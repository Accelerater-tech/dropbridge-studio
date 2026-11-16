"""验证「关闭窗口留在托盘」：发 WM_CLOSE，然后看窗口是不是只是被藏起来。"""
import ctypes
import ctypes.wintypes as wt
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
TITLE = sys.argv[1] if len(sys.argv) > 1 else "DropBridge Studio"

hwnd = user32.FindWindowW(None, TITLE)
print("hwnd:", hwnd, "visible:", bool(user32.IsWindowVisible(hwnd)) if hwnd else None)
if not hwnd:
    raise SystemExit("window not found")

WM_CLOSE = 0x0010
user32.PostMessageW(wt.HWND(hwnd), WM_CLOSE, 0, 0)
time.sleep(2.5)

hwnd2 = user32.FindWindowW(None, TITLE)
print("after close -> hwnd:", hwnd2,
      "visible:", bool(user32.IsWindowVisible(hwnd2)) if hwnd2 else None)
