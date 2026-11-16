"""DropBridge Studio — health checks ("一键体检") and environment info."""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import winreg
from pathlib import Path

import psutil

from . import config
from .supervisor import busy_ports, CHAIN, TCP_PORTS, UDP_PORTS

DEVICE_KEY = r"SYSTEM\CurrentControlSet\Enum\USB\VID_0BDA&PID_C820&MI_02"
ADAPTER_HINT = "Realtek 8821CU"


def _device_instance() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, DEVICE_KEY) as key:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(key, index)
                except OSError:
                    return None
                index += 1
                if name.startswith("7&") or name.startswith("6&") or name.startswith("5&"):
                    return name
    except OSError:
        return None
    return None


def driver_state() -> dict:
    instance = _device_instance()
    if not instance:
        return {"present": False, "service": None, "bound": False}
    service = None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{DEVICE_KEY}\\{instance}") as key:
            service, _ = winreg.QueryValueEx(key, "Service")
    except OSError:
        pass
    return {
        "present": True,
        "service": service,
        "bound": (service or "").upper() == "WINUSB",
    }


def _adapter_present() -> bool:
    try:
        out = subprocess.run(
            ["ipconfig", "/all"], capture_output=True, text=True, timeout=12,
            encoding="mbcs", errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return ADAPTER_HINT in out


def _port_owners() -> str:
    names = {p.lower() for p in ("airbridge_radio.exe", "radio_pipe_bridge.exe",
                                 "awdl_netd.exe", "awdld.exe", "python.exe", "pythonw.exe")}
    found = set()
    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info.get("name") or "").lower()
        except (psutil.Error, OSError):
            continue
        if name in names:
            found.add(name)
    return "疑似上一轮链路仍在运行: " + ", ".join(sorted(found)) if found else ""


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_bytes(b"ok")
        probe.unlink()
        return True
    except OSError:
        return False


def _check(check_id: str, title: str, ok: bool, detail: str, fix: str = "") -> dict:
    return {"id": check_id, "title": title, "ok": bool(ok), "detail": detail, "fix": fix}


def run_checks(settings: config.Settings, chain_running: bool) -> list:
    root = Path(settings.root) if settings.root else None
    backend = settings.backend if root else None
    checks = []

    checks.append(_check(
        "root", "安装目录",
        bool(root and root.is_dir() and (backend / "airbridge_radio.exe").is_file()),
        str(root) if root else "未找到 DropBridge 安装目录",
        "choose_root"))

    missing = [p.name for p in (
        backend / "airbridge_radio.exe", backend / "radio_pipe_bridge.exe",
        backend / "awdl_netd.exe", backend / "awdld.exe",
        backend / "airdrop" / "receiver.py") if not p.is_file()] if backend else ["全部"]
    checks.append(_check(
        "files", "后端程序", not missing,
        "5 个后端组件齐全" if not missing else "缺少: " + ", ".join(missing),
        "choose_root"))

    drv = driver_state()
    if not drv["present"]:
        checks.append(_check("driver", "RTL8821CU 驱动", False,
                             "未检测到网卡（USB ID 0bda:c820）", "check_plug"))
    elif drv["bound"]:
        checks.append(_check("driver", "RTL8821CU 驱动", True,
                             "WinUSB 已绑定 (MI_02)，可用于 AWDL", ""))
    else:
        checks.append(_check("driver", "RTL8821CU 驱动", False,
                             f"当前驱动为 {drv['service'] or '未知'}，需要绑定 WinUSB", "install_driver"))

    # 绑定 WinUSB 后，这块 USB 网卡会从 Windows 的网卡列表里消失（被 libusb 独占），
    # 所以「设备在位」以 USB 实例存在为准，ipconfig 里是否还有 Realtek 网卡只作补充信息。
    if not drv["present"]:
        checks.append(_check("adapter", "设备在位", False,
                             "未插入 RTL8821CU（0bda:c820）", "check_plug"))
    elif _adapter_present():
        checks.append(_check("adapter", "设备在位", True,
                             "RTL8821CU 在位（仍在 Windows 网卡列表中）", ""))
    else:
        checks.append(_check("adapter", "设备在位", True,
                             "RTL8821CU 在位（已被 WinUSB 独占，网卡列表不可见属正常）", ""))

    held = busy_ports()
    if chain_running:
        checks.append(_check("ports", "端口占用", True,
                             "链路运行中，端口由本程序持有", ""))
    elif not held:
        checks.append(_check("ports", "端口占用", True,
                             "49876 / 49877 / 8771 / 15353 可用", ""))
    else:
        owners = _port_owners()
        checks.append(_check(
            "ports", "端口占用", False,
            f"被占用: {', '.join(map(str, held))}"
            + (f"（{owners}）" if owners else ""),
            "reclaim"))

    py = Path(settings.python)
    checks.append(_check("python", "接收器运行时",
                         py.is_file() or shutil.which(settings.python) is not None,
                         str(py) if py.is_file() else "使用系统 Python", ""))

    checks.append(_check("outdir", "接收目录", _writable(settings.outdir),
                         str(settings.outdir), "open_outdir"))

    keys_ok = settings.keys.is_dir() and any(settings.keys.iterdir())
    checks.append(_check("keys", "AirDrop 身份密钥", keys_ok,
                         str(settings.keys) if keys_ok else "首次启动会自动生成",
                         "open_keys"))

    checks.append(_check("beacon", "蓝牙信标", (backend / "beacon.ps1").is_file() if backend else False,
                         "beacon.ps1 存在，可广播 AirDrop 提示" if backend and (backend / "beacon.ps1").is_file()
                         else "未找到 beacon.ps1", ""))

    return checks


