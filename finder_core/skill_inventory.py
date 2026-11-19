"""Read-only concrete SKILL.md inventory; frontmatter semantics belong to the Agent."""
from __future__ import annotations

from copy import deepcopy
import posixpath
import re
from typing import Sequence
from urllib.parse import unquote, urlsplit

from .contracts import Candidate, Evidence, ObservationBatch, SourceDocument
from .evidence import content_hash
from .validation import ContractError


def normalize_skill_path(path: str) -> str:
    """Normalize a repository path without admitting a filesystem or URL target."""
    if not isinstance(path, str) or not path or path.startswith(("/", "\\", "~")) or ":" in path or "\x00" in path:
        raise ContractError("skill.path", "requires a repository-relative SKILL.md path")
    path = posixpath.normpath(path.replace("\\", "/"))
    if path in {".", ".."} or path.startswith("../") or posixpath.basename(path) != "SKILL.md":
        raise ContractError("skill.path", "requires a repository-relative SKILL.md path")
    return path


def skill_candidate_id(repository_id: str, path: str) -> str:
    # Hash the path only for an unambiguous compact ID; readable identity stays explicit.
    return "github:" + repository_id + ":skill:" + content_hash(normalize_skill_path(path))[:24]


def candidate_skill_path(card: Candidate) -> str | None:
    """Accept the established host-import path alias, rejecting ambiguous identity."""
    paths = {normalize_skill_path(card.identifiers[key]) for key in ("skill_path", "path") if key in card.identifiers}
    if len(paths) > 1:
        raise ContractError("skill.path", "skill_path and path must identify the same concrete SKILL.md")
    return next(iter(paths), None)


def resolve_reference(skill_path: str, target: str) -> dict:
    """Classify one reference; never access a filesystem, URL or command."""
    result = {"target": target}
    decoded = unquote(target.strip().strip("<>"))
    try:
        parsed = urlsplit(decoded)
    except ValueError:
        return {**result, "kind": "local_or_unsupported"}
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return {**result, "kind": "external"}
    if (parsed.scheme or decoded.startswith(("/", "\\", "~", "$")) or "\x00" in decoded or not parsed.path):
        return {**result, "kind": "local_or_unsupported"}
    root = posixpath.dirname(normalize_skill_path(skill_path))
    path = posixpath.normpath(posixpath.join(root, parsed.path.replace("\\", "/")))
    if path == ".." or path.startswith("../"):
        return {**result, "kind": "outside_repository"}
    inside = not root or path.startswith(root + "/")
    return {**result, "kind": "skill" if inside else "shared", "path": path}


def scan_references(document: SourceDocument) -> list[dict]:
    """Find Markdown links and standalone literal file paths, without parsing YAML.

    This is discovery only, not a complete Markdown/frontmatter parser. The Agent
    reads source text for semantic dependencies, tool requirements and licenses.
    """
    hits = [(m.start(), m.group(1)) for m in re.finditer(r"\[[^\]\n]*\]\(([^\s)]+)(?:\s+[^)]*)?\)", document.content_text)]
    hits.extend((m.start(), m.group(1)) for m in re.finditer(r"`([^`\s]+(?:\.[A-Za-z0-9]+))`", document.content_text)
                if "/" in m.group(1) or "\\" in m.group(1))
    seen, result = set(), []
    for _, target in sorted(hits):
        if target in seen or target.startswith("#"):
            continue
        seen.add(target)
        result.append(resolve_reference(document.path, target))
    return result


def extract_skill_candidates(repo: Candidate, files: Sequence[SourceDocument]) -> ObservationBatch:
    """Only complete, actually read concrete SKILL.md documents become entities.

    Repository metric objects retain their repository subject/scope. Generated
    file evidence records source text for later Agent semantic assessment; caller
    must merge the underlying provider registry to resolve file/metric evidence.
    """
    repository_id = repo.identifiers.get("github_repository_id")
    if not repository_id:
        raise ContractError("skill.repository", "requires an immutable GitHub repository ID")
    cards, observations = {}, {}
    subjects = {repo.candidate_id, repository_id, "github:" + repository_id}
    if repo.identifiers.get("full_name"):
        subjects.add("github:" + repo.identifiers["full_name"])
    for doc in files:
        if doc.truncated or not doc.content_text.strip() or doc.subject_id not in subjects:
            continue
        try:
            path = normalize_skill_path(doc.path)
        except ContractError:
            continue
        cid = skill_candidate_id(repository_id, path)
        source = {"path": path, "ref": doc.ref, "content_text": doc.content_text,
                  "source_evidence_ids": doc.evidence_ids, "references": scan_references(doc)}
        eid = "skill-read:" + content_hash({"subject": cid, "source": source, "fetched_at": doc.fetched_at.isoformat()})
        identifiers = {key: repo.identifiers[key] for key in ("github_repository_id", "full_name", "default_branch") if key in repo.identifiers}
        identifiers.update(skill_path=path, source_ref=doc.ref)
        sha = repo.identifiers.get("commit_sha")
        if sha == doc.ref and re.fullmatch(r"[0-9a-fA-F]{40}", sha or ""):
            identifiers["commit_sha"] = sha
        observations[eid] = Evidence(eid, doc.source_url, cid, doc.fetched_at,
            {"repository_id": repository_id, "level": "file", "path": path, "ref": doc.ref},
            "Read concrete SKILL.md; repository metrics are shared; semantic assessment required",
            "repository", "verified", "complete source-document read; no execution or YAML interpretation", source)
        cards[cid] = Candidate(cid, "skill", identifiers,
            urls={"repository": "https://github.com/" + identifiers["full_name"], "skill": doc.source_url} if "full_name" in identifiers else {"skill": doc.source_url},
            versions=[sha] if "commit_sha" in identifiers else [], metrics=deepcopy(repo.metrics),
            discovery_evidence_ids=[eid])
    return ObservationBatch(candidates=[cards[k] for k in sorted(cards, key=lambda k: cards[k].identifiers["skill_path"])],
                            evidence=list(observations.values()))
