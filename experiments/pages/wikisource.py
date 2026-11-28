"""Small MediaWiki API helper for Vietnamese Wikisource (#271). Standard library only."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API = "https://vi.wikisource.org/w/api.php"
UA = "page-set-collector/1.0 (research project, low request rate)"


def _open(req: urllib.request.Request, timeout: int) -> bytes:
    """GET with a polite delay; on HTTP 429/503 wait (Retry-After, else growing) and retry."""
    for attempt in range(8):
        time.sleep(1.0)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()  # type: ignore[no-any-return]
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 503) or attempt == 7:
                raise
            time.sleep(float(exc.headers.get("Retry-After") or 15 * (attempt + 1)))
    raise RuntimeError("unreachable")


def api(base: str = API, **params: Any) -> dict[str, Any]:
    params["format"] = "json"
    req = urllib.request.Request(
        base + "?" + urllib.parse.urlencode(params), headers={"User-Agent": UA}
    )
    return json.loads(_open(req, 60))  # type: ignore[no-any-return]


def download(url: str, dest: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with open(dest, "wb") as fh:
        fh.write(_open(req, 120))
