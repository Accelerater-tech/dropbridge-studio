"""验证 _Event 的 set/reset 是否真的生效（句柄截断会导致静默失败）。"""
import ctypes
import ctypes.wintypes as wt

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateEventW.restype = wt.HANDLE
kernel32.CreateEventW.argtypes = [wt.LPVOID, wt.BOOL, wt.BOOL, wt.LPCWSTR]
kernel32.WaitForSingleObject.restype = wt.DWORD
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]

WAIT_OBJECT_0, WAIT_TIMEOUT = 0, 258


def state(handle) -> str:
    code = kernel32.WaitForSingleObject(handle, 0)
    return {WAIT_OBJECT_0: "signaled", WAIT_TIMEOUT: "quiet"}.get(code, f"code={code}")


name = r"Local\DropBridgeProbeEvent"
handle = kernel32.CreateEventW(None, True, False, name)
print("create ->", state(handle))

kernel32.SetEvent(handle)
print("naive SetEvent ->", state(handle), "err", ctypes.get_last_error())

kernel32.ResetEvent(handle)
print("naive ResetEvent ->", state(handle), "err", ctypes.get_last_error())

kernel32.SetEvent.argtypes = [wt.HANDLE]
kernel32.ResetEvent.argtypes = [wt.HANDLE]
kernel32.SetEvent(handle)
print("typed SetEvent ->", state(handle))
kernel32.ResetEvent(handle)
print("typed ResetEvent ->", state(handle))
kernel32.CloseHandle(handle)
