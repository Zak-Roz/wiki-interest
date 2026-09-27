"""HTTP layer: one place for User-Agent, retries, throttling and the disk cache.

Why a cache: founders iterate ("now add Slovak", "make it 3 years", "swap the
article") and every iteration re-requests mostly the same data. Cached JSON
responses make repeat runs instant and keep us far below Wikimedia's limits.
Completed date ranges never change, so they are cached forever; ranges that
touch "today" are refreshed after a few hours.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

import requests

DEFAULT_UA = (
    "wiki-interest-skill/0.1 (Wikipedia interest analysis skill; "
    "set WIKI_USER_AGENT to your contact)"
)
FOREVER = None  # ttl sentinel


class OfflineMiss(RuntimeError):
    """Raised in offline mode when a URL is not in the cache."""


class ApiError(RuntimeError):
    def __init__(self, url: str, status: int, body: str = ""):
        super().__init__(f"HTTP {status} for {url}: {body[:200]}")
        self.url, self.status, self.body = url, status, body


class NetworkBlocked(ApiError):
    """The environment will not let us reach this host (egress proxy, firewall,
    DNS). Retrying cannot help, so this is raised on the first attempt and the
    host is remembered for the rest of the run."""

    def __init__(self, url: str, host: str, reason: str):
        RuntimeError.__init__(self, f"network blocked: {host} ({reason})")
        self.url, self.status, self.body = url, 0, reason
        self.host, self.reason = host, reason


# Substrings that mean "the network refused us", not "the server had a hiccup".
# Covers requests/urllib3 proxy errors (CONNECT rejected by an egress proxy),
# DNS that is deliberately empty, and proxies that answer 403 themselves.
_BLOCK_MARKERS = (
    "tunnel connection failed", "unable to connect to proxy", "connect_rejected",
    "proxyerror", "failed to resolve", "name or service not known",
    "nodename nor servname", "temporary failure in name resolution",
    "getaddrinfo failed", "no address associated",
)


def host_of(url: str) -> str:
    return urlsplit(url).hostname or url


def _reason_from_exception(e: Exception) -> Optional[str]:
    if isinstance(e, requests.exceptions.ProxyError):
        return "egress proxy refused the connection"
    msg = str(e).lower()
    for m in _BLOCK_MARKERS:
        if m in msg:
            if "resolve" in m or "name" in m or "nodename" in m or "getaddrinfo" in m or "address" in m:
                return "DNS lookup failed (no network or host blocked)"
            return "egress proxy refused the connection"
    return None


def _reason_from_response(r) -> Optional[str]:
    """A proxy (not Wikimedia) answering 403/407 means the host is not allowed."""
    if r.status_code == 407:
        return "proxy requires authentication"
    if r.status_code == 403:
        deny = r.headers.get("x-deny-reason")
        text = (r.text or "")[:300].lower()
        if deny:
            return f"egress proxy: {deny}"
        if "allowlist" in text or "egress" in text or "not allowed" in text:
            return "egress proxy: host not allowed"
    return None


def cache_dir() -> Path:
    d = os.environ.get("WIKI_CACHE_DIR")
    if not d:
        d = os.path.join(os.path.expanduser("~"), ".cache", "wiki-interest")
    p = Path(d)
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_key(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def cache_path(url: str) -> Path:
    return cache_dir() / (cache_key(url) + ".json")


def cache_put(url: str, status: int, body: Any) -> None:
    """Public so tests/fixtures can seed the cache with canned responses."""
    rec = {"url": url, "status": status, "fetched_at": time.time(), "body": body}
    cache_path(url).write_text(json.dumps(rec, ensure_ascii=False))


def cache_get(url: str, ttl: Optional[float]) -> Optional[dict]:
    p = cache_path(url)
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    if ttl is not None and time.time() - rec.get("fetched_at", 0) > ttl:
        return None
    return rec


class Client:
    def __init__(self, offline: Optional[bool] = None, min_interval: float = 0.05):
        self.offline = (
            offline if offline is not None else os.environ.get("WIKI_OFFLINE") == "1"
        )
        self.min_interval = min_interval
        self._last = 0.0
        self.stats = {"hits": 0, "misses": 0, "requests": 0}
        self.blocked: dict = {}  # host -> reason, filled on the first refusal
        self.session = requests.Session()
        self.session.headers["User-Agent"] = os.environ.get("WIKI_USER_AGENT", DEFAULT_UA)
        self.session.headers["Accept"] = "application/json"

    def get_json(self, url: str, ttl: Optional[float] = FOREVER, ok404: bool = False) -> Any:
        """GET a JSON document, via cache. 404 -> None if ok404 else ApiError."""
        rec = cache_get(url, ttl)
        if rec is not None:
            self.stats["hits"] += 1
            if rec["status"] == 404:
                if ok404:
                    return None
                raise ApiError(url, 404, "cached 404")
            return rec["body"]
        self.stats["misses"] += 1
        if self.offline:
            raise OfflineMiss(f"offline mode and not cached: {url}")
        host = host_of(url)
        if host in self.blocked:  # fail fast: we already know this host is unreachable
            raise NetworkBlocked(url, host, self.blocked[host])
        body, status = self._request(url)
        if status == 404:
            cache_put(url, 404, None)
            if ok404:
                return None
            raise ApiError(url, 404, str(body)[:200])
        cache_put(url, 200, body)
        return body

    def _request(self, url: str):
        delays = [1, 3, 8]
        for attempt in range(len(delays) + 1):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            self.stats["requests"] += 1
            try:
                r = self.session.get(url, timeout=30)
            except requests.RequestException as e:
                reason = _reason_from_exception(e)
                if reason:  # blocked, not flaky: retrying only wastes time
                    raise self._block(url, reason)
                if attempt == len(delays):
                    raise self._block(url, f"unreachable after {attempt + 1} attempts ({type(e).__name__})")
                time.sleep(delays[attempt])
                continue
            reason = _reason_from_response(r)
            if reason:
                raise self._block(url, reason)
            if r.status_code == 200:
                return r.json(), 200
            if r.status_code == 404:
                return r.text, 404
            if r.status_code in (429, 500, 502, 503, 504) and attempt < len(delays):
                retry_after = r.headers.get("Retry-After")
                time.sleep(float(retry_after) if retry_after else delays[attempt])
                continue
            raise ApiError(url, r.status_code, r.text)
        raise ApiError(url, 0, "retries exhausted")

    def _block(self, url: str, reason: str) -> NetworkBlocked:
        host = host_of(url)
        self.blocked[host] = reason
        return NetworkBlocked(url, host, reason)

    def probe(self, url: str, timeout: float = 8.0) -> tuple:
        """One uncached GET, no retries -> ("ok" | "blocked" | "error", detail).
        Used by `wiki.py check` and to explain a failed run."""
        if host_of(url) in self.blocked:
            return "blocked", self.blocked[host_of(url)]
        try:
            r = self.session.get(url, timeout=timeout)
        except requests.RequestException as e:
            reason = _reason_from_exception(e)
            return ("blocked", reason) if reason else ("error", f"{type(e).__name__}: {str(e)[:120]}")
        reason = _reason_from_response(r)
        if reason:
            return "blocked", reason
        if r.status_code >= 400 and r.status_code != 404:
            return "error", f"HTTP {r.status_code}"
        return "ok", f"HTTP {r.status_code}"
