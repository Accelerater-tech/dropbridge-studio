"""托盘图标：关掉窗口也继续接，右键就能启停。

pystray 的图标回调跑在自己的线程里，所有对窗口的操作都用
`webview` 提供的调度（show/hide 内部会切回 UI 线程）。
"""
from __future__ import annotations

import threading
import time
from typing import Callable

import pystray
from PIL import Image

from . import config

REFRESH_SECONDS = 3.0


class Tray:
    def __init__(self, api, window) -> None:
        self.api = api
        self.window = window
        self._icon: pystray.Icon | None = None
        self._thread: threading.Thread | None = None

    # ----- 数据 -----------------------------------------------------------
    def _image(self) -> Image.Image:
        png = config.ASSET_DIR / "studio.png"
        if png.is_file():
            return Image.open(png)
        return Image.new("RGB", (64, 64), (18, 24, 40))

    def _title(self) -> str:
        state = self.api.state()
        phase = state.get("phase", "stopped")
        text = {
            "ready": "接收就绪",
            "starting": "启动中…",
            "stopping": "正在停止",
            "error": "链路异常",
        }.get(phase, "未启动")
        return f"{config.APP_NAME} · {text}"

    # ----- 菜单动作 -------------------------------------------------------
    def _show(self, *_args) -> None:
        try:
            self.window.show()
            self.window.restore()
        except Exception:
            pass

    def _quit(self, *_args) -> None:
        try:
            self.api.chain.stop()
        finally:
            if self._icon:
                self._icon.stop()
            try:
                self.window.destroy()
            except Exception:
                pass

    def _start(self, *_args) -> None:
        threading.Thread(target=self.api.start, daemon=True).start()

    def _stop(self, *_args) -> None:
        threading.Thread(target=self.api.stop, daemon=True).start()

    def _open_received(self, *_args) -> None:
        from . import system

        system.open_path(self.api.settings.outdir)

    # ----- 生命周期 -------------------------------------------------------
    def start(self) -> None:
        if self._icon is not None:
            return
        if not config.ASSET_DIR.joinpath("studio.png").is_file():
            return
        menu = pystray.Menu(
            pystray.MenuItem("显示主窗口", self._show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("启动接收", self._start),
            pystray.MenuItem("停止接收", self._stop),
            pystray.MenuItem("打开接收文件夹", self._open_received),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._quit),
        )
        self._icon = pystray.Icon(config.APP_ID, self._image(), config.APP_NAME, menu)
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()
        threading.Thread(target=self._refresh_loop, daemon=True).start()

    def _refresh_loop(self) -> None:
        while self._icon is not None:
            time.sleep(REFRESH_SECONDS)
            self.refresh()

    def refresh(self) -> None:
        if self._icon is None:
            return
        try:
            self._icon.title = self._title()
        except Exception:
            pass

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()
            self._icon = None
