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

from . import config, system

REFRESH_SECONDS = 3.0


def human_size(size) -> str:
    try:
        value = float(size or 0)
    except (TypeError, ValueError):
        value = 0.0
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


class Tray:
    def __init__(self, api, window) -> None:
        self.api = api
        self.window = window
        self._icon: pystray.Icon | None = None
        self._thread: threading.Thread | None = None
        self._told_hidden = False
        self._seen: set = set()
        self._primed = False

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
        discovery = state.get("discovery") or {}
        peers = discovery.get("awdl_peers") or 0
        if phase == "ready" and peers:
            text += f" · 对端 {peers}"
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
        system.open_path(self.api.settings.outdir)

    def _toggle_autostart(self, *_args) -> None:
        enabled = system.set_autostart(not system.autostart_enabled())
        self.api.settings_update({"autostart": bool(enabled)})

    # ----- 提示 -----------------------------------------------------------
    def notify(self, title: str, message: str) -> None:
        if not self._icon or not self.api.settings.get("notify", True):
            return
        try:
            self._icon.notify(message, title)
        except Exception:
            pass

    def hint_hidden_once(self) -> None:
        """第一次关窗口时告诉用户：它没退出，在右下角。"""
        if self._told_hidden:
            return
        self._told_hidden = True
        self.notify(config.APP_NAME, "还在后台接收中，双击托盘图标可以打开窗口。")

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
            pystray.MenuItem(
                "开机自启",
                self._toggle_autostart,
                checked=lambda _item: system.autostart_enabled(),
            ),
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
            self._watch_transfers()

    def _watch_transfers(self) -> None:
        """有文件落盘就弹一条气泡，窗口藏起来时也知道收到了什么。"""
        try:
            state = self.api.state()
        except Exception:
            return
        rows = state.get("transfers") or []
        # 只关心已经收完的，正在传输中的下一轮再说
        done = {str(row.get("path")): row for row in rows
                if str(row.get("status")) != "receiving"}
        if not self._primed:
            # 第一次只记下已有的，避免把历史文件当新文件
            self._seen = set(done)
            self._primed = True
            return
        for path, row in done.items():
            if path in self._seen:
                continue
            name = row.get("name") or "文件"
            self.notify("收到文件", f"{name} · {human_size(row.get('size') or 0)}")
        self._seen |= set(done)

    def refresh(self) -> None:
        if self._icon is None:
            return
        try:
            self._icon.title = self._title()
        except Exception:
            pass

    def running(self) -> bool:
        """托盘图标是否还活着（窗口藏起来时靠它确认程序没退出）。"""
        thread = self._thread
        return bool(self._icon is not None and thread is not None and thread.is_alive())

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()
            self._icon = None
