"""Read-only HTTP with shared run budgets, bounded waits and safe provenance."""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from multiprocessing import get_context
from typing import Callable
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .cache import CacheEntry, FileCache, SECRET_ENV, SECRET_KEYS, public_url, redact_text
from .contracts import Policy, ProviderLimit


@dataclass
class WireResponse:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class HttpResult:
    status: int | None
    body: bytes
    source_url: str
    fetched_at: datetime
    state: str = "verified"
    limits: list[ProviderLimit] = field(default_factory=list)
    from_cache: bool = False

    @property
    def partial(self) -> bool:
        return bool(self.limits) or self.state != "verified"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_MESSAGE_SIZE = 4096


def _request_worker(connection, url: str, headers: dict[str, str], timeout: float) -> None:
    """One GET in an owned child; never return exception text/request headers."""
    try:
        # Disable urllib's credential-forwarding automatic redirect handler.
        opener = build_opener(_NoRedirect())
        try:
            response = opener.open(Request(url, headers=headers, method="GET"), timeout=timeout)
        except HTTPError as exc:
            response = exc
        with response:
            metadata = json.dumps({"status": response.code, "headers": dict(response.headers.items())}).encode("utf-8")
            for offset in range(0, len(metadata), _MESSAGE_SIZE - 1):
                connection.send_bytes(b"H" + metadata[offset:offset + _MESSAGE_SIZE - 1])
            while True:
                chunk = response.read1(_MESSAGE_SIZE - 1)
                if not chunk:
                    break
                connection.send_bytes(b"B" + chunk)
        connection.send_bytes(b"")
    except Exception as exc:
        # Invalid header values can contain credentials. Only a safe error kind
        # crosses IPC, including when the parent has already closed its end.
        try:
            connection.send_bytes(b"V" if isinstance(exc, ValueError) else b"E")
        except (OSError, EOFError):
            pass
    finally:
        connection.close()


def _request(url: str, headers: dict[str, str], timeout: float) -> WireResponse:
    """Bound the entire acquisition, including DNS, headers and IPC, by a deadline.

    Socket inactivity timeouts cannot stop a progressing response. An owned
    short-lived spawn child makes cancellation portable without leaving request
    threads behind. Small framed messages prevent a large blocking IPC read.
    """
    deadline = time.monotonic() + timeout
    context = get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_request_worker, args=(sender, url, headers, timeout))
    started = False
    metadata, body = bytearray(), []
    try:
        process.start()
        started = True
        sender.close()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not receiver.poll(remaining):
                raise TimeoutError("HTTP acquisition deadline exhausted")
            try:
                message = receiver.recv_bytes(_MESSAGE_SIZE)
            except (EOFError, OSError):
                raise OSError("HTTP worker ended without a complete response") from None
            if not message:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("HTTP acquisition deadline exhausted")
                process.join(remaining)
                if process.is_alive() or time.monotonic() >= deadline:
                    raise TimeoutError("HTTP acquisition deadline exhausted")
                decoded = json.loads(metadata)
                result = WireResponse(decoded["status"], b"".join(body), decoded["headers"])
                if time.monotonic() >= deadline:
                    raise TimeoutError("HTTP acquisition deadline exhausted")
                return result
            if message[:1] == b"H":
                metadata.extend(message[1:])
            elif message[:1] == b"B":
                body.append(message[1:])
            elif message == b"V":
                raise ValueError("invalid HTTP request configuration")
            else:
                raise OSError("HTTP worker acquisition failed")
    finally:
        sender.close()
        receiver.close()
        if started:
            if process.is_alive():
                process.terminate()
            process.join()
        process.close()


def _normalized_url(url: str, params: dict) -> str:
    parsed = urlsplit(public_url(url))
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    for key, value in params.items():
        if key.lower() not in SECRET_KEYS and value is not None:
            values = value if isinstance(value, (list, tuple)) else [value]
            pairs.extend((key, str(item)) for item in values)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(sorted(pairs)), ""))


