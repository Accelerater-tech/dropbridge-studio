"""GitHub token 的本地保管：用 Windows DPAPI 加密，只有当前 Windows 用户能解开。

存盘位置：%LOCALAPPDATA%\\DropBridgeStudio\\github.token
- 不是明文，别的账户/别的机器拷走也解不开
- 不放进仓库、不放进 data/、不写进任何日志

用法：
  python tools/gh_auth.py save <token>   # 存一次
  python tools/gh_auth.py show           # 只看掩码，确认存的是什么
  python tools/gh_auth.py token          # 打印明文（给脚本用，别平时跑）
  python tools/gh_auth.py forget         # 删掉

脚本里取用：from gh_auth import token; token() 会先看环境变量 GH_TOKEN，再落到加密文件。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

STORE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "DropBridgeStudio" / "github.token"
ENTROPY = b"dropbridge-studio-gh"


def _crypt() -> tuple:
    try:
        import win32crypt
    except ImportError as err:  # pragma: no cover
        raise SystemExit("需要 pywin32：pip install pywin32") from err
    return win32crypt


def save(raw: str) -> Path:
    token = raw.strip()
    if not token:
        raise SystemExit("token 是空的")
    win32crypt = _crypt()
    blob = win32crypt.CryptProtectData(token.encode("utf-8"), "dropbridge-studio", ENTROPY, None, None, 0)
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_bytes(blob)
    try:  # 只有当前用户可读写
        import win32security  # noqa: F401  (win32crypt 已经带 win32 依赖，这里只是确认可用)
    except ImportError:
        pass
    return STORE


def load() -> str | None:
    if not STORE.is_file():
        return None
    win32crypt = _crypt()
    try:
        data = win32crypt.CryptUnprotectData(STORE.read_bytes(), ENTROPY, None, None, 0)
    except Exception:  # noqa: BLE001 - 别的账户/别处拷来的文件，解不开就是解不开
        return None
    raw = data[1].decode("utf-8", errors="replace").strip()
    return raw or None


def masked(token: str) -> str:
    if len(token) < 12:
        return "***"
    return f"{token[:7]}…{token[-4:]}（{len(token)} 位）"


def token() -> str:
    """给脚本用：环境变量优先，其次加密存档。"""
    env = os.environ.get("GH_TOKEN", "").strip()
    if env:
        return env
    stored = load()
    if stored:
        os.environ["GH_TOKEN"] = stored
        return stored
    raise SystemExit("没有 GitHub token：先 python tools/gh_auth.py save <token>")


def main(argv: list[str]) -> int:
    action = argv[0] if argv else "show"
    if action == "save":
        path = save(argv[1] if len(argv) > 1 else sys.stdin.readline())
        print("saved to", path, "|", masked(load() or ""))
    elif action == "show":
        stored = load()
        print("stored:", masked(stored) if stored else "（还没有存）", "|", STORE)
    elif action == "token":
        print(token())
    elif action == "forget":
        if STORE.is_file():
            STORE.unlink()
            print("removed", STORE)
        else:
            print("nothing stored")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
