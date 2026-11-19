"""Small atomic file cache. Payloads retain their original observation time."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, quote, quote_plus, urlencode, urlsplit, urlunsplit

SECRET_ENV = ("GITHUB_TOKEN", "OPENALEX_API_KEY", "SEMANTIC_SCHOLAR_API_KEY")
SECRET_KEYS = {"token", "access_token", "api_key", "apikey", "authorization", "password", "key", "x-api-key"}


def redact_text(value: str, secrets=()) -> str:
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        for form in {secret, quote(secret, safe=""), quote_plus(secret)}:
            value = value.replace(form, "[REDACTED]")
    names = "|".join(re.escape(k) for k in SECRET_KEYS)
    value = re.sub(r'(?i)(?<![\w-])(["\']?(?:' + names + r')["\']?\s*[:=]\s*)("[^"\r\n]*"|\'[^\'\r\n]*\'|(?:Bearer\s+)?[^\s,;&}]+)',
                   lambda m: m[1] + '"[REDACTED]"', value)
    return re.sub(r"(?i)\bBearer\s+[^\s\"',;]+", "Bearer [REDACTED]", value)


def public_url(url: str) -> str:
    """Remove URL credentials, secret query fields and fragments."""
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    port = parsed.port
    netloc = host + (f":{port}" if port is not None else "")
    query = sorted((k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() not in SECRET_KEYS)
    return urlunsplit((parsed.scheme.lower(), netloc.lower(), parsed.path or "/", urlencode(query), ""))


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("cache time must include a timezone")
    return value.astimezone(timezone.utc)


@dataclass
class CacheEntry:
    payload: bytes
    source_url: str
    saved_at: datetime
    ttl_seconds: int | None
    status: int = 200

    def __post_init__(self):
        self.saved_at = _aware(self.saved_at)
        if self.ttl_seconds is not None and (type(self.ttl_seconds) is not int or self.ttl_seconds < 0):
            raise ValueError("cache TTL must be a nonnegative integer or null")
        if type(self.payload) is not bytes or type(self.status) is not int:
            raise ValueError("invalid cache payload or status")

    def is_stale(self, now: datetime) -> bool:
        return self.ttl_seconds is not None and (_aware(now) - self.saved_at).total_seconds() >= self.ttl_seconds


class FileCache:
    def __init__(self, directory: Path | str):
        self.directory = Path(directory)

    def _path(self, key: str) -> Path:
        return self.directory / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json")

    def get(self, key: str, now: datetime, allow_stale: bool = False) -> CacheEntry | None:
        now = _aware(now)
        try:
            data = json.loads(self._path(key).read_text(encoding="utf-8"))
            entry = CacheEntry(base64.b64decode(data["payload"], validate=True), data["source_url"],
                               datetime.fromisoformat(data["saved_at"]), data["ttl_seconds"], data["status"])
            if entry.saved_at > now or (entry.is_stale(now) and not allow_stale):
                return None
            return entry
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def put(self, key: str, entry: CacheEntry) -> None:
        secrets = tuple(os.environ.get(name, "") for name in SECRET_ENV)
        payload = redact_text(entry.payload.decode("utf-8", errors="replace"), secrets).encode("utf-8")
        data = {"payload": base64.b64encode(payload).decode("ascii"), "source_url": redact_text(public_url(entry.source_url), secrets),
                "saved_at": entry.saved_at.isoformat(), "ttl_seconds": entry.ttl_seconds, "status": entry.status}
        self.directory.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory, suffix=".tmp", delete=False) as handle:
                name = handle.name
                json.dump(data, handle, ensure_ascii=False, allow_nan=False)
            os.replace(name, self._path(key))
        finally:
            if name is not None:
                Path(name).unlink(missing_ok=True)