def cache_key(provider: str, url: str, params: dict, visibility: str) -> str:
    material = json.dumps([provider, _normalized_url(url, params), visibility], separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


_HOSTS = {"github": {"api.github.com", "raw.githubusercontent.com"},
          "arxiv": {"export.arxiv.org", "arxiv.org"}, "openalex": {"api.openalex.org"},
          "semantic_scholar": {"api.semanticscholar.org"}}
_AUTH = {"github": ("GITHUB_TOKEN", "api.github.com", "Authorization", "Bearer "),
         "openalex": ("OPENALEX_API_KEY", "api.openalex.org", "Authorization", "Bearer "),
         "semantic_scholar": ("SEMANTIC_SCHOLAR_API_KEY", "api.semanticscholar.org", "x-api-key", "")}
_WAIT_KEY = "transport_wait_milliseconds"
_ARXIV_KEY = "transport_arxiv_last_milliseconds"
_LIVE_REASONS = {"provider quota exhausted", "provider authentication or access denied", "provider retry cooldown"}


def _strongest_limit(previous, current):
    if previous is not None and (previous.reset_at is None or
                                (current.reset_at is not None and previous.reset_at > current.reset_at)):
        return previous
    return current


class HttpClient:
    def __init__(self, cache: FileCache, *, policy: Policy, skill: str, request_counts: dict[str, int] | None = None,
                 provider_limits: list[ProviderLimit] | None = None,
                 environ: dict[str, str] | None = None, request: Callable = _request,
                 now: Callable = lambda: datetime.now(timezone.utc), monotonic: Callable = time.monotonic,
                 sleep: Callable = time.sleep):
        if skill not in ("skill-finding", "tool-finding", "paper-finding"):
            raise ValueError("unknown skill")
        self.cache, self.policy, self.skill = cache, policy, skill
        self.request_counts = request_counts if request_counts is not None else {}
        if any(type(n) is not int or n < 0 for n in self.request_counts.values()):
            raise ValueError("request counts must be nonnegative integers")
        env = os.environ if environ is None else environ
        self._credentials = {name: env.get(name, "") for name in SECRET_ENV}
        self.request, self.now, self.monotonic, self.sleep = request, now, monotonic, sleep
        self.provider_limits = provider_limits if provider_limits is not None else []
        self.wait_seconds = self.request_counts.get(_WAIT_KEY, 0) / 1000.0
        self._live = {}
        for limit in self.provider_limits:
            if limit.reason in _LIVE_REASONS:
                self._live[limit.provider] = _strongest_limit(self._live.get(limit.provider), limit)
        stamp = self.request_counts.get(_ARXIV_KEY)
        self._arxiv_last = datetime.fromtimestamp(stamp / 1000, timezone.utc) if stamp is not None else None
        self._lock = threading.RLock()
        self._paper_initial_route = None

    @contextmanager
    def paper_initial_scope(self, route: str):
        """Charge actual initial-paper attempts to one persisted policy lane.

        The lock covers the complete synchronous scope, including provider
        retries and redirects. Cached reads remain free. Enrichment outside this
        scope still consumes the shared structured budget, without a lane reset.
        """
        if self.skill != "paper-finding" or route not in {"recent", "classic"}:
            raise ValueError("paper initial scope requires recent/classic in a paper run")
        with self._lock:
            previous = self._paper_initial_route
            self._paper_initial_route = route
            try:
                yield
            finally:
                self._paper_initial_route = previous

    def is_authenticated(self, provider: str) -> bool:
        """Report existing credential capability without exposing it or issuing I/O."""
        auth = _AUTH.get(provider)
        return bool(auth and self._credentials[auth[0]])

    def _record_wait(self, seconds):
        self.wait_seconds += max(0.0, seconds)
        self.request_counts[_WAIT_KEY] = math.ceil(self.wait_seconds * 1000)

    def _record_live(self, limit):
        # Different response headers impose simultaneous restrictions. A shorter
        # deadline must never erase a longer/indefinite restriction.
        limit = _strongest_limit(self._live.get(limit.provider), limit)
        self._live[limit.provider] = limit
        self.provider_limits[:] = [old for old in self.provider_limits
                                   if not (old.provider == limit.provider and old.reason in _LIVE_REASONS)]
        self.provider_limits.append(limit)
        return limit

    def _limit(self, provider, reason, remaining=None, reset_at=None):
        return ProviderLimit(provider, remaining, reset_at, reason)

    def _blocked(self, provider):
        if self._paper_initial_route is not None:
            route = self._paper_initial_route
            cap = int(self.policy.budgets.paper_structured * self.policy.paper.route_budget_shares[route])
            if self.request_counts.get("transport_paper_initial_" + route, 0) >= cap:
                return self._limit(provider, "initial paper " + route + " request budget exhausted", 0)
        live = self._live.get(provider)
        if live is not None and (live.reset_at is None or live.reset_at > self.now()):
            return live
        if live is not None:
            del self._live[provider]
        if provider == "github":
            cap = self.policy.budgets.github_authenticated if self._credentials["GITHUB_TOKEN"] else self.policy.budgets.github_anonymous
            if self.request_counts.get(provider, 0) >= cap:
                return self._limit(provider, "run request budget exhausted", 0)
        if self.skill == "paper-finding" and self.request_counts.get("paper_structured", 0) >= self.policy.budgets.paper_structured:
            return self._limit(provider, "shared paper request budget exhausted", 0)
        if self.wait_seconds >= self.policy.transport.max_wait_seconds:
            return self._limit(provider, "run network wait budget exhausted")
        return None

    def _wait(self, seconds):
        seconds = max(0.0, seconds)
        if seconds >= self.policy.transport.max_wait_seconds - self.wait_seconds:
            return False
        if seconds:
            start = self.monotonic()
            self.sleep(seconds)
            self._record_wait(max(seconds, self.monotonic() - start, 0.0))
        return True

    def _retry_delay(self, headers, retry):
        raw = headers.get("retry-after", "")
        try:
            seconds = float(raw)
            if math.isfinite(seconds):
                return max(0.0, seconds)
        except ValueError:
            pass
        try:
            return max(0.0, (parsedate_to_datetime(raw) - self.now()).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return float(2 ** retry)

    def get(self, provider: str, url: str, params: dict, ttl_seconds: int | None) -> HttpResult:
        # Serialize calls: arXiv permits one connection, and budget reservation
        # plus request issuance must be atomic for concurrent provider callers.
        with self._lock:
            return self._get(provider, url, params, ttl_seconds)

    def _get(self, provider, url, params, ttl_seconds):
        if ttl_seconds is not None and (type(ttl_seconds) is not int or ttl_seconds < 0):
            raise ValueError("TTL must be a nonnegative integer or null")
        secrets = tuple(self._credentials.values())
        try:
            source = _normalized_url(url, params)
            parsed = urlsplit(source)
            allowed = provider in _HOSTS and parsed.scheme == "https" and parsed.hostname in _HOSTS[provider] and parsed.port in (None, 443)
        except (ValueError, TypeError, AttributeError):
            source, allowed = "https://invalid.invalid/", False
        source = redact_text(source, secrets)
        if not allowed:
            return HttpResult(None, b"", source, self.now(), "failed", [self._limit(provider, "unsupported provider URL")])
        auth = _AUTH.get(provider)
        credential = self._credentials[auth[0]] if auth and parsed.hostname == auth[1] else ""
        visibility = "authenticated:" + hashlib.sha256(credential.encode()).hexdigest() if credential else "public"
        key = cache_key(provider, source, {}, visibility)
        try:
            cached = self.cache.get(key, self.now(), False)
        except OSError:
            cached = None
        if cached is not None and ttl_seconds is not None and (self.now() - cached.saved_at).total_seconds() >= ttl_seconds:
            cached = None
        if cached is not None:
            return HttpResult(cached.status, cached.payload, cached.source_url, cached.saved_at, from_cache=True)
        headers = {"User-Agent": "dev-research-skills/1.0 (read-only research)", "Accept": "application/json"}
        if provider == "github":
            headers["X-GitHub-Api-Version"] = "2026-03-10"
        if credential:
            headers[auth[2]] = auth[3] + credential
        last = HttpResult(None, b"", source, self.now(), "failed")
        retries, redirects = 0, 0
        request_url = source
        while True:
            blocked = self._blocked(provider)
            if blocked:
                last.limits.append(blocked)
                break
            if provider == "arxiv" and self._arxiv_last is not None:
                interval = self.policy.transport.arxiv_interval_seconds - (self.now() - self._arxiv_last).total_seconds()
                if not self._wait(interval):
                    last.limits.append(self._limit(provider, "arXiv interval exceeds remaining network wait budget"))
                    break
            timeout = min(self.policy.transport.timeout_seconds, self.policy.transport.max_wait_seconds - self.wait_seconds)
            if timeout <= 0:
                last.limits.append(self._limit(provider, "run network wait budget exhausted"))
                break
            self.request_counts[provider] = self.request_counts.get(provider, 0) + 1
            if self.skill == "paper-finding":
                self.request_counts["paper_structured"] = self.request_counts.get("paper_structured", 0) + 1
                if self._paper_initial_route is not None:
                    lane_key = "transport_paper_initial_" + self._paper_initial_route
                    self.request_counts[lane_key] = self.request_counts.get(lane_key, 0) + 1
            started = self.monotonic()
            if provider == "arxiv":
                self._arxiv_last = self.now()
                self.request_counts[_ARXIV_KEY] = math.ceil(self._arxiv_last.timestamp() * 1000)
            configuration_failed = False
            try:
                reply = self.request(request_url, dict(headers), timeout)
            except (OSError, HTTPException):
                reply = None
            except ValueError:
                # urllib may put a credential-bearing header value in this
                # exception. Configuration failures are neither echoed nor retried.
                reply, configuration_failed = None, True
            finally:
                self._record_wait(self.monotonic() - started)
            response_headers = {k.lower(): v for k, v in reply.headers.items()} if reply else {}
            if configuration_failed:
                last.limits.append(self._limit(provider, "invalid HTTP request configuration"))
                break
            if reply:
                last = HttpResult(reply.status, redact_text(reply.body.decode("utf-8", errors="replace"), secrets).encode("utf-8"),
                                  source, self.now(), "verified" if 200 <= reply.status < 300 else "failed")
                reset = None
                try:
                    reset = datetime.fromtimestamp(float(response_headers["x-ratelimit-reset"]), timezone.utc)
                except (KeyError, ValueError, OverflowError, OSError):
                    pass
                if response_headers.get("x-ratelimit-remaining") == "0":
                    limit = self._limit(provider, "provider quota exhausted", 0, reset)
                    limit = self._record_live(limit)
                    last.limits.append(limit)
                if 200 <= reply.status < 300:
                    try:
                        self.cache.put(key, CacheEntry(last.body, source, last.fetched_at, ttl_seconds, reply.status))
                    except OSError:
                        last.limits.append(self._limit(provider, "cache write unavailable"))
                    return last
                if reply.status in (301, 302, 303, 307, 308):
                    try:
                        target = urljoin(request_url, response_headers.get("location", ""))
                        target_parts = urlsplit(target)
                        target_parts.port
                    except ValueError:
                        last.limits.append(self._limit(provider, "malformed provider redirect"))
                        break
                    origin = urlsplit(request_url)
                    if (target_parts.scheme, target_parts.netloc) != (origin.scheme, origin.netloc) or redirects >= 5:
                        last.limits.append(self._limit(provider, "redirect blocked outside original origin or redirect limit"))
                        break
                    request_url = public_url(target)
                    redirects += 1
                    continue
                if reply.status in (401, 403):
                    limit = self._limit(provider, "provider authentication or access denied", 0, reset)
                    limit = self._record_live(limit)
                    last.limits.append(limit)
                    break
                if reply.status not in (429, 500, 502, 503, 504):
                    last.limits.append(self._limit(provider, "provider HTTP request failed"))
                    break
            if retries >= self.policy.transport.max_retries:
                last.limits.append(self._limit(provider, "bounded retries exhausted"))
                break
            blocked = self._blocked(provider)
            if blocked:
                last.limits.append(blocked)
                break
            delay = self._retry_delay(response_headers, retries)
            if not self._wait(delay):
                last.limits.append(self._limit(provider, "retry delay exceeds remaining network wait budget"))
                break
            retries += 1
        if last.status == 429:
            delay = self._retry_delay(response_headers, retries)
            try:
                reset_at = self.now() + timedelta(seconds=delay)
            except OverflowError:
                reset_at = None
            limit = self._limit(provider, "provider retry cooldown", 0, reset_at)
            limit = self._record_live(limit)
            last.limits.append(limit)
        # Failed refresh never erases useful cached observations or changes their date.
        cached = self.cache.get(key, self.now(), True)
        if cached is not None:
            return HttpResult(cached.status, cached.payload, cached.source_url, cached.saved_at, "stale", last.limits, True)
        return last
