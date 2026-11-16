"""DropBridge Studio — the object pywebview exposes to the UI as ``pywebview.api``."""
from __future__ import annotations

import base64
import ctypes
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from . import config, diag
from .supervisor import Chain

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _clipboard(text: str) -> bool:
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.restype = ctypes.c_void_p
        if not user32.OpenClipboard(None):
            return False
        try:
            user32.EmptyClipboard()
            size = (len(text) + 1) * ctypes.sizeof(ctypes.c_wchar)
            handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
            if not handle:
                return False
            pointer = kernel32.GlobalLock(ctypes.c_void_p(handle))
            ctypes.memmove(pointer, ctypes.c_wchar_p(text), size)
            kernel32.GlobalUnlock(ctypes.c_void_p(handle))
            return bool(user32.SetClipboardData(CF_UNICODETEXT, ctypes.c_void_p(handle)))
        finally:
            user32.CloseClipboard()
    except Exception:
        return False


def _human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


class Api:
    def __init__(self) -> None:
        self.settings = config.Settings()
        self.chain = Chain(self.settings)
        self._window = None
        self._started = time.time()
        self._thumb_cache: dict[str, tuple[float, str]] = {}
        # 自动取证线程：手机一来就把现场打包，不依赖用户记得点按钮
        threading.Thread(target=self._forensics, name="forensics", daemon=True).start()

    # ------------------------------------------------------------- lifecycle
    def boot(self) -> dict:
        if self.settings.get("auto_connect"):
            self.chain.start()
        return self.state()

    def _forensics(self) -> None:
        """手机一来就自动留证：发现请求出现后等 20 秒，把当时的现场打包。"""
        seen = 0
        last = 0.0
        while True:
            time.sleep(2.0)
            try:
                snapshot = self.chain.snapshot()
                if snapshot.get("phase") != "ready":
                    continue
                discovers = (snapshot.get("stats", {}).get("receiver") or {}).get("discovers", 0)
                if discovers <= seen:
                    continue
                seen = discovers
                if time.time() - last < 90.0:   # 一次尝试里手机可能重连好几次，只留一份
                    continue
                time.sleep(20.0)
                last = time.time()
                result = self.capture_bundle(silent=True)
                if result.get("ok"):
                    name = Path(result["path"]).name
                    self.chain._event("diag", f"已自动留证 {name}")
            except Exception:  # noqa: BLE001 — 取证线程绝不能把界面搞崩
                time.sleep(5.0)



    def state(self) -> dict:
        snapshot = self.chain.snapshot()
        snapshot["settings"] = self.settings.as_dict()
        snapshot["env"] = diag.environment(self.settings)
        snapshot["app"] = {"name": config.APP_NAME, "version": config.VERSION,
                           "root": self.settings.root, "outdir": str(self.settings.outdir)}
        return snapshot

    def start(self) -> dict:
        if self.chain.snapshot()["phase"] in ("starting", "ready"):
            return self.state()
        self.chain.start()
        return {"ok": True}

    def stop(self) -> dict:
        self.chain.stop()
        return {"ok": True}

    def restart(self) -> dict:
        self.chain.stop()
        time.sleep(0.6)
        self.chain.start()
        return {"ok": True}

    def quit(self) -> dict:
        try:
            self.chain.stop()
        finally:
            os._exit(0)

    # ------------------------------------------------------- windows 集成
    def autostart(self, enabled: bool | None = None) -> dict:
        """读/写开机自启（「启动」文件夹里的快捷方式）。"""
        from . import system

        if enabled is None:
            return {"enabled": system.autostart_enabled()}
        return {"enabled": system.set_autostart(bool(enabled))}

    def open_dir(self, which: str = "received") -> dict:
        from . import system

        target = self.settings.outdir if which == "received" else self.settings.root
        system.open_path(target)
        return {"ok": True}

    def self_test(self) -> dict:
        """自己投一个文件给自己：证明「电脑这端」没问题。"""
        from . import selftest

        if self.chain.snapshot()["phase"] != "ready":
            return {"ok": False, "steps": [], "error": "链路还没就绪，先点「启动接收」"}
        return selftest.run(self.settings.outdir)


    # ------------------------------------------------------------------ logs
    def logs(self, name: str = "all", limit: int = 400) -> list:
        return self.chain.logs(name, int(limit))

    def clear_transfers(self) -> dict:
        self.chain.clear_transfers()
        return {"ok": True}

    # --------------------------------------------------------------- thumbnails
    def thumb(self, path: str) -> str | None:
        cached = self._thumb_cache.get(path)
        if cached and abs(cached[0] - os.path.getmtime(path)) < 1:
            return cached[1]
        try:
            from PIL import Image
            image = Image.open(path)
            image.thumbnail((480, 480))
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, "JPEG", quality=82)
            data = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
            self._thumb_cache[path] = (os.path.getmtime(path), data)
            return data
        except Exception:
            return None

    # --------------------------------------------------------------- settings
    def settings_update(self, patch: dict) -> dict:
        self.settings.update(patch or {})
        return {"ok": True, "settings": self.settings.as_dict()}

    def pick_folder(self, current: str = "") -> str | None:
        import webview
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG,
                                                directory=current or self.settings.root)
        if result:
            return result[0]
        return None

    def choose_root(self) -> str | None:
        import webview
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG, directory=self.settings.root or "C:\\")
        if result:
            self.settings.update({"root": result[0]})
            self.chain.stop()
        return result[0] if result else None

    # --------------------------------------------------------------- file ops
    def open_path(self, path: str) -> dict:
        if not path or not Path(path).exists():
            return {"ok": False, "error": "路径不存在"}
        os.startfile(path)  # noqa: S606 - opens with the shell, user-initiated
        return {"ok": True}

    def reveal(self, path: str) -> dict:
        if not path or not Path(path).exists():
            return {"ok": False, "error": "路径不存在"}
        subprocess.Popen(["explorer.exe", "/select,", str(Path(path))])
        return {"ok": True}

    def copy_path(self, path: str) -> dict:
        return {"ok": _clipboard(path)}

    def open_outdir(self) -> dict:
        return self.open_path(str(self.settings.outdir))

    # -------------------------------------------------------------- doctor
    def doctor(self) -> dict:
        running = self.chain.snapshot()["phase"] == "ready"
        checks = diag.run_checks(self.settings, running)
        return {"checks": checks, "env": diag.environment(self.settings),
                "ok": all(item["ok"] for item in checks)}

    def fix(self, action: str) -> dict:
        if action == "reclaim":
            killed = self.chain.reclaim()
            return {"ok": True, "message": f"已回收 {killed} 个残留进程"}
        if action == "open_outdir":
            return self.open_path(str(self.settings.outdir))
        if action == "open_keys":
            return self.open_path(str(self.settings.keys))
        if action == "check_plug":
            return {"ok": True, "message": "请把 RTL8821CU 网卡插到 USB 口（需要直连，不要经过 Hub 供电不足的口）"}
        if action == "install_driver":
            return self.install_driver()
        return {"ok": False, "error": "未知操作"}

    def install_driver(self) -> dict:
        driver_dir = config.HERE / "assets" / "driver"
        inf = driver_dir / "airbridge-winusb.inf"
        if not inf.is_file():
            return {"ok": False, "error": "缺少驱动文件"}
        log = config.studio_dir(self.settings.root) / "driver-install.log"
        script = config.studio_dir(self.settings.root) / "install-driver.ps1"
        script.write_text(
            "$ErrorActionPreference='Continue'\n"
            f"$d='{driver_dir}'\n"
            f"$log='{log}'\n"
            "\"driver install $(Get-Date -Format o)\" | Out-File -Append -Encoding utf8 $log\n"
            "certutil -addstore -f Root (Join-Path $d 'dropbridge-driver.cer') *>> $log\n"
            "certutil -addstore -f TrustedPublisher (Join-Path $d 'dropbridge-driver.cer') *>> $log\n"
            "& pnputil.exe /add-driver (Join-Path $d 'airbridge-winusb.inf') /install *>> $log\n"
            "'exit=' + $LASTEXITCODE | Out-File -Append -Encoding utf8 $log\n",
            encoding="utf-8-sig")
        try:
            subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-Command", f"Start-Process powershell -Verb RunAs -Wait -ArgumentList "
                                        f"'-NoProfile','-ExecutionPolicy','Bypass','-File','{script}'"],
                           timeout=180, creationflags=0x08000000)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "驱动安装超时（可能取消了 UAC）"}
        except OSError as error:
            return {"ok": False, "error": str(error)}
        state = diag.driver_state()
        text = log.read_text(encoding="utf-8", errors="replace")[-1200:] if log.exists() else ""
        return {"ok": state["bound"], "bound": state["bound"], "service": state["service"],
                "log": text}

    # ----------------------------------------------------------------- report
    def export_report(self) -> dict:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = config.studio_dir(self.settings.root) / f"diagnostics-{stamp}.json"
        diag.export_report(self.settings, self.chain, target)
        return {"ok": True, "path": str(target)}

    def capture_bundle(self, silent: bool = False) -> dict:
        """把一次实测需要的全部材料打成一个压缩包（时间线 + 日志 + 体检 + 环境）。"""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        folder = config.studio_dir(self.settings.root) / "captures"
        folder.mkdir(parents=True, exist_ok=True)
        payload = diag.report_payload(self.settings, self.chain)
        payload["events"] = self.chain.snapshot().get("events", [])
        payload["note"] = ("这是 DropBridge Studio 自动抓的实测包："
                           "events 是手机每次来的痕迹，disk_logs 是后端原始日志。")
        target = folder / f"capture-{stamp}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("capture.json", json.dumps(payload, ensure_ascii=False, indent=2))
            run_dir = getattr(self.chain, "run_dir", None)
            if run_dir:
                for log in sorted(Path(run_dir).glob("*.log")):
                    try:
                        zf.write(log, arcname=f"logs/{log.name}")
                    except OSError:
                        pass
        return {"ok": True, "path": str(target)}

    def open_report(self) -> dict:
        target = config.studio_dir(self.settings.root)
        return self.open_path(str(target))

    # ------------------------------------------------------------------- info
    def about(self) -> dict:
        return {
            "app": config.APP_NAME,
            "version": config.VERSION,
            "root": self.settings.root,
            "received": str(self.settings.outdir),
            "uptime": int(time.time() - self._started),
            "python": sys.version.split()[0],
        }
