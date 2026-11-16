"""查命名停止事件当前是否已存在、是否处于触发状态。"""
import ctypes
import ctypes.wintypes as wt

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateEventW.restype = wt.HANDLE
kernel32.CreateEventW.argtypes = [wt.LPVOID, wt.BOOL, wt.BOOL, wt.LPCWSTR]
kernel32.WaitForSingleObject.restype = wt.DWORD
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]

NAME = r"Local\DropBridgeRadioStop"
handle = kernel32.CreateEventW(None, True, False, NAME)
err = ctypes.get_last_error()
code = kernel32.WaitForSingleObject(handle, 0)
print("already_existed:", err == 183, "| state:", {0: "SIGNALED", 258: "quiet"}.get(code, code))
kernel32.CloseHandle(handle)
