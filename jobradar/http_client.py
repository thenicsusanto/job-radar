"""Tiny stdlib HTTP helper so the bot needs no pip installs (keeps each run fast)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

USER_AGENT = "job-radar/1.0 (personal internship alert bot)"
DEFAULT_TIMEOUT_SECONDS = 20


class NotFound(Exception):
    """The URL returned 404 (for an ATS board: the board does not exist)."""


class NotModified(Exception):
    """The server answered 304 to a conditional request."""


def fetch(
    url: str,
    *,
    etag: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = 2,
) -> tuple[bytes, str | None]:
    """GET a URL. Returns (body, etag). Raises NotFound / NotModified / OSError."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, */*"}
    if etag:
        headers["If-None-Match"] = etag
    last_error: Exception | None = None
    for attempt_number in range(attempts):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return response.read(), response.headers.get("ETag")
        except urllib.error.HTTPError as http_error:
            if http_error.code == 404:
                raise NotFound(url) from http_error
            if http_error.code == 304:
                raise NotModified(url) from http_error
            last_error = http_error
            if http_error.code not in (429, 500, 502, 503, 504):
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as network_error:
            last_error = network_error
        if attempt_number + 1 < attempts:
            time.sleep(1.5 * (attempt_number + 1))
    raise OSError(f"GET {url} failed: {last_error}")


def fetch_json(url: str, **keyword_arguments):
    body, _etag = fetch(url, **keyword_arguments)
    return json.loads(body)
