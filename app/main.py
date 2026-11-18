"""DropBridge Studio — application entry point (pywebview + WebView2)."""
from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

import webview

from . import config
from .api import Api


def _single_instance() -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, "Local\\DropBridgeStudio.Single")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return False
    globals()["_mutex_handle"] = handle
    return True


def _trace(message: str) -> None:
    """启动阶段排障用：写到临时目录，浏览器端看不见也能事后翻。"""
    try:
        path = Path(tempfile.gettempdir()) / "dropbridge-studio-startup.log"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%H:%M:%S')} {message}\n")
    except OSError:
        pass


def _activate_existing() -> bool:
    """第二个实例起来时，把已经藏着的主窗口重新叫出来，而不是弹个框。"""
    user32 = ctypes.windll.user32
    for _ in range(20):
        hwnd = user32.FindWindowW(None, config.APP_NAME)
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE：从托盘藏起来的状态恢复
            user32.SetForegroundWindow(hwnd)
            return True
        time.sleep(0.15)
    return False


def _report_startup_error(error: BaseException) -> None:
    try:
        path = Path(tempfile.gettempdir()) / "dropbridge-studio-error.log"
        path.write_text(traceback.format_exc(), encoding="utf-8")
    except OSError:
        pass


def _apply_icon() -> None:
    """WM_SETICON + 任务栏重绘，让标题栏和任务栏都显示 Studio 图标。"""
    ico = config.ASSET_DIR / "studio.ico"
    if not ico.is_file():
        return
    user32 = ctypes.windll.user32
    time.sleep(0.6)
    hwnd = user32.FindWindowW(None, config.APP_NAME)
    if not hwnd:
        return
    load_image = user32.LoadImageW
    load_image.restype = ctypes.c_void_p
    for size, kind in ((16, 0), (32, 0), (48, 0), (256, 1)):
        handle = load_image(None, str(ico), 1, size, size, 0x10)  # IMAGE_ICON
        if handle:
            user32.SendMessageW(hwnd, 0x0080, kind, ctypes.c_void_p(handle))  # WM_SETICON


def _auto_start(api: Api) -> None:
    """窗口显示后再起链路：用户打开软件就是在等接收，不用再点一次。"""
    time.sleep(1.2)
    try:
        api.start()
    except Exception:
        _report_startup_error(sys.exc_info()[1])


def main() -> int:
    # 打包成 --noconsole 的 exe 时没有控制台，stdout/stderr 是 None，
    # 任何 print 都会炸；给它们接上黑洞。
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))

    page = ""
    for index, arg in enumerate(sys.argv[1:], start=1):
        if arg == "--page" and index < len(sys.argv) - 1:
            page = sys.argv[index + 1]
        elif arg.startswith("--page="):
            page = arg.split("=", 1)[1]

    if not _single_instance():
        if not _activate_existing():
            ctypes.windll.user32.MessageBoxW(
                None, "DropBridge Studio 已经在运行了。", config.APP_NAME, 0x40)
        return 0

    if os.environ.get("STUDIO_DEBUG"):
        # WebView2 会把这个环境变量里的参数加到命令行，调试时可以走 CDP
        os.environ.setdefault(
            "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
            "--remote-debugging-port=9333 --remote-allow-origins=*")

    api = Api()
    url = (config.WEB_DIR / "index.html").as_uri()
    if page:
        url += "#" + page

    storage = Path(tempfile.gettempdir()) / "dropbridge-studio-webview"
    # 开机自启 + 「启动后最小化」：窗口一开始就别弹，等用户点托盘图标再出来
    hidden_start = bool(api.settings.get("start_minimized"))
    window = webview.create_window(
        config.APP_NAME,
        url,
        js_api=api,
        width=1280,
        height=840,
        min_size=(1060, 700),
        background_color="#080b11",
        text_select=False,
        hidden=hidden_start,
    )
    api._window = window
    tray_holder: list = []

    def on_closing() -> bool:
        # 默认像 QQ/微信：关窗口只是收起来，链路和托盘继续在。
        # 真想退出，用托盘菜单的「退出」。
        if api.settings.get("close_to_tray") and tray_holder:
            try:
                window.hide()
                tray_holder[0].hint_hidden_once()
            except Exception:
                pass
            return False
        try:
            api.chain.stop()
        finally:
            if tray_holder:
                tray_holder[0].stop()
            return True

    window.events.closing += on_closing

    def on_start() -> None:
        """窗口起来后把图标换成自己的（WebView2 默认给的是 Python 图标）。"""
        _apply_icon()
        try:
            from .tray import Tray

            tray = Tray(api, window)
            tray.start()
            tray_holder.append(tray)
            api.tray = tray
        except Exception:
            _report_startup_error(sys.exc_info()[1])
        if api.settings.get("auto_connect"):
            threading.Thread(target=_auto_start, args=(api,), daemon=True).start()
        if hidden_start and not tray_holder:
            # 托盘起不来就不能藏着——否则用户永远找不到窗口
            try:
                window.show()
            except Exception:  # noqa: BLE001
                pass

    try:
        webview.start(on_start, debug=False, private_mode=False, storage_path=str(storage))
    except Exception as error:  # pragma: no cover - GUI level failure
        _report_startup_error(error)
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
