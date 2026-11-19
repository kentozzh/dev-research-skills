"""Shared checked paper facts; no title-based identities or inferred authority."""
from __future__ import annotations

import calendar
import json
import math
import re
from urllib.parse import quote

from ..contracts import Evidence, Metric, ProviderBatch, ProviderLimit
from ..evidence import content_hash
from ..validation import reportable_url


def doi(value):
    if not isinstance(value, str):
        return None
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/|^doi:", "", value.strip(), flags=re.I).lower()
    return value if re.fullmatch(r"10\.\d{4,9}/\S+", value) else None


def doi_url(identifier):
    return "https://doi.org/" + quote(identifier, safe="/:%")


def checked_link(value):
    """Return an optional upstream URL only if it can safely be reported."""
    return value if reportable_url(value) else None


def checked_link_metadata(value):
    """Validate links before persisting a provider location or access object."""
    if isinstance(value, dict):
        return {key: checked_link(item) if key == "url" or key.endswith("_url") else checked_link_metadata(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [checked_link_metadata(item) for item in value]
    if isinstance(value, str) and value.lstrip().lower().startswith(("http://", "https://")):
        return checked_link(value)
    return value


def arxiv(value):
    if not isinstance(value, str):
        return None
    value = re.sub(r"^https?://(?:export\.)?arxiv\.org/abs/|^arxiv:", "", value.strip(), flags=re.I)
    return value if re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})(?:v\d+)?", value) else None


def normalized_identity(name, value):
    if name == "doi":
        return doi(value)
    if name == "arxiv":
        value = arxiv(value)
        return re.sub(r"v\d+$", "", value) if value else None
    return value


def date_range(client):
    end = client.now().date()
    month = end.year * 12 + end.month - 1 - client.policy.paper.recent_months
    year, month = divmod(month, 12)
    start = end.replace(year=year, month=month + 1, day=min(end.day, calendar.monthrange(year, month + 1)[1]))
    return start.isoformat(), end.isoformat()


def chain_query(text):
    for direction in ("references", "citations"):
        if text.startswith(direction + ":"):
            return direction, text[len(direction) + 1:].strip()
    return None, None


class PaperProvider:
    def __init__(self, client):
        self.client = client
        self.evidence = []
        self.provider_limits = []

    def _limit(self, reason):
        limit = ProviderLimit(self.name, reason=reason)
        if limit not in self.provider_limits:
            self.provider_limits.append(limit)

    def _get(self, url, params=None, *, query=False, xml=False, static=False):
        ttl = (self.client.policy.cache.paper_identity_seconds if static else
               self.client.policy.cache.queries_seconds if query else self.client.policy.cache.counts_seconds)
        result = self.client.get(self.name, url, params or {}, ttl)
        for limit in result.limits:
            if limit not in self.provider_limits:
                self.provider_limits.append(limit)
        if not 200 <= (result.status or 0) < 300:
            self._limit("Paper response unavailable; source coverage incomplete")
            return result, None
        if xml:
            return result, result.body
        try:
            data = json.loads(result.body, parse_constant=lambda _: "invalid upstream number",
                parse_float=lambda raw: float(raw) if math.isfinite(float(raw)) else "invalid upstream number")
        except (ValueError, UnicodeError):
            self._limit("Paper response invalid JSON; source coverage incomplete")
            data = None
        return result, data

    def _evidence(self, result, subject, data, scope=None):
        scope = {"provider": self.name, **(scope or {})}
        eid = self.name + "-evidence:" + content_hash([result.source_url, subject, result.fetched_at.isoformat(), scope, data])
        item = Evidence(eid, result.source_url, subject, result.fetched_at, scope,
            json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False)[:1600], "api", result.state,
            "Read documented " + self.name + " response fields", data)
        if not any(e.evidence_id == eid for e in self.evidence):
            self.evidence.append(item)
        return item

    def _query_evidence(self, result, query, count, **scope):
        return self._evidence(result, query.query_id, {"observed_items": count},
            {"operation":"search", "valid_response":True, "route":query.route, **scope})

    def _metric(self, value, unit, result, subject, evidence, *, scope=None, method=None):
        status = result.state if value is not None else "unavailable"
        valid = True
        if value is not None:
            if unit in {"count", "year"}:
                valid = type(value) is int and value >= 0
            elif unit == "percentile":
                valid = type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 1
            elif unit == "boolean":
                valid = type(value) is bool
            elif unit == "text":
                valid = isinstance(value, str) and bool(value.strip())
        scope = {"level":"paper", **(scope or {})}
        if not valid:
            value, status = None, "failed"
            scope["reason"] = "invalid upstream " + unit
            self._limit("Invalid upstream paper metric retained as unknown; other facts preserved")
        return Metric(value, status, unit, self.name, subject, result.fetched_at, scope,
                      [evidence.evidence_id], method or self.method)

    def _batch(self, cards, start=0, *, partial=False, cursor=None, query_subject=None):
        # Identical IDs in an upstream page are one record, never duplicate imports.
        unique = {card.candidate_id:card for card in cards}
        referenced = {eid for card in cards for eid in card.discovery_evidence_ids}
        referenced.update(eid for card in cards for metric in card.metrics.values() for eid in metric.evidence_ids)
        referenced.update(eid for card in cards for relation in card.relations for eid in relation.evidence_ids)
        evidence = [e for index,e in enumerate(self.evidence) if index >= start or e.evidence_id in referenced or e.subject_id == query_subject]
        return ProviderBatch(list(unique.values()), evidence, list(self.provider_limits),
            partial or bool(self.provider_limits) or any(m.status in {"failed","conflict","stale"} for c in cards for m in c.metrics.values()), cursor)
