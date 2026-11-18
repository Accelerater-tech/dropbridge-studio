"""mDNS 旁听：坐在 receiver 和 awdl_netd 的 UDP 代理中间，顺手记下谁在找我们。

链路本来是 receiver --UDP--> 127.0.0.1:15353 (awdl_netd) <--> ff02::fb:5353。
我们改成 receiver -> 我们(15354) -> netd(15353)，双向原样转发，只在中间
解析 DNS 报文：

* 收到查询（QR=0）说明"附近有台苹果设备正在找接收端"，记下名字和类型；
* 一条查询都没有，说明对方根本没找到这条链路（设备设置、距离、蓝牙/Wi-Fi）。

这个模块只读旁听，不改包内容；转发失败会记错误但不会让链路挂掉。
"""
from __future__ import annotations

import socket
import struct
import threading
import time
from collections import deque

Q_TYPES = {
    1: "A",
    12: "PTR",
    16: "TXT",
    28: "AAAA",
    33: "SRV",
    47: "NSEC",
    255: "ANY",
}


def parse_questions(packet: bytes) -> tuple[list[str], list[int], bool]:
    """返回 (问题名列表, 问题类型列表, 是否响应包)。解析失败就返回空。"""
    if len(packet) < 12:
        return [], [], False
    flags = struct.unpack("!H", packet[2:4])[0]
    is_response = bool(flags & 0x8000)
    (qcount,) = struct.unpack("!H", packet[4:6])
    names: list[str] = []
    qtypes: list[int] = []
    offset = 12
    for _ in range(min(qcount, 32)):
        labels = []
        while offset < len(packet):
            length = packet[offset]
            if length == 0:
                offset += 1
                break
            if length & 0xC0:  # 压缩指针：问题段里不该出现，出现了就放弃
                return names, qtypes, is_response
            offset += 1
            if offset + length > len(packet):
                return names, qtypes, is_response
            labels.append(packet[offset:offset + length].decode("utf-8", "replace"))
            offset += length
        if offset + 4 > len(packet):
            break
        (qtype,) = struct.unpack("!H", packet[offset:offset + 2])
        offset += 4
        names.append(".".join(labels))
        qtypes.append(qtype)
    return names, qtypes, is_response


class MdnsObserver:
    """把 receiver 的 mDNS 收发改道，顺便统计附近设备问过什么。"""

    def __init__(self, listen_port: int = 15354, upstream_port: int = 15353) -> None:
        self.listen_port = listen_port
        self.upstream = ("127.0.0.1", upstream_port)
        self.sock: socket.socket | None = None
        self.thread: threading.Thread | None = None
        self.stopping = threading.Event()
        self.lock = threading.Lock()
        self.receiver_addr: tuple[str, int] | None = None
        self.total_queries = 0
        self.total_responses = 0
        self.recent: deque[dict] = deque(maxlen=24)
        self.names: dict[str, int] = {}
        self.error = ""
        self.started_at = 0.0
        self._minute_bucket = int(time.time() // 60)
        self._minute_counts: dict[int, int] = {}

    # ----- 生命周期 -------------------------------------------------------
    def start(self) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", self.listen_port))
            sock.settimeout(0.3)
        except OSError as error:
            self.error = f"mDNS 旁听没能监听 {self.listen_port}：{error}"
            return False
        self.sock = sock
        self.started_at = time.time()
        self.thread = threading.Thread(target=self._run, name="mdns-observer", daemon=True)
        self.thread.start()
        return True

    def stop(self) -> None:
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=1.5)
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    # ----- 转发与统计 -----------------------------------------------------
    def _run(self) -> None:
        while not self.stopping.is_set():
            sock = self.sock
            if sock is None:
                break
            try:
                packet, addr = sock.recvfrom(9000)
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                break
            try:
                self._handle(packet, addr)
            except Exception as error:  # noqa: BLE001 - 旁听坏掉也不能影响接收
                self.error = f"mDNS 旁听异常：{error}"

    def _handle(self, packet: bytes, addr: tuple[str, int]) -> None:
        names, qtypes, is_response = parse_questions(packet)
        from_upstream = addr[1] == self.upstream[1] and addr[0] == self.upstream[0]
        if from_upstream:
            with self.lock:
                target = self.receiver_addr
                if is_response:
                    self.total_responses += 1
            if target:
                self.sock.sendto(packet, target)
            return

        # 来自 receiver：先记住它的地址，再转给 netd
        with self.lock:
            self.receiver_addr = addr
        try:
            self.sock.sendto(packet, self.upstream)
        except OSError as error:
            self.error = f"mDNS 转发失败：{error}"

        now = time.time()
        label = Q_TYPES.get(qtypes[0], str(qtypes[0])) if qtypes else "?"
        with self.lock:
            if is_response:
                self.total_responses += 1
                return
            self.total_queries += 1
            bucket = int(now // 60)
            self._minute_counts[bucket] = self._minute_counts.get(bucket, 0) + 1
            for name in names:
                self.names[name] = self.names.get(name, 0) + 1
            self.recent.append({
                "t": now,
                "name": names[0] if names else "",
                "type": label,
                "port": addr[1],
            })

    # ----- 快照 -----------------------------------------------------------
    def snapshot(self) -> dict:
        now = time.time()
        with self.lock:
            this_minute = self._minute_counts.get(int(now // 60), 0)
            last_minute = self._minute_counts.get(int(now // 60) - 1, 0)
            recent = [dict(item, ago=round(now - item["t"], 1)) for item in list(self.recent)]
            names = sorted(self.names.items(), key=lambda kv: kv[1], reverse=True)[:8]
            return {
                "listening": self.sock is not None,
                "port": self.listen_port,
                "total_queries": self.total_queries,
                "total_responses": self.total_responses,
                "this_minute": this_minute,
                "last_minute": last_minute,
                "recent": recent[-8:],
                "names": [{"name": name, "count": count} for name, count in names],
                "error": self.error,
                "uptime": int(now - self.started_at) if self.started_at else 0,
            }
