"""通过 CDP 读写正在运行的 Studio 页面：截图 / 执行 JS / 抓控制台错误。

用法:
    python tools/cdp.py shot data/x.png
    python tools/cdp.py eval "document.title"
    python tools/cdp.py errors
"""
from __future__ import annotations

import base64
import json
import sys
import urllib.request

import websocket

PORT = 9333


def target() -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=5) as response:
        pages = json.load(response)
    for page in pages:
        if page.get("type") == "page":
            return page
    raise SystemExit("no page target")


class Session:
    def __init__(self) -> None:
        info = target()
        self.ws = websocket.create_connection(info["webSocketDebuggerUrl"], timeout=15)
        self.seq = 0

    def call(self, method: str, **params):
        self.seq += 1
        self.ws.send(json.dumps({"id": self.seq, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == self.seq:
                return message.get("result", message)

    def eval(self, expression: str):
        result = self.call("Runtime.evaluate", expression=expression, returnByValue=True,
                           awaitPromise=True)
        if "exceptionDetails" in result:
            return {"error": result["exceptionDetails"].get("text")}
        return result.get("result", {}).get("value")

    def shot(self, path: str) -> None:
        data = self.call("Page.captureScreenshot", format="png")["data"]
        with open(path, "wb") as handle:
            handle.write(base64.b64decode(data))

    def close(self) -> None:
        self.ws.close()


def main() -> int:
    session = Session()
    try:
        command = sys.argv[1]
        if command == "shot":
            session.shot(sys.argv[2])
            print("saved", sys.argv[2])
        elif command == "eval":
            print(json.dumps(session.eval(sys.argv[2]), ensure_ascii=False, indent=2))
        elif command == "errors":
            print(json.dumps(session.eval(
                "(window.__errors||[]).slice(-20)"), ensure_ascii=False, indent=2))
        else:
            raise SystemExit(f"unknown command {command}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
