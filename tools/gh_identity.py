"""用 GitHub API 读当前登录用户信息（token 只从环境变量读，不落盘）。

用法：GH_TOKEN=xxx python tools/gh_identity.py
"""
import json
import os
import sys
import urllib.request


def api(path: str, token: str, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request("https://api.github.com" + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "dropbridge-studio")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as err:
        body = err.read().decode(errors="replace")
        try:
            return err.code, json.loads(body)
        except ValueError:
            return err.code, {"raw": body[:400]}


def main() -> int:
    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        print("missing GH_TOKEN")
        return 2
    status, user = api("/user", token)
    print("status", status)
    if status != 200:
        print(json.dumps(user, ensure_ascii=False)[:400])
        return 1
    print(json.dumps({k: user.get(k) for k in ("login", "name", "id", "email", "html_url")}, ensure_ascii=False, indent=2))
    scopes = ""
    req = urllib.request.Request("https://api.github.com/user", method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("User-Agent", "dropbridge-studio")
    with urllib.request.urlopen(req, timeout=30) as resp:
        scopes = resp.headers.get("x-oauth-scopes", "")
    print("scopes:", scopes or "(fine-grained / none reported)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
