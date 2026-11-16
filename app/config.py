"""DropBridge Studio — configuration and paths.

The studio is a controller: it drives the existing DropBridge backend
binaries (radio / bridge / netd / awdld / receiver) instead of reimplementing
them.  Everything it writes lives next to that backend, under data/studio/.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "DropBridge Studio"
APP_ID = "DropBridgeStudio"
VERSION = "1.0.0"

# 打包成 exe 后资源在 PyInstaller 的解包目录里；源码运行时就是项目根。
FROZEN = bool(getattr(sys, "frozen", False))
HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
EXE_PATH = Path(sys.executable).resolve() if FROZEN else None
WEB_DIR = HERE / "web"
ASSET_DIR = HERE / "assets"

# Candidate install roots, best first.  The first one that actually contains
# the radio backend wins when the user has not chosen a root yet.
_ROOTS = [
    *([EXE_PATH.parent] if FROZEN else []),
    Path(r"C:\Users\50174\Desktop\DropBridge"),
    HERE.parent / "DropBridge-app" / "DropBridge",
    Path(r"C:\Program Files\DropBridge"),
]

DEFAULTS = {
    "root": "",
    "device_name": "DropBridge",
    "model": "MacBookPro18,3",
    "channel": 149,
    "width": 20,
    "chanseq": "social",
    "tcp_merge": True,
    "flags": "0x3fb",
    "outdir": "",
    "keys": "",
    "beacon": True,
    "welcome_seen": False,
    "auto_connect": True,
    "auto_restart": True,
    "notify": True,
    "radio_verbose": False,
    "trace": True,
    "close_to_tray": False,
    "max_receive_percent": 30,
}


def _has_backend(root: Path) -> bool:
    return (root / "backend" / "airbridge_radio.exe").is_file()


def detect_root() -> str:
    for candidate in _ROOTS:
        try:
            if _has_backend(candidate):
                return str(candidate)
        except OSError:
            continue
    return ""


def data_dir(root: str) -> Path:
    return Path(root) / "data"


def studio_dir(root: str) -> Path:
    path = data_dir(root) / "studio"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path(root: str) -> Path:
    return studio_dir(root) / "settings.json"


class Settings:
    """Tiny JSON-backed settings store with sane derived paths."""

    def __init__(self) -> None:
        self._root = detect_root()
        self._values = dict(DEFAULTS)
        if self._root:
            self._values["root"] = self._root
        self.load()
        if not Path(self._values.get("root") or "").is_dir():
            self._values["root"] = self._root or ""

    # -- io ---------------------------------------------------------------
    def load(self) -> None:
        root = self._values.get("root") or self._root
        if not root:
            return
        path = settings_path(root)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(raw, dict):
            for key, value in raw.items():
                if key in DEFAULTS and isinstance(value, type(DEFAULTS[key])) or key in DEFAULTS and value is None:
                    self._values[key] = value
                elif key in DEFAULTS:
                    try:
                        self._values[key] = type(DEFAULTS[key])(value)
                    except (TypeError, ValueError):
                        pass

    def save(self) -> None:
        root = self.root
        if not root:
            return
        path = settings_path(root)
        path.write_text(json.dumps(self._values, indent=2, ensure_ascii=False), encoding="utf-8")

    # -- accessors --------------------------------------------------------
    def as_dict(self) -> dict:
        return dict(self._values)

    def update(self, patch: dict) -> dict:
        for key, value in patch.items():
            if key not in DEFAULTS:
                continue
            default = DEFAULTS[key]
            if isinstance(default, bool):
                value = bool(value)
            elif isinstance(default, int):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
            elif isinstance(default, str):
                value = str(value)
            self._values[key] = value
        if self._values.get("root"):
            studio_dir(self._values["root"])
        self.save()
        return self.as_dict()

    @property
    def root(self) -> str:
        return str(self._values.get("root") or "")

    @property
    def backend(self) -> Path:
        return Path(self.root) / "backend"

    @property
    def data(self) -> Path:
        return data_dir(self.root)

    @property
    def outdir(self) -> Path:
        raw = self._values.get("outdir") or ""
        return Path(raw) if raw else self.data / "received"

    @property
    def keys(self) -> Path:
        raw = self._values.get("keys") or ""
        return Path(raw) if raw else self.data / "keys"

    @property
    def logs(self) -> Path:
        path = studio_dir(self.root) / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def python(self) -> str:
        bundled = self.backend / "python" / "python.exe"
        if bundled.is_file():
            return str(bundled)
        return os.environ.get("DS_PYTHON") or "python"

    def get(self, key: str, default=None):
        return self._values.get(key, default)

    def __getitem__(self, key):
        return self._values[key]
