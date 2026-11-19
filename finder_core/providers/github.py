"""Public GitHub facts. Retrieved candidate files are data and never executed."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
from collections.abc import Sequence
from datetime import datetime
from urllib.parse import quote

from ..contracts import (Candidate, Evidence, FileEntry, FileInventory, Metric,
                         ProviderBatch, ProviderLimit, QuerySpec, SourceDocument)
from ..transport import HttpClient
from ..validation import ContractError

API = "https://api.github.com"
METHOD = "github-rest-v1"


class GitHubProvider:
    """Evidence/limits registries also expose observations from file/tree reads.

    Numeric IDs for file/tree methods must first be discovered or enriched on this
    instance; owner/name is also accepted. Only documented owner/name routes are
    used. Ref is retained as supplied: blob/tree IDs never become commit IDs.
    """

    def __init__(self, client: HttpClient):
        self.client = client
        self.evidence: list[Evidence] = []
        self.provider_limits: list[ProviderLimit] = []
        self._names: dict[str, str] = {}
        self._ids: dict[str, str] = {}
        self._observations: dict[str, Candidate] = {}
        self._commits: set[tuple[str, str]] = set()

    def _limit(self, reason):
        item = ProviderLimit("github", reason=reason)
        if item not in self.provider_limits:
            self.provider_limits.append(item)

    def _get(self, route, params=None, *, ttl="default", allow404=False):
        result = self.client.get("github", API + route, params or {},
                                 self.client.policy.cache.counts_seconds if ttl == "default" else ttl)
        for item in ([] if allow404 and result.status == 404 else result.limits):
            if item not in self.provider_limits:
                self.provider_limits.append(item)
        try:
            payload = json.loads(result.body,
                                 parse_constant=lambda _: "invalid upstream number",
                                 parse_float=lambda raw: float(raw) if math.isfinite(float(raw)) else "invalid upstream number")
        except (ValueError, UnicodeError):
            payload = None
        if allow404 and result.status == 404:
            return result, None
        if not 200 <= (result.status or 0) < 300 or payload is None:
            self._limit("GitHub response unavailable or invalid JSON")
            return result, None
        return result, payload

    def _evidence(self, result, subject, scope, data, *, status=None):
        # Only selected API facts are retained, never a local repository copy.
        excerpt = json.dumps(data, ensure_ascii=False, allow_nan=False, sort_keys=True)
        key = json.dumps([result.source_url, subject, result.fetched_at.isoformat(), scope, data], sort_keys=True)
        eid = "github-evidence:" + hashlib.sha256(key.encode()).hexdigest()
        item = Evidence(eid, result.source_url, subject, result.fetched_at, scope,
                        excerpt[:1200], "api", status or result.state,
                        "Read documented GitHub REST response fields", data)
        if not any(e.evidence_id == eid for e in self.evidence):
            self.evidence.append(item)
        return item

    def _repo(self, data, result, *, path=None, file_url=None):
        rid = data.get("id")
        name = data.get("full_name")
        if type(rid) is not int or rid <= 0 or not isinstance(name, str) or not re.fullmatch(r"[^/\s]+/[^/\s]+", name):
            self._limit("repository missing valid immutable ID or owner/name")
            return None
        if data.get("private") is True:
            self._limit("private repository excluded from public discovery")
            return None
        rid = str(rid)
        self._names[rid], self._ids[name] = name, rid
        subject = "github:" + rid
        scope = {"repository_id": rid, "level": "repository"}
        fields = {k: data[k] for k in ("id", "full_name", "stargazers_count", "forks_count", "subscribers_count", "license", "archived", "created_at", "pushed_at") if k in data}
        evidence = self._evidence(result, subject, scope, fields)
        identifiers = {"github_repository_id": rid, "full_name": name}
        if isinstance(data.get("default_branch"), str) and data["default_branch"]:
            identifiers["default_branch"] = data["default_branch"]
        card = Candidate(subject, "tool", identifiers=identifiers,
                         urls={"repository": "https://github.com/" + quote(name, safe="/")},
                         discovery_evidence_ids=[evidence.evidence_id])
        mapping = {"stars": ("stargazers_count", "count"), "forks": ("forks_count", "count"),
                   "watchers": ("subscribers_count", "count"), "archived": ("archived", "boolean"),
                   "license": ("license", "license"), "pushed_at": ("pushed_at", "datetime"),
                   "created_at": ("created_at", "datetime")}
        for logical, (field, unit) in mapping.items():
            value = data.get(field)
            if logical == "license":
                value = value.get("spdx_id") if isinstance(value, dict) else None
                if value in ("NOASSERTION", "", "OTHER"):
                    value = None
            card.metrics[logical] = self._metric(value, unit, result, subject, scope, evidence)
        if path:
            hit = self._evidence(result, subject, {**scope, "path": path, "level": "discovery"}, {"path": path})
            card.discovery_evidence_ids.append(hit.evidence_id)
            if isinstance(file_url, str) and file_url.startswith("https://github.com/"):
                card.urls["file:" + path] = file_url
        return card

    def _metric(self, value, unit, result, subject, scope, evidence, *, missing="unavailable"):
        status = result.state if value is not None else missing
        valid = True
        if value is not None:
            if unit == "count":
                valid = type(value) is int and value >= 0
            elif unit == "boolean":
                valid = type(value) is bool
            elif unit == "datetime":
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    valid = parsed.tzinfo is not None and parsed.utcoffset() is not None
                except (AttributeError, TypeError, ValueError):
                    valid = False
            elif unit == "license":
                valid = isinstance(value, str) and bool(value.strip())
        metric_scope = dict(scope)
        if not valid:
            value, status = None, "failed"
            metric_scope["reason"] = "invalid upstream " + unit + " value"
        return Metric(value, status, unit, "github", subject, result.fetched_at,
                      metric_scope, [evidence.evidence_id], METHOD)

    def search(self, query: QuerySpec) -> ProviderBatch:
        start = len(self.evidence)
        code_query = bool(re.search(r"(?:^|\s)(?:filename|path|extension):", query.query))
        code = code_query and self.client.is_authenticated("github")
        text = query.query
        if code_query and not code:
            text = re.sub(r'(?:^|\s)(?:filename|path|extension):(?:"[^"]*"|\S+)', " ", text).strip()
            self._limit("code file search unavailable without credentials; repository discovery and discovered file inspection fallback")
        text = (text or "SKILL") + " is:public"
        cap = min(60, self.client.policy.capacity.github_initial)
        params = {"q": text, "per_page": cap, "page": 1}
        if not code:
            params.update(sort="stars", order="desc")
        result, payload = self._get("/search/" + ("code" if code else "repositories"), params,
                                    ttl=self.client.policy.cache.queries_seconds)
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            self._limit("GitHub search envelope invalid or unavailable")
            return self._batch([], start, partial=True)
        self._evidence(result, query.query_id,
                       {"operation": "search", "provider": "github", "valid_response": True},
                       {"total_count": payload.get("total_count"),
                        "observed_items": len(payload["items"]),
                        "incomplete_results": payload.get("incomplete_results")})
        cards = {}
        items = payload["items"][:cap]
        for item in items:
            if not isinstance(item, dict):
                self._limit("invalid search result skipped")
                continue
            data = item.get("repository") if code else item
            if not isinstance(data, dict):
                self._limit("invalid code-search repository skipped")
                continue
            card = self._repo(data, result, path=item.get("path") if code else None,
                              file_url=item.get("html_url") if code else None)
            if card:
                if card.candidate_id in cards:
                    old = cards[card.candidate_id]
                    old.urls.update(card.urls)
                    old.discovery_evidence_ids = list(dict.fromkeys(old.discovery_evidence_ids + card.discovery_evidence_ids))
                else:
                    cards[card.candidate_id] = card
        self._limit(f"initial candidates maximum {cap}; observed before dedup {len(items)}; after dedup {len(cards)}")
        incomplete = payload.get("incomplete_results") is True
        if incomplete:
            self._limit("search incomplete_results=true; discovery is incomplete")
        total = payload.get("total_count")
        more = type(total) is int and total > len(items)
        if more or len(payload["items"]) > cap:
            self._limit(f"search pagination stopped at initial cap {cap}; more matches may exist")
        self._observations.update(cards)
        return self._batch(list(cards.values()), start, partial=result.partial or incomplete or more or (code_query and not code),
                           cursor="page=2" if more else None)

    def _batch(self, cards, start, *, partial=False, cursor=None):
        ids = {eid for c in cards for eid in c.discovery_evidence_ids}
        ids.update(eid for c in cards for m in c.metrics.values() for eid in m.evidence_ids)
        evidence = [e for n, e in enumerate(self.evidence) if n >= start or e.evidence_id in ids]
        return ProviderBatch(cards, evidence, list(self.provider_limits), partial, cursor)

    def _name(self, repo_id):
        key = repo_id.removeprefix("github:")
        name = self._names.get(key, key)
        if not re.fullmatch(r"[^/\s]+/[^/\s]+", name):
            raise ContractError("github.repo_id", "numeric repository ID must be discovered or enriched before file access; owner/name also accepted")
        return name

    def enrich(self, candidates: Sequence[Candidate]) -> ProviderBatch:
        start = len(self.evidence)
        cards, partial = [], False
        for original in candidates:
            rid = original.identifiers.get("github_repository_id")
            name = original.identifiers.get("full_name")
            if name and rid:
                self._names[rid], self._ids[name] = name, rid
            try:
                name = self._name(name or rid or "")
            except ContractError:
                self._limit("candidate lacks resolvable public repository identity")
                partial = True
                continue
            result, data = self._get("/repos/" + quote(name, safe="/"))
            card = self._repo(data, result) if isinstance(data, dict) else None
            if card is None:
                partial = True
                # Reuse only observations actually seen by this provider. Persisted
                # cards carry reserved provenance and cannot be copied into a batch.
                known = self._observations.get("github:" + (rid or ""))
                if known:
                    cards.append(Candidate.from_dict(known.to_dict()))
                continue
            if rid and card.identifiers["github_repository_id"] != rid:
                self._limit("repository identity changed at owner/name; detail not assigned to original")
                partial = True
                continue
            release, data = self._get("/repos/" + quote(name, safe="/") + "/releases/latest", allow404=True)
            scope = {"repository_id": card.identifiers["github_repository_id"], "level": "repository"}
            value = data.get("published_at") if isinstance(data, dict) else None
            ev = self._evidence(release, card.candidate_id, scope, {"published_at": value},
                                status="unavailable" if release.status == 404 else None)
            card.metrics["released_at"] = self._metric(value, "datetime", release, card.candidate_id, scope, ev,
                                                       missing="unavailable" if release.status == 404 or release.state in ("verified", "stale") else "failed")
            if original.kind == "skill" and (path := original.identifiers.get("skill_path", original.identifiers.get("path"))):
                card.kind = "skill"
                card.candidate_id += ":" + path
                card.identifiers["skill_path"] = path
            cards.append(card)
            partial |= result.partial or (release.partial and release.status != 404) or any(m.status == "failed" for m in card.metrics.values())
        return self._batch(cards, start, partial=partial)

    def resolve_ref(self, repo_id: str, ref: str) -> str | None:
        """Resolve one ref through the commits API; only this proves a commit pin."""
        name = self._name(repo_id)
        result, data = self._get("/repos/" + quote(name, safe="/") + "/commits/" + quote(ref, safe=""),
                                 ttl=self.client.policy.cache.queries_seconds)
        sha = data.get("sha") if isinstance(data, dict) else None
        valid = result.state == "verified" and isinstance(sha, str) and re.fullmatch(r"[0-9a-fA-F]{40}", sha)
        if not valid:
            self._limit("commit ref could not be verified; commit identity remains unknown")
            return None
        scope = {"repository_id": self._ids.get(name, name), "level": "commit", "ref": ref}
        self._evidence(result, "github:" + self._ids.get(name, name), scope, {"requested_ref": ref, "commit_sha": sha})
        self._commits.add((name, sha))
        return sha

    def _file_ttl(self, name, ref):
        return None if (name, ref) in self._commits and self.client.policy.cache.sha_files_indefinite else self.client.policy.cache.queries_seconds

    def read_file(self, repo_id: str, path: str, ref: str) -> SourceDocument:
        if not path or path.startswith("/") or "\\" in path or any(p in ("", ".", "..") for p in path.split("/")):
            raise ContractError("github.path", "expected a concrete relative repository file path")
        name = self._name(repo_id)
        subject = "github:" + self._ids.get(name, name)
        result, data = self._get("/repos/" + quote(name, safe="/") + "/contents/" + quote(path, safe="/"), {"ref": ref},
                                 ttl=self._file_ttl(name, ref))
        text, truncated = "", True
        if (isinstance(data, dict) and data.get("type") == "file"
                and data.get("encoding") == "base64" and isinstance(data.get("content"), str)):
            try:
                content = base64.b64decode("".join(data["content"].split()), validate=True)
                text = content.decode("utf-8")
                truncated = result.state != "verified" or ("size" in data and (type(data["size"]) is not int or data["size"] != len(content)))
            except (KeyError, TypeError, ValueError, UnicodeError, binascii.Error):
                pass
        if truncated:
            self._limit("file content unavailable, unsupported or truncated; content was not fully read")
        scope = {"repository_id": self._ids.get(name, name), "level": "file", "path": path, "ref": ref}
        facts = {"path": path, "ref": ref, "content_text": text, "truncated": truncated}
        if isinstance(data, dict) and isinstance(data.get("sha"), str):
            facts["blob_sha"] = data["sha"]
        ev = self._evidence(result, subject, scope, facts, status="failed" if truncated else None)
        return SourceDocument(subject, result.source_url, path, ref, text, truncated, result.fetched_at, [ev.evidence_id])

    def list_tree(self, repo_id: str, ref: str) -> FileInventory:
        name = self._name(repo_id)
        subject = "github:" + self._ids.get(name, name)
        result, data = self._get("/repos/" + quote(name, safe="/") + "/git/trees/" + quote(ref, safe=""),
                                 {"recursive": "1"}, ttl=self._file_ttl(name, ref))
        entries = []
        truncated = result.state != "verified" or not isinstance(data, dict) or not isinstance(data.get("tree"), list)
        if isinstance(data, dict) and isinstance(data.get("tree"), list):
            truncated |= data.get("truncated") is not False
            for item in data["tree"]:
                if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                    truncated = True
                    continue
                kind = {"blob": "file", "tree": "directory", "commit": "submodule"}.get(item.get("type"))
                if item.get("mode") == "120000":
                    kind = "symlink"
                if kind:
                    entries.append(FileEntry(item["path"], kind))
                else:
                    truncated = True
        if truncated:
            self._limit("repository tree truncated or unavailable; inventory is incomplete")
        scope = {"repository_id": self._ids.get(name, name), "level": "tree", "ref": ref}
        ev = self._evidence(result, subject, scope, {"ref": ref, "entries": [e.to_dict() for e in entries], "truncated": truncated})
        return FileInventory(repo_id, ref, entries, truncated, [ev.evidence_id])
