"""DropBridge Studio — backend chain supervisor.

Starts the five DropBridge backends in the exact order the original tray app
uses (radio -> bridge -> netd -> awdld -> receiver), waits for each one's
readiness line, tails their output, keeps a small telemetry model for the UI
and watches the received folder.

Everything here runs off the GUI thread; the UI polls ``snapshot()``.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import socket
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

import psutil

from . import config

CHAIN = ("radio", "bridge", "netd", "awdld", "receiver")
EVENTS_MAX = 240
ACCESS = re.compile(r'"POST /(Discover|Ask)')
READY = {
    "radio": "listening on 127.0.0.1:49876",
    "bridge": "waiting for awdld",
    "netd": "waiting for awdld",
    "awdld": "host interface",
    "receiver": "receiving as",
}
TIMEOUT = {"radio": 300, "bridge": 30, "netd": 30, "awdld": 90, "receiver": 60}
TCP_PORTS = (49876, 49877, 8771)
UDP_PORTS = (15353,)

KV = re.compile(r"(\w+)=(-?\d+(?:\.\d+)?)")
LEVEL = re.compile(r"\[(E|W|I|D|T)\]|(ERROR|WARN|INFO|DEBUG)\b")


def _port_in_use(port: int, udp: bool = False) -> bool:
    try:
        if udp:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        with sock:
            if not udp:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True


def busy_ports() -> list:
    held = [p for p in TCP_PORTS if _port_in_use(p)]
    held += [f"{p}/udp" for p in UDP_PORTS if _port_in_use(p, udp=True)]
    return held


def _listing(pid: int, port: int, udp: bool = False) -> bool:
    """这个进程是否已经在监听 port —— 只看 socket 表，绝不真去连。

    后端把「有人连上」当成协议握手开始：探测式 connect 会让 radio 写 HELLO
    失败后自杀、让 netd 认为 awdld 握手失败后退出 1。所以这里必须只读 socket 状态。
    """
    try:
        proc = psutil.Process(pid)
        for conn in proc.net_connections(kind="inet"):
            if not conn.laddr or conn.laddr.port != port:
                continue
            if udp and conn.type == socket.SOCK_DGRAM:
                return True
            if not udp and conn.status == psutil.CONN_LISTEN:
                return True
    except (psutil.Error, OSError):
        return False
    return False


def _udp_bound(pid: int, port: int) -> bool:
    try:
        for conn in psutil.net_connections(kind="udp"):
            if conn.pid == pid and conn.laddr and conn.laddr.port == port:
                return True
    except (psutil.Error, OSError):
        pass
    return False


# 后端的日志是块缓冲的（管道里会滞后很久），所以就绪判断优先看端口 / 地址文件，
# 日志行只作为加速信号。
# 端口归属（对过 psutil）：radio 49876、netd 49877、receiver 8771；bridge 建命名管道
TCP_READY = {"radio": 49876, "netd": 49877, "receiver": 8771}
UDP_READY = {"netd": 15353}
PIPE_READY = {"bridge": r"\\.\pipe\winawdl-radio"}


class _Event:
    """Named manual-reset event the radio watches (Local\\DropBridgeRadioStop)."""

    def __init__(self, name: str = r"Local\DropBridgeRadioStop") -> None:
        self.name = name
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateEventW.restype = wt.HANDLE
        kernel32.CreateEventW.argtypes = [wt.LPVOID, wt.BOOL, wt.BOOL, wt.LPCWSTR]
        self._handle = kernel32.CreateEventW(None, True, False, name)
        self._kernel32 = kernel32

    def reset(self) -> None:
        self._kernel32.ResetEvent(self._handle)

    def set(self) -> None:
        self._kernel32.SetEvent(self._handle)

    def close(self) -> None:
        try:
            self._kernel32.CloseHandle(self._handle)
        except Exception:
            pass


class Child:
    def __init__(self, name: str, exe: str, args: list, env: dict, cwd: str,
                 log_path: Path | None = None) -> None:
        self.name = name
        self.exe = exe
        self.args = args
        self.env = env
        self.cwd = cwd
        self.log_path = log_path
        self.proc: subprocess.Popen | None = None
        self.ready = False
        self.exit_code = None
        self.started_at = 0.0
        self.lines = deque(maxlen=1200)
        self.running = False
        self.on_line = None

    def start(self) -> None:
        flags = 0x08000000  # CREATE_NO_WINDOW
        env = dict(os.environ)
        env.update({k: v for k, v in self.env.items() if v is not None})
        env["PYTHONUNBUFFERED"] = "1"
        self.proc = subprocess.Popen(
            [self.exe, *self.args],
            cwd=self.cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            creationflags=flags,
        )
        self.started_at = time.time()
        self.running = True
        self.ready = False
        self.exit_code = None
        threading.Thread(target=self._pump, name=f"pump-{self.name}", daemon=True).start()

    def _pump(self) -> None:
        proc = self.proc
        if not proc or not proc.stdout:
            return
        handle = None
        if self.log_path:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                handle = open(self.log_path, "a", encoding="utf-8", errors="replace")
            except OSError:
                handle = None
        while True:
            try:
                chunk = proc.stdout.readline()
            except (OSError, ValueError):
                break
            if not chunk:
                break
            text = chunk.decode("utf-8", "replace").rstrip("\r\n")
            if text:
                self.lines.append((time.time(), text))
                if self.on_line:
                    try:
                        self.on_line(text)
                    except Exception:  # noqa: BLE001 - 解析出错不能弄死读取线程
                        pass
                if handle:
                    try:
                        handle.write(f"{time.strftime('%H:%M:%S')} {text}\n")
                        handle.flush()
                    except OSError:
                        pass
        if handle:
            try:
                handle.close()
            except OSError:
                pass
        self.running = False
        try:
            self.exit_code = proc.wait(timeout=3)
        except Exception:
            self.exit_code = -1

    def stop(self, timeout: float = 5.0) -> None:
        proc = self.proc
        if not proc or proc.poll() is not None:
            self.running = False
            return
        try:
            proc.terminate()
            proc.wait(timeout=timeout)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        self.running = False

    @property
    def alive(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)


class Transfer:
    __slots__ = ("name", "path", "size", "mtime", "speed", "status", "prev", "seen", "kind")

    def __init__(self, path: Path) -> None:
        stat = path.stat()
        self.name = path.name
        self.path = str(path)
        self.size = stat.st_size
        self.mtime = stat.st_mtime
        self.speed = 0.0
        self.status = "receiving"
        self.prev = (stat.st_size, time.time())
        self.seen = time.time()
        self.kind = "image" if path.suffix.lower() in (
            ".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".webp") else "file"

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "size": self.size,
            "mtime": self.mtime,
            "speed": round(self.speed, 1),
            "status": self.status,
            "kind": self.kind,
        }


class Chain:
    def __init__(self, settings: config.Settings) -> None:
        self.settings = settings
        self.lock = threading.RLock()
        self.children: dict[str, Child] = {}
        self.phase = "idle"
        self.message = "未启动"
        self.started_at = 0.0
        self.stop_requested = False
        self.stats = {
            "radio": {"cb": 0, "crc": 0, "tx": 0, "failed": 0, "fps": 0.0, "peers": 0, "channel": 0},
            "netd": {"tx_frames": 0, "tx_bytes": 0, "tx_fail": 0, "peers": 0},
            "awdld": {"address": "", "master": "", "peers": 0},
            "receiver": {"discovers": 0, "asks": 0, "last_event": "", "last_event_at": 0.0},
        }
        self.radio_address = ""
        self.sync_master = ""
        self.events: list[dict] = []
        self._evlock = threading.Lock()
        self.events_path = config.studio_dir(settings.root) / "timeline.jsonl"
        self._load_events()
        self.series = deque(maxlen=90)
        self.transfers: dict[str, Transfer] = {}
        self._stop_event: _Event | None = None
        self._thread: threading.Thread | None = None
        self._watch: threading.Thread | None = None
        self._watch_stop = threading.Event()
        self.restarts = 0
        self.last_error = ""
        self.failed_logs: list = []
        self.run_dir: Path | None = None

    # ------------------------------------------------------------------ state
    def snapshot(self) -> dict:
        with self.lock:
            now = time.time()
            children = []
            for name in CHAIN:
                child = self.children.get(name)
                children.append({
                    "name": name,
                    "running": bool(child and child.alive),
                    "ready": bool(child and child.ready),
                    "exit_code": child.exit_code if child else None,
                    "pid": child.proc.pid if child and child.proc else None,
                })
            transfers = sorted(
                (t.as_dict() for t in self.transfers.values()),
                key=lambda item: item["mtime"], reverse=True)[:200]
            return {
                "phase": self.phase,
                "message": self.message,
                "running": self.phase in ("starting", "ready"),
                "uptime": int(now - self.started_at) if self.started_at else 0,
                "children": children,
                "beacon": self._beacon_state(),
                "stats": dict(self.stats),
                "series": list(self.series),
                "transfers": transfers,
                "restarts": self.restarts,
                "last_error": self.last_error,
                "ports": busy_ports(),
                "address": self.radio_address,
                "master": self.sync_master,
                "events": list(self.events),
                "now": now,
            }

    def _load_events(self) -> None:
        """把上一次运行时留下的事件读回来，重启后仍能看到「手机来过」。"""
        try:
            lines = self.events_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        items = []
        for line in lines[-EVENTS_MAX:]:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            item["historic"] = True
            items.append(item)
        if not items:
            return
        self.events = items
        last = next((e for e in reversed(items) if e.get("kind") in ("peer", "file")), None)
        if last:
            self.stats["receiver"]["last_event"] = last.get("text", "")
            self.stats["receiver"]["last_event_at"] = last.get("at", 0.0)

    def _event(self, kind: str, text: str) -> None:
        """记一条时间线事件（供界面回放「手机来过/走了」这类瞬间）。"""
        item = {
            "at": time.time(),
            "t": time.strftime("%H:%M:%S"),
            "kind": kind,
            "text": text,
        }
        with self._evlock:
            self.events.append(item)
            if len(self.events) > EVENTS_MAX:
                del self.events[:-EVENTS_MAX]
            try:
                self.events_path.parent.mkdir(parents=True, exist_ok=True)
                with self.events_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            except OSError:
                pass

    def _beacon_state(self) -> dict:
        child = self.children.get("beacon")
        if not child:
            return {"running": False, "state": "off", "text": "未启动"}
        lines = [text for _, text in list(child.lines)[-80:]]
        errors = [text for text in lines if "拒绝访问" in text or "denied" in text.lower()
                  or "error" in text.lower() or "失败" in text]
        advertised = [text for text in lines if "advertis" in text.lower() or "广播" in text]
        if errors:
            return {"running": child.alive, "state": "error",
                    "text": errors[-1][:160], "lines": lines[-6:]}
        if advertised:
            return {"running": child.alive, "state": "ok",
                    "text": advertised[-1][:160], "lines": lines[-6:]}
        return {"running": child.alive, "state": "wait",
                "text": "等待首次广播…" if child.alive else "已退出",
                "lines": lines[-6:]}

    def logs(self, name: str, limit: int = 400) -> list:
        if name == "all":
            merged = []
            for child in self.children.values():
                merged.extend((ts, child.name, text) for ts, text in child.lines)
            if not merged:
                merged = list(self.failed_logs)
            merged.sort(key=lambda item: item[0])
            rows = merged[-limit:]
        else:
            child = self.children.get(name)
            if child:
                rows = [(ts, name, text) for ts, text in child.lines][-limit:]
            else:
                rows = [row for row in self.failed_logs if row[1] == name][-limit:]
        return [{"t": ts, "src": src, "text": text} for ts, src, text in rows]

    # ------------------------------------------------------------------ start
    def _make_children(self) -> dict[str, Child]:
        s = self.settings
        backend = s.backend
        root = s.root
        run_dir = s.logs / time.strftime("%Y%m%d-%H%M%S")
        self.run_dir = run_dir
        addr = str(s.data / "awdl_netd.addr")
        radio_env = {
            "AIRBRIDGE_LOG_LEVEL": "info" if s.get("radio_verbose") else "warn",
            "AIRBRIDGE_LINK_STATS": "1",
            "AIRBRIDGE_FASTRETUNE_FW": "2",
            "AIRBRIDGE_PARENT_PID": str(os.getpid()),
        }
        awdl_env = {
            "AWDL_ELECTION_METRIC": "200",
            "AWDL_ELECTION_COUNTER": "100000",
            "AWDL_CHANSEQ": "social" if s.get("chanseq") == "social" else None,
            "AWDL_FOLLOW_MASTER_SEQ": None,
        }
        receiver_args = [
            "-u", str(backend / "airdrop" / "receiver.py"),
            "--name", str(s.get("device_name")),
            "--model", str(s.get("model")),
            "--listen", "127.0.0.1",
            "--mdns-address-file", addr,
            "--outdir", str(s.outdir),
            "--keys", str(s.keys),
            "--flags", str(s.get("flags")),
            "--max-receive-percent", str(s.get("max_receive_percent")),
        ]
        if s.get("trace", True):
            # DEBUG 级握手日志：手机连上却没继续时会留下线索
            receiver_args.append("--trace")
        return {
            "radio": Child("radio", str(backend / "airbridge_radio.exe"),
                           [str(s.get("channel")), str(s.get("width"))], radio_env, root,
                           run_dir / "radio.log"),
            "bridge": Child("bridge", str(backend / "radio_pipe_bridge.exe"), [], {}, root,
                            run_dir / "bridge.log"),
            "netd": Child("netd", str(backend / "awdl_netd.exe"), [], {
                "AWDL_NETD_MDNS_PROXY": "1",
                "AWDL_NETD_ADDR_FILE": addr,
            }, root, run_dir / "netd.log"),
            "awdld": Child("awdld", str(backend / "awdld.exe"),
                           ["-c", str(s.get("channel")),
                            "-s", "1",
                            "-j", "400" if s.get("tcp_merge") else "0",
                            "-v"], awdl_env, root, run_dir / "awdld.log"),
            "receiver": Child("receiver", self.settings.python, receiver_args, {}, root,
                              run_dir / "receiver.log"),
        }

    def _wire(self, children: dict) -> dict:
        """把每个子进程的每行输出接到统计解析上（之前根本没接，导致速率/发现数一直是 0）。"""
        for name, child in children.items():
            child.on_line = lambda text, name=name: self._ingest(name, text)
        return children

    def missing(self) -> list:
        s = self.settings
        need = [s.backend / "airbridge_radio.exe", s.backend / "radio_pipe_bridge.exe",
                s.backend / "awdl_netd.exe", s.backend / "awdld.exe",
                s.backend / "airdrop" / "receiver.py"]
        return [str(p) for p in need if not p.is_file()]

    def start(self, background: bool = True) -> bool:
        with self.lock:
            if self.phase == "starting":
                return False
            self.stop_requested = False
            self.phase = "starting"
            self._event("chain", "开始启动链路")
            self.message = "正在启动链路"
        if background:
            self._thread = threading.Thread(target=self._start_chain, name="chain-start", daemon=True)
            self._thread.start()
            return True
        return self._start_chain()

    def _start_chain(self) -> bool:
        s = self.settings
        try:
            missing = self.missing()
            if missing:
                self._fail("缺少后端文件: " + ", ".join(Path(p).name for p in missing))
                return False
            # 总是先清残留：孤儿 radio 会一直占着 USB 设备，导致新 radio 起来就退
            killed = self.reclaim()
            held = busy_ports()
            if held:
                self._fail("端口被占用: " + ", ".join(map(str, held)) +
                           (f"（已回收 {killed} 个残留进程）" if killed else ""))
                return False
            for path in (s.outdir, s.keys, s.logs):
                path.mkdir(parents=True, exist_ok=True)
            addr = s.data / "awdl_netd.addr"
            if addr.exists():
                try:
                    addr.unlink()
                except OSError:
                    pass
            self._stop_event = _Event()
            self._stop_event.reset()
            self._children_make = self._wire(self._make_children())
            self.children = self._children_make
            self.started_at = time.time()
            self.restarts = 0

            for name in CHAIN:
                if self.stop_requested:
                    self.message = "已取消"
                    self._fail("启动已取消", keep_children=False)
                    return False
                child = self.children[name]
                # awdld 起来得最快，偶发抢跑（netd 还没监听）就重试几次
                tries = 3 if name == "awdld" else 1
                ready = False
                for attempt in range(tries):
                    try:
                        child.start()
                    except OSError as error:
                        self._fail(f"{name} 启动失败: {error}")
                        return False
                    self.message = f"等待 {name} 就绪"
                    if self._wait_ready(child, TIMEOUT[name], soft=True):
                        ready = True
                        break
                    if self.stop_requested:
                        self._fail("启动已取消")
                        return False
                    if attempt + 1 < tries:
                        self._ingest("supervisor",
                                     f"{name} 第 {attempt + 1} 次没起来"
                                     f"（退出码 {child.exit_code}），重试")
                        if name == "awdld":
                            # awdld 一挂，bridge 的管道就可能被“消费”掉：
                            # 后面的 awdld 会看到 FILE_NOT_FOUND，只能连 pipe 前端一起重启
                            self._reboot_front()
                        time.sleep(1.0)
                if not ready:
                    self._fail(self.last_error or f"{name} 未就绪")
                    return False

            self.phase = "ready"
            self.message = "接收就绪"
            self._event("chain", "链路就绪，等待手机连接")
            self.last_error = ""
            if s.get("beacon"):
                self.start_beacon()
            self._watch_stop.clear()
            if not (self._watch and self._watch.is_alive()):
                self._watch = threading.Thread(target=self._watchdog, name="watchdog", daemon=True)
                self._watch.start()
            return True
        except Exception as error:  # keep the UI alive whatever happens
            self._fail(f"内部错误: {error}")
            return False

    def _reboot_front(self) -> None:
        """awdld 连不上管道时，把 bridge + netd 一起重启（管道实例是一次性的）。"""
        for name in ("netd", "bridge"):
            child = self.children.get(name)
            if child:
                child.stop(4.0)
                child.ready = False
        time.sleep(0.8)
        for name in ("bridge", "netd"):
            child = self.children.get(name)
            if not child or self.stop_requested:
                continue
            try:
                child.start()
            except OSError:
                continue
            self._wait_ready(child, TIMEOUT[name], soft=True)

    def _wait_ready(self, child: Child, timeout: float, soft: bool = False) -> bool:
        """就绪 = 端口/管道/地址文件就位；日志行只是锦上添花（后端是块缓冲的）。

        soft=True 时把失败原因写进 last_error 但不结束链路，交给调用方决定要不要重试。
        """
        deadline = time.time() + timeout
        addr = self.settings.data / "awdl_netd.addr"
        port = TCP_READY.get(child.name)
        udp = UDP_READY.get(child.name)
        pipe = PIPE_READY.get(child.name)

        def give_up(reason: str) -> bool:
            self.last_error = reason
            if soft:
                return False
            self._fail(reason)
            return False

        while time.time() < deadline:
            if self.stop_requested:
                return give_up("启动已取消")
            if child.exit_code is not None:
                return give_up(f"{child.name} 提前退出（代码 {child.exit_code}）")
            # 只看 socket 表：探测连接会被后端当成握手开始，反而把链路搞崩。
            # netd 启动时只 listen TCP 49877（UDP 15353 是 awdld 握手后才有的），
            # 所以别等 UDP，等它反而永远等不到。
            if port and child.proc and _listing(child.proc.pid, port):
                child.ready = True
                return True
            if pipe and os.path.exists(pipe):
                child.ready = True
                return True
            if udp and child.proc and _listing(child.proc.pid, udp, udp=True):
                child.ready = True
                return True
            if child.name == "awdld" and addr.is_file():
                try:
                    if addr.read_text(encoding="utf-8", errors="replace").strip():
                        child.ready = True
                        return True
                except OSError:
                    pass
            for _, text in list(child.lines):
                if READY[child.name] in text:
                    child.ready = True
                    return True
            time.sleep(0.15)
        extra = ""
        if child.name == "awdld" and not addr.is_file():
            extra = "（netd 未写出 awdl_netd.addr）"
        return give_up(f"{child.name} 在 {int(timeout)} 秒内未就绪{extra}")

    def _fail(self, message: str, keep_children: bool = False) -> None:
        self._event("error", message)
        self.last_error = message
        self.phase = "error"
        self.message = message
        # 进程马上要被收掉，先把尾部输出留一份给界面和日志页看
        saved = []
        for child in self.children.values():
            tail = list(child.lines)[-80:]
            saved.extend((ts, child.name, text) for ts, text in tail)
            if child.exit_code is not None:
                saved.append((time.time(), child.name, f"[退出码 {child.exit_code}]"))
        self.failed_logs = saved
        self._ingest("supervisor", f"ERROR {message}")
        if not keep_children:
            self._stop_children()

    # ------------------------------------------------------------------- stop
    def stop(self) -> None:
        with self.lock:
            self.stop_requested = True
        self._watch_stop.set()
        self.stop_beacon()
        self._stop_children()
        with self.lock:
            self.phase = "idle"
            self.message = "已停止"
        self._event("chain", "链路已停止")

    def _stop_children(self) -> None:
        children = dict(self.children)
        for name in reversed(CHAIN):
            child = children.get(name)
            if not child:
                continue
            if name == "radio" and self._stop_event:
                try:
                    self._stop_event.set()
                    deadline = time.time() + 15
                    while child.alive and time.time() < deadline:
                        time.sleep(0.2)
                except Exception:
                    pass
            child.stop(5.0)
        for child in children.values():
            if child.proc and child.proc.stdout:
                try:
                    child.proc.stdout.close()
                except Exception:
                    pass
        self.children = {}
        if self._stop_event:
            self._stop_event.close()
            self._stop_event = None

    def reclaim(self) -> int:
        """Kill leftovers that belong to this install (never other programs)."""
        root = str(Path(self.settings.root).resolve()).lower().rstrip("\\") + "\\"
        exe_names = {"airbridge_radio.exe", "radio_pipe_bridge.exe", "awdl_netd.exe",
                     "awdld.exe"}
        supervisor_names = {"dropbridge.exe"}
        targets: list[psutil.Process] = []
        supervisors: list[psutil.Process] = []
        for proc in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
            try:
                info = proc.info
                name = (info.get("name") or "").lower()
                exe = (info.get("exe") or "").lower()
                cmd = " ".join(info.get("cmdline") or []).lower()
                if proc.pid == os.getpid():
                    continue
                if name in supervisor_names and exe.startswith(root):
                    supervisors.append(proc)
                elif name in exe_names and exe.startswith(root):
                    targets.append(proc)
                elif name in ("python.exe", "pythonw.exe") and "receiver.py" in cmd and root in cmd:
                    targets.append(proc)
                elif name == "powershell.exe" and "beacon.ps1" in cmd and root in cmd:
                    targets.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
        killed = 0
        # 先掐掉 supervisor，否则它会把刚杀掉的子进程又拉起来
        for proc in supervisors + targets:
            try:
                proc.kill()
                killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
        if killed:
            time.sleep(1.2)
        return killed

    # --------------------------------------------------------------- watchdog
    def _watchdog(self) -> None:
        last_scan = 0.0
        while not self._watch_stop.wait(1.0):
            with self.lock:
                phase = self.phase
                children = dict(self.children)
            if phase != "ready":
                continue
            dead = [name for name, child in children.items() if child.exit_code is not None]
            if dead:
                self.last_error = "后端退出: " + ", ".join(dead)
                self.message = self.last_error
                self.phase = "error"
                self._ingest("supervisor", f"ERROR {self.last_error}")
                self.stop_beacon()
                self._stop_children()
                if self.settings.get("auto_restart"):
                    time.sleep(2.0)
                    self.restarts += 1
                    self.start()
                continue
            self._sample()
            if time.time() - last_scan > 1.5:
                last_scan = time.time()
                self._scan_received()

    def _sample(self) -> None:
        with self.lock:
            fps = float(self.stats["radio"].get("fps") or 0.0)
            self.series.append({"t": time.time(), "fps": fps})

    # ------------------------------------------------------------ log parsing
    def _ingest(self, src: str, text: str) -> None:
        stats = self.stats
        if src in ("radio", "netd", "awdld"):
            for key, value in KV.findall(text):
                try:
                    number = float(value)
                except ValueError:
                    continue
                if key == "frames":
                    stats["radio"]["peers"] = int(number)
                if key in stats[src]:
                    stats[src][key] = int(number) if number == int(number) else number
            if " fps=" in text:
                try:
                    stats["radio"]["fps"] = float(text.split(" fps=")[1].split()[0])
                except (IndexError, ValueError):
                    pass
            if "peer frames=" in text:
                try:
                    frames = int(text.split("peer frames=")[1].split()[0])
                    stats["radio"]["peers"] = frames
                except (IndexError, ValueError):
                    pass
            if "AWDL address " in text:
                addr = text.split("AWDL address ", 1)[1].split()[0].strip(",")
                if len(addr) == 17:
                    self.radio_address = addr
                    stats["awdld"]["address"] = addr
            if "sync master is now " in text:
                addr = text.split("sync master is now ", 1)[1].split()[0].strip(",")
                if len(addr) == 17:
                    self.sync_master = addr
                    stats["awdld"]["master"] = addr
        elif src == "receiver":
            # 只认访问日志那一行（形如 127.0.0.1 "POST /Discover HTTP/1.1" 200 -），
            # 否则 DEBUG 头行 + 状态行会把一次请求记成两次。
            hit = ACCESS.findall(text)
            for method in hit:
                if method == "Discover":
                    stats["receiver"]["discovers"] += 1
                    self._note_receiver("发现请求 (Discover)")
                else:
                    stats["receiver"]["asks"] += 1
                    self._note_receiver("发送请求 (Ask)")
            if "upload " in text and "bytes received" in text:
                self._note_receiver("传输中")
            elif "connection from" in text:
                # 手机先建 TLS 连接再发 Discover；只连不发也能看出来
                peer = text.split("connection from ", 1)[1].strip()[:24]
                self._note_receiver(f"手机连上来了 {peer}")

    def _note_receiver(self, what: str, kind: str = "peer") -> None:
        self.stats["receiver"]["last_event"] = what
        self.stats["receiver"]["last_event_at"] = time.time()
        self._event(kind, what)

    # ----------------------------------------------------------- received dir
    def _scan_received(self) -> None:
        outdir = self.settings.outdir
        try:
            entries = list(outdir.iterdir())
        except OSError:
            return
        now = time.time()
        with self.lock:
            for path in entries:
                try:
                    if not path.is_file():
                        continue
                    stat = path.stat()
                except OSError:
                    continue
                key = str(path)
                item = self.transfers.get(key)
                if item is None:
                    if stat.st_mtime < now - 86400 * 7:
                        continue
                    fresh = Transfer(path)
                    # 启动时的第一轮扫描只是把历史文件读进来，不算「刚收到」
                    if not self.started_at or stat.st_mtime < self.started_at:
                        fresh.status = "done"
                    self.transfers[key] = fresh
                    continue
                delta = stat.st_size - item.size
                if delta > 0:
                    elapsed = max(now - item.prev[1], 0.001)
                    item.speed = delta / elapsed
                    item.prev = (stat.st_size, now)
                    item.size = stat.st_size
                    item.mtime = stat.st_mtime
                    item.status = "receiving"
                elif item.status == "receiving" and now - item.mtime > 3:
                    item.status = "done"
                    item.speed = 0.0
                    self._note_receiver(f"已保存 {path.name}", kind="file")
            # drop vanished entries
            for key in list(self.transfers):
                if not Path(key).exists():
                    del self.transfers[key]

    def clear_transfers(self) -> None:
        with self.lock:
            self.transfers.clear()

    # ----------------------------------------------------------------- beacon
    def start_beacon(self) -> None:
        script = self.settings.backend / "beacon.ps1"
        if not script.is_file():
            return
        temp = config.studio_dir(self.settings.root) / "temp"
        temp.mkdir(parents=True, exist_ok=True)
        env = {"TEMP": str(temp), "TMP": str(temp)}
        child = Child("beacon", "powershell.exe",
                      ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                      env, self.settings.root,
                      log_path=(self.run_dir / "beacon.log") if self.run_dir else None)
        try:
            child.start()
        except OSError:
            return
        self.children["beacon"] = child

    def stop_beacon(self) -> None:
        child = self.children.pop("beacon", None)
        if child:
            child.stop(2.0)
