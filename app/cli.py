"""Headless entry points — the same engine the GUI drives, readable in a terminal.

    python -m app.cli doctor                 # 体检（驱动 / 网卡 / 端口 / 目录 / 后端）
    python -m app.cli run --seconds 90       # 起链路，实时打印状态，到点收尾
    python -m app.cli hold                   # 起链路并保持（Ctrl+C 收尾）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import config, diag
from .supervisor import Chain

# Windows 控制台默认 GBK，中文/符号写不进去会直接抛 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

_MARK = {"ok": "OK", "wait": "..", "no": "XX"}
_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
RESET = "\x1b[0m" if _COLOR else ""
DIM = "\x1b[2m" if _COLOR else ""
GREEN = "\x1b[32m" if _COLOR else ""
RED = "\x1b[31m" if _COLOR else ""
YELLOW = "\x1b[33m" if _COLOR else ""
CYAN = "\x1b[36m" if _COLOR else ""

FIX_TEXT = {
    "choose_root": "在设置里选择 DropBridge 安装目录",
    "check_plug": "重新插拔 USB 网卡",
    "install_driver": "运行「安装 / 修复驱动」（需管理员）",
    "reclaim": "结束上一轮残留进程后重试",
    "open_outdir": "换个可写的接收目录",
    "open_keys": "首次启动会自动生成密钥",
}


def _paint(text: str, color: str) -> str:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return text
    return f"{color}{text}{RESET}"


def cmd_doctor(args: argparse.Namespace) -> int:
    settings = config.Settings()
    if args.root:
        settings.update({"root": args.root})
    print(f"安装目录  {settings.root}")
    print(f"接收目录  {settings.outdir}")
    checks = diag.run_checks(settings, False)
    width = max(len(c["title"]) for c in checks) + 2
    bad = 0
    for check in checks:
        mark = _paint("PASS", GREEN) if check["ok"] else _paint("FAIL", RED)
        if not check["ok"]:
            bad += 1
        print(f"[{mark}] {check['title'].ljust(width)} {check['detail']}")
        if not check["ok"] and check.get("fix"):
            print(f"        {DIM}→ {FIX_TEXT.get(check['fix'], check['fix'])}{RESET}")
    env = diag.environment(settings)
    print()
    for key, value in env.items():
        print(f"{DIM}{key.ljust(12)}{RESET} {value}")
    print()
    print(_paint(f"{len(checks) - bad}/{len(checks)} 项通过", GREEN if not bad else YELLOW))
    return 0 if not bad else 1


def _render(snap: dict, previous: dict) -> None:
    phase = snap["phase"]
    color = GREEN if phase == "ready" else (YELLOW if phase == "starting" else RED)
    stats = snap["stats"]
    radio, netd, awdld, receiver = (stats["radio"], stats["netd"],
                                    stats["awdld"], stats["receiver"])
    nodes = " ".join(
        f"{n['name']}{_MARK['ok'] if n['ready'] else (_MARK['wait'] if n['running'] else _MARK['no'])}"
        for n in snap["children"])
    line = (f"{_paint(phase.upper(), color).ljust(12)} {snap['uptime']:>4}s  {nodes}  "
            f"tx={radio['tx']} peers={radio['peers']} fps={radio['fps']:.1f} "
            f"disc={receiver['discovers']} ask={receiver['asks']}")
    transfers = len(snap["transfers"])
    sys.stdout.write("\r" + line + f" files={transfers}" + " " * 8)
    sys.stdout.flush()
    if snap["phase"] != previous.get("phase") and snap["message"]:
        sys.stdout.write("\n" + DIM + "  " + snap["message"] + RESET + "\n")
    if snap.get("last_error") and snap["last_error"] != previous.get("last_error"):
        sys.stdout.write("\n" + _paint("  " + snap["last_error"], RED) + "\n")
    previous["phase"] = snap["phase"]
    previous["last_error"] = snap.get("last_error", "")


def _run(seconds: float | None, verbose: bool) -> int:
    settings = config.Settings()
    chain = Chain(settings)
    killed = chain.reclaim()
    if killed:
        print(_paint(f"清理残留进程 {killed} 个", DIM))
    missing = chain.missing()
    if missing:
        print(_paint("缺少后端文件: " + ", ".join(missing), RED))
        return 2
    if not chain.start():
        print(_paint(f"启动失败: {chain.message}", RED))
        return 3
    previous: dict = {}
    deadline = time.time() + seconds if seconds else None
    ready_at = 0.0
    try:
        while True:
            snap = chain.snapshot()
            _render(snap, previous)
            if snap["phase"] == "ready" and not ready_at:
                ready_at = time.time()
            if snap["phase"] in ("error", "failed"):
                sys.stdout.write("\n")
                print(_paint("链路失败: " + snap["message"], RED))
                if not verbose:
                    for row in chain.logs("all", 25):
                        print(f"{DIM}{row['src']:>9}{RESET} {row['text']}")
                return 4
            if deadline and time.time() >= deadline:
                break
            time.sleep(1.0)
    except KeyboardInterrupt:
        print()
    finally:
        chain.stop()
    sys.stdout.write("\n")
    if ready_at:
        print(_paint("链路在线过，已正常收尾。", GREEN))
        return 0
    print(_paint("链路未就绪。", YELLOW))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    return _run(args.seconds, args.verbose)


def cmd_json(args: argparse.Namespace) -> int:
    settings = config.Settings()
    payload = {
        "settings": settings.as_dict(),
        "checks": diag.run_checks(settings, False),
        "env": diag.environment(settings),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dropbridge-studio", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_doctor = sub.add_parser("doctor", help="体检本机环境")
    p_doctor.add_argument("--root", default="", help="指定 DropBridge 安装目录")
    p_doctor.set_defaults(func=cmd_doctor)

    p_run = sub.add_parser("run", help="启动接收链路并观察")
    p_run.add_argument("--seconds", type=float, default=90.0, help="观察时长（0 = 一直跑）")
    p_run.add_argument("--verbose", action="store_true", help="失败时不打印日志尾部")
    p_run.set_defaults(func=cmd_run)

    p_hold = sub.add_parser("hold", help="启动链路并一直保持")
    p_hold.add_argument("--verbose", action="store_true", help="失败时不打印日志尾部")
    p_hold.set_defaults(func=lambda a: _run(None, a.verbose))

    p_json = sub.add_parser("json", help="输出体检结果 JSON")
    p_json.set_defaults(func=cmd_json)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
