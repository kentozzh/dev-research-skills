"""Evidence reference checks and deterministic, source-preserving metric lookup."""
from __future__ import annotations

import hashlib
import json
import posixpath
from urllib.parse import urlsplit

from .contracts import Candidate, Evidence, Metric, ObservationBatch, RunState
from .validation import ContractError, _safe_url

IDENTITY_FIELDS = {"doi", "arxiv", "github_repository_id", "openalex", "semantic_scholar"}


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def content_hash(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def metric_name(key: str, metric: Metric) -> str:
    """Qualified keys are provider.name, with @digest for same-provider conflicts."""
    prefix = metric.provider + "."
    return (key[len(prefix):] if key.startswith(prefix) else key).split("@", 1)[0]


def get_metric(candidate: Candidate, name: str, provider: str | None = None) -> Metric | None:
    """Return one unambiguous observation, preserving its status and provenance.

    No provider is selected implicitly when several observations match. Callers
    must check status and scope; this helper never turns missing data into zero.
    """
    matches = [m for key, m in candidate.metrics.items()
               if name in {metric_name(key, m), m.provider + "." + metric_name(key, m)}
               and (provider is None or m.provider == provider)]
    return matches[0] if len(matches) == 1 else None


def _github_count_source(item: Evidence, card: Candidate, metric: Metric) -> bool:
    if item.status != "verified" or item.source_category not in {"api", "official", "repository"}:
        return False
    repo = card.identifiers.get("github_repository_id")
    name = card.identifiers.get("full_name")
    repository_url = urlsplit(card.urls.get("repository", ""))
    if not name and repository_url.hostname in {"github.com", "www.github.com"}:
        name = repository_url.path.strip("/")
    raw = item.source_object
    if "stargazers_count" in raw:
        if raw["stargazers_count"] != metric.value or (repo and "id" in raw and str(raw["id"]) != repo):
            return False
    if "repository_id" in item.scope and str(item.scope["repository_id"]) != repo:
        return False
    url = urlsplit(item.source_url)
    parts = url.path.strip("/").split("/")
    if url.hostname == "api.github.com":
        if parts[0] == "search":
            return bool(repo and str(raw.get("id")) == repo)
        if parts[0] == "repositories":
            return bool(repo and parts[1:2] == [repo])
        if parts[0] != "repos":
            return False
        parts = parts[1:]
    elif url.hostname not in {"github.com", "www.github.com"}:
        return False
    if len(parts) < 2:
        return False
    if name:
        return "/".join(parts[:2]).casefold() == name.casefold()
    return bool(repo and (str(item.scope.get("repository_id")) == repo
                          or item.subject_id in {repo, "github:" + repo}))


def repository_stars(state: RunState, card: Candidate) -> Metric | None:
    """Use the same current repository observation for all of its skills."""
    repo = card.identifiers.get("github_repository_id")
    if card.kind == "skill" and not repo:
        return None
    sources = [card] if not repo else [c for c in state.candidates.values()
        if c.kind in {"tool", "skill"} and c.identifiers.get("github_repository_id") == repo]
    observations = [(source, m) for source in sources for key, m in source.metrics.items()
                    if metric_name(key, m) == "stars"]
    if not observations:
        return None
    newest = max(m.fetched_at for _, m in observations)
    current = [(source, m) for source, m in observations if m.fetched_at == newest]
    selected = current[0][1]
    for source, metric in current:
        if (metric.status != "verified" or metric.unit != "count" or type(metric.value) is not int
                or metric.value < 0 or metric.value != selected.value):
            return None
        scoped_repo = metric.scope.get("repository_id")
        if scoped_repo is not None and str(scoped_repo) != repo:
            return None
        subjects = {repo, f"github:{repo}"} if repo else set()
        if name := source.identifiers.get("full_name"):
            subjects.add("github:" + name)
        if source.kind == "tool" or scoped_repo is not None:
            subjects.update((source.candidate_id, *source.aliases))
        if (metric.subject_id not in subjects or metric.scope.get("level", "repository") != "repository"
                or "path" in metric.scope):
            return None
        if not any(eid in state.evidence and _github_count_source(state.evidence[eid], source, metric)
                   for eid in metric.evidence_ids):
            return None
    return selected


def checked_source(evidence: Evidence) -> bool:
    return evidence.status == "verified" and evidence.source_category not in {"host_search", "agent"}


def candidate_subject_ids(candidate: Candidate) -> set[str]:
    """Retained identities and explicit repository ownership support one card.

    A repository source may support its concrete skills; a sibling skill source
    does not become shared merely because both skills belong to one repository.
    """
    subjects = {candidate.candidate_id, *candidate.aliases}
    for key, value in candidate.identifiers.items():
        if key.split("@", 1)[0] in IDENTITY_FIELDS or key == "anthology":
            subjects.add(value)
        elif key == "source_id:" + value:
            subjects.add(value)
    if candidate.kind in {"skill", "tool"}:
        repository = candidate.identifiers.get("github_repository_id")
        if repository:
            subjects.update({repository, "github:" + repository})
        full_name = candidate.identifiers.get("full_name")
        if full_name:
            subjects.add("github:" + full_name)
    return subjects


def _supports_subject(item: Evidence, subject_ids: set[str]) -> bool:
    linked = item.scope.get("subject_ids", [])
    return item.subject_id in subject_ids or (isinstance(linked, list) and any(subject in linked for subject in subject_ids))


def supports_assessment_subject(item: Evidence, candidate: Candidate, evidence: dict[str, Evidence]) -> bool:
    """Apply concrete-skill path scope before sharing repository documents."""
    if not _supports_subject(item, candidate_subject_ids(candidate)):
        return False
    if candidate.kind != "skill":
        return True
    repository = candidate.identifiers.get("github_repository_id")
    if "repository_id" in item.scope and str(item.scope["repository_id"]) != repository:
        return False
    observed = item.scope.get("path")
    if observed is None:
        return True
    if not isinstance(observed, str) or not observed or observed.startswith(("/", "\\")) or ":" in observed:
        return False
    observed = posixpath.normpath(observed.replace("\\", "/"))
    if observed in {".", ".."} or observed.startswith("../"):
        return False
    # Root repository documents apply across its skills. More specific sources
    # must be inside this skill, explicitly linked, or referenced as shared.
    if ("/" not in observed and observed != "SKILL.md"
            and item.scope.get("level") not in {"directory", "skill_path", "tree"}):
        return True
    from .skill_inventory import candidate_skill_path
    skill_path = candidate_skill_path(candidate)
    if not skill_path:
        return False
    directory = posixpath.dirname(skill_path)
    if not directory or observed == skill_path or observed == directory or observed.startswith(directory + "/"):
        return True
    direct = {candidate.candidate_id, *candidate.aliases}
    linked = item.scope.get("subject_ids", [])
    if isinstance(linked, list) and any(subject in linked for subject in direct):
        return True
    for source in evidence.values():
        if (checked_source(source) and source.subject_id in direct and source.scope.get("path") == skill_path
                and str(source.scope.get("repository_id", repository)) == repository):
            refs = source.source_object.get("references", [])
            if isinstance(refs, list) and any(isinstance(ref, dict) and ref.get("kind") == "shared"
                    and ref.get("path") == observed for ref in refs):
                return True
    return False


def require_references(ids: list[str], evidence: dict[str, Evidence], path: str, *, verified=False) -> None:
    if set(ids) - evidence.keys():
        raise ContractError(path, "references unknown evidence identifiers")
    if verified and (not ids or any(not checked_source(evidence[eid]) for eid in ids)):
        raise ContractError(path, "verified claims need checked source evidence, not discovery summaries")


def validate_batch_evidence(batch: ObservationBatch, existing: dict[str, Evidence] | None = None) -> None:
    """Cross-record validation shared by imports and merges with existing facts."""
    evidence = dict(existing or {})
    seen = set()
    for item in batch.evidence:
        if item.evidence_id in seen:
            raise ContractError("ObservationBatch.evidence", "duplicate evidence identifiers")
        seen.add(item.evidence_id)
        if item.evidence_id in evidence and item.to_dict() != evidence[item.evidence_id].to_dict():
            raise ContractError("ObservationBatch.evidence", "an evidence identifier cannot be reassigned")
        evidence[item.evidence_id] = item
    candidate_ids = [c.candidate_id for c in batch.candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ContractError("ObservationBatch.candidates", "duplicate candidate identifiers")
    for candidate in batch.candidates:
        if any(key.startswith(("source_id:", "identifier_source:")) or
               ("@" in key and key.split("@", 1)[0] in IDENTITY_FIELDS)
               for key in candidate.identifiers):
            raise ContractError("ObservationBatch.candidates.identifiers", "identity provenance identifiers are reserved for run storage")
        for key, url in candidate.urls.items():
            _safe_url(url, f"ObservationBatch.candidates.urls.{key}")
        require_references(candidate.discovery_evidence_ids, evidence, "ObservationBatch.candidates.discovery_evidence_ids")
        for name, metric in candidate.metrics.items():
            path = f"ObservationBatch.candidates.metrics.{name}"
            require_references(metric.evidence_ids, evidence, path, verified=metric.status == "verified")
            if metric.status == "verified" and any(not _supports_subject(evidence[eid], {metric.subject_id, candidate.candidate_id}) for eid in metric.evidence_ids):
                raise ContractError(path, "evidence must identify the observed subject")
            if metric.status == "verified" and metric_name(name, metric) in {"official_implementation", "publication_track"}:
                if any(evidence[eid].source_category not in {"api", "official", "repository", "paper"} for eid in metric.evidence_ids):
                    raise ContractError(path, "official claims require a checked primary source")
        for relation in candidate.relations:
            require_references(relation.evidence_ids, evidence, "ObservationBatch.candidates.relations", verified=relation.status == "verified")
            if relation.status == "verified" and any(not _supports_subject(evidence[eid], {relation.source_id, relation.target_id}) for eid in relation.evidence_ids):
                raise ContractError("ObservationBatch.candidates.relations", "evidence must identify a related subject")
    for relation in batch.identity_relations:
        require_references(relation.evidence_ids, evidence, "ObservationBatch.identity_relations", verified=relation.status == "verified")
        if relation.status == "verified" and any(not _supports_subject(evidence[eid], {relation.source_id, relation.target_id}) for eid in relation.evidence_ids):
            raise ContractError("ObservationBatch.identity_relations", "evidence must identify a related subject")
