"""Minimal JSON-over-HTTP client for wrappers, with an egress allowlist.

Proxies are bypassed and only allow-listed hosts may be contacted, so code
under review never leaves the machine unless an operator configures it.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from orchestrator.contracts import AdapterError

DEFAULT_ALLOWED = ("localhost", "127.0.0.1", "::1", "llm-runtime", "fake-runtime", "host.docker.internal")


def allowed_hosts() -> set[str]:
    extra = os.environ.get("ACR_ALLOWED_HOSTS", "")
    return set(DEFAULT_ALLOWED) | {h.strip() for h in extra.split(",") if h.strip()}


def check_egress(url: str) -> None:
    host = urlparse(url).hostname or ""
    if host not in allowed_hosts():
        raise AdapterError(f"egress to '{host}' is not allowed; add it to ACR_ALLOWED_HOSTS explicitly")


def _opener() -> urllib.request.OpenerDirector:
    if os.environ.get("ACR_ALLOW_PROXY") == "1":
        return urllib.request.build_opener()
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request_json(
    method: str, url: str, payload: dict[str, Any] | None = None, timeout: float = 30.0, headers: dict[str, str] | None = None
) -> Any:
    check_egress(url)
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with _opener().open(req, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode(errors="replace")
        raise AdapterError(f"HTTP {e.code} from {url}: {detail}", transient=e.code >= 500 or e.code == 429) from e
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise AdapterError(f"cannot reach {url}: {e}", transient=True) from e
    try:
        return json.loads(body or b"null")
    except json.JSONDecodeError:
        return body.decode(errors="replace")