def environment(settings: config.Settings) -> dict:
    version = ""
    try:
        raw = (Path(settings.root) / "VERSION.txt").read_text(encoding="utf-8-sig", errors="replace")
        version = " · ".join(part.strip() for part in raw.splitlines() if part.strip())
    except OSError:
        pass
    drv = driver_state()
    return {
        "app": config.VERSION,
        "python": platform.python_version(),
        "os": platform.platform(),
        "root": settings.root,
        "backend_version": version.replace("\n", " · "),
        "driver": drv,
        "cpu": psutil.cpu_percent(interval=None),
        "mem": psutil.virtual_memory().percent,
        "hostname": socket.gethostname(),
        "ports": [*TCP_PORTS, *(f"{p}/udp" for p in UDP_PORTS)],
    }


def _protocol_notes(disk_logs: dict[str, str]) -> dict:
    """从落盘日志里提炼「iPhone 走到哪一步」的证据，方便离线分析。"""
    text = disk_logs.get("receiver.log", "")
    notes = {
        "discover": 0,
        "ask": 0,
        "upload": 0,
        "last_discover": "",
        "last_ask": "",
        "handshake_errors": [],
        "hint": "",
    }
    for line in text.splitlines():
        if "POST /Discover" in line:
            notes["discover"] += 1
            notes["last_discover"] = line.strip()[:24]
        elif "POST /Ask" in line or "ask from " in line:
            notes["ask"] += 1
            notes["last_ask"] = line.strip()[:24]
        elif "POST /Upload" in line:
            notes["upload"] += 1
        elif "handshake" in line.lower() and ("fail" in line.lower() or "error" in line.lower()):
            notes["handshake_errors"].append(line.strip()[:200])
    radio = disk_logs.get("radio.log", "")
    for line in radio.splitlines()[-200:]:
        if "peer frames=" in line:
            notes["peers"] = line.split("peer frames=", 1)[1][:40]
    if notes["discover"] and not notes["ask"]:
        notes["hint"] = ("手机已经连上并取走了本机身份（Discover），但没有发起协商（Ask）。"
                         "这通常是手机端放弃投送，或它随后另开连接时连不上本机。")
    elif notes["ask"] and not notes["upload"]:
        notes["hint"] = "协商已到达但文件没有上传，可能是权限/空间/超时。"
    elif notes["upload"]:
        notes["hint"] = "已进入上传阶段。"
    return notes


def report_payload(settings, chain) -> dict:
    """组装诊断报告的内容（导出 JSON 与实测压缩包共用）。"""
    snapshot = chain.snapshot()
    run_dir = getattr(chain, "run_dir", None)
    disk_logs: dict[str, str] = {}
    if run_dir:
        for log in sorted(Path(run_dir).glob("*.log")):
            try:
                text = log.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            disk_logs[log.name] = "\n".join(text.splitlines()[-400:])
    return {
        "app": {"name": config.APP_NAME, "version": config.VERSION},
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "environment": environment(settings),
        "checks": run_checks(settings, snapshot.get("phase") == "ready"),
        "state": snapshot,
        "transfers": snapshot.get("transfers", []),
        "logs": {name: chain.logs(name, 600) for name in [*CHAIN, "beacon"]},
        "disk_logs": disk_logs,
        "notable": _protocol_notes(disk_logs),
        "settings": settings.as_dict(),
    }


def export_report(settings: config.Settings, chain, destination: Path) -> Path:
    data = report_payload(settings, chain)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination
