"""按 iPhone 的原始请求头打一次 Discover，把原始响应字节扒出来看封包是否合法。"""
import plistlib
import socket
import ssl
import sys
import uuid

HOST, PORT = "127.0.0.1", 8771


def body_plist() -> bytes:
    payload = {
        "SenderComputerName": "iPhone",
        "SenderModelName": "iPhone15,2",
        "SenderRecordData": b"",
        "MediaCapabilities": b'{"Version": 1}',
    }
    return plistlib.dumps(payload, fmt=plistlib.FMT_BINARY)


def probe(label: str, headers: str, body: bytes) -> None:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
    except ssl.SSLError:
        pass
    raw = socket.create_connection((HOST, PORT), timeout=8)
    tls = ctx.wrap_socket(raw, server_hostname="DropBridge")
    request = f"POST /Discover HTTP/1.1\r\n{headers}".encode() + body
    tls.sendall(request)
    chunks = []
    tls.settimeout(6)
    try:
        while True:
            piece = tls.recv(65536)
            if not piece:
                break
            chunks.append(piece)
    except socket.timeout:
        chunks.append(b"<TIMEOUT>")
    data = b"".join(chunks)
    head, _, rest = data.partition(b"\r\n\r\n")
    print(f"--- {label}: total {len(data)} B, body {len(rest)} B")
    print(head.decode("latin-1"))
    if rest.startswith(b"<TIMEOUT>"):
        print("!! 服务端没有主动关闭连接，也没写完 body")
    try:
        plist = plistlib.loads(rest)
        print("plist keys:", sorted(plist))
        caps = plist.get("ReceiverMediaCapabilities")
        print("caps type:", type(caps).__name__, "value:", caps[:60] if isinstance(caps, bytes) else caps)
    except Exception as error:  # noqa: BLE001
        print("plist 解析失败:", error)
        print("body head:", rest[:120])
    tls.close()


iphone_headers = (
    "User-Agent: AirDrop/1.0\r\n"
    "Connection: close\r\n"
    "Transfer-Encoding: chunked\r\n\r\n"
)
payload = body_plist()
chunked = b"%x\r\n" % len(payload) + payload + b"\r\n0\r\n\r\n"
probe("iPhone 原始形态", iphone_headers, chunked)

sane = (
    "User-Agent: AirDrop/1.0\r\n"
    f"Content-Length: {len(payload)}\r\n"
    "Content-Type: application/x-apple-binary-plist\r\n"
    "Connection: close\r\n\r\n"
)
probe("Content-Length 形态", sane, payload)
