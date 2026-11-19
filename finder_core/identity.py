"""Conservative work/version merging; titles and citation totals are not identities."""
from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path

from .contracts import Candidate, ObservationBatch, RunState
from .evidence import IDENTITY_FIELDS, _supports_subject, canonical_json, checked_source, content_hash, metric_name, validate_batch_evidence
from .validation import ContractError, load_policy


def snapshot_id(state: RunState) -> str:
    """Bind evaluations to the full request and facts, excluding usage/judgments."""
    return "snapshot:" + content_hash({"request": state.request.to_dict(),
        "candidates": {k: v.to_dict() for k, v in state.candidates.items()},
        "evidence": {k: v.to_dict() for k, v in state.evidence.items()}})


def _merge_metrics(candidates: list[Candidate]):
    observations = {}
    for candidate in candidates:
        for key, metric in candidate.metrics.items():
            name = metric_name(key, metric)
            # A later observation replaces the same provider/subject/scope only.
            slot = (name, metric.provider, metric.subject_id, canonical_json(metric.scope))
            observations.setdefault(slot, {})[canonical_json(metric.to_dict())] = metric
    grouped = {}
    for slot, records in observations.items():
        newest = max(m.fetched_at for m in records.values())
        for metric in records.values():
            if metric.fetched_at == newest:
                grouped.setdefault(slot[0], []).append(metric)
    result = {}
    for name, metrics in sorted(grouped.items()):
        for metric in sorted(metrics, key=lambda m: canonical_json(m.to_dict())):
            key = name if len(metrics) == 1 else f"{metric.provider}.{name}"
            if key in result:
                previous = result.pop(key)
                result[f"{key}@{content_hash(previous.to_dict())[:16]}"] = previous
                result[f"{key}@{content_hash(metric.to_dict())[:16]}"] = metric
            elif any(k.startswith(key + "@") for k in result):
                result[f"{key}@{content_hash(metric.to_dict())[:16]}"] = metric
            else:
                result[key] = metric
    return dict(sorted(result.items()))


def _identifier_sources(card: Candidate, key: str) -> set[str]:
    """Only internal provenance may authenticate an original suffixed identity."""
    encoded = card.identifiers.get("identifier_source:" + key)
    if encoded is None:
        return {card.candidate_id} if "@" not in key else set()
    try:
        sources = json.loads(encoded)
    except (ValueError, TypeError):
        return set()
    if not isinstance(sources, list) or any(not isinstance(source, str) for source in sources):
        return set()
    return {source for source in sources if card.identifiers.get("source_id:" + source) == source}


def _merge_cards(cards: list[Candidate], canonical_id: str) -> Candidate:
    cards = sorted(cards, key=lambda c: (c.candidate_id, canonical_json(c.to_dict())))
    kinds = {c.kind for c in cards}
    if len(kinds) != 1:
        raise ContractError("ObservationBatch.identity_relations", "different candidate kinds cannot be merged")
    identifiers, urls, identifier_sources = {}, {}, {}
    aliases, versions, discoveries, relations = set(), set(), set(), {}
    for card in cards:
        for key, value in card.identifiers.items():
            if key.startswith("identifier_source:"):
                continue
            original_key = key
            if key in identifiers and identifiers[key] != value:
                key = f"{key}@{card.candidate_id}"
            identifiers[key] = value
            if original_key.split("@", 1)[0] in IDENTITY_FIELDS:
                identifier_sources.setdefault(key, set()).update(_identifier_sources(card, original_key))
        identifiers[f"source_id:{card.candidate_id}"] = card.candidate_id
        for key, value in card.urls.items():
            if key in urls and urls[key] != value:
                urls[f"{key}@{card.candidate_id}"] = value
            else:
                urls[key] = value
        aliases.update(card.aliases)
        aliases.add(card.candidate_id)
        versions.update(card.versions)
        discoveries.update(card.discovery_evidence_ids)
        for relation in card.relations:
            relations[canonical_json(relation.to_dict())] = relation
    for key, sources in identifier_sources.items():
        identifiers["identifier_source:" + key] = canonical_json(sorted(sources))
    aliases.discard(canonical_id)
    return Candidate(canonical_id, cards[0].kind, dict(sorted(identifiers.items())), sorted(aliases),
        dict(sorted(urls.items())), sorted(versions), [relations[k] for k in sorted(relations)],
        _merge_metrics(cards), sorted(discoveries))


def _verified_identifiers(card, evidence):
    refs = set(card.discovery_evidence_ids)
    for metric in card.metrics.values():
        refs.update(metric.evidence_ids)
    def verified_subject(source):
        return any(eid in evidence and checked_source(evidence[eid]) and
                   _supports_subject(evidence[eid], {source}) for eid in refs)

    if card.kind == "skill":
        if not verified_subject(card.candidate_id):
            return []
        repository = card.identifiers.get("github_repository_id")
        path = card.identifiers.get("skill_path", card.identifiers.get("path", ""))
        path = posixpath.normpath(path.replace("\\", "/"))
        if not repository or path in {".", ".."} or path.startswith(("/", "../")):
            return []
        # GitHub paths are case-sensitive; SHA describes a version of this skill.
        return [(card.kind, "github_skill", repository, path)]
    result = []
    for key, value in card.identifiers.items():
        logical_key = key.split("@", 1)[0]
        if logical_key not in IDENTITY_FIELDS or not any(verified_subject(source) for source in _identifier_sources(card, key)):
            continue
        key = logical_key
        if card.kind == "tool" and key != "github_repository_id":
            continue
        if card.kind == "paper" and key == "github_repository_id":
            continue
        if key == "doi":
            value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value.strip(), flags=re.I).lower()
        elif key == "arxiv":
            value = re.sub(r"v\d+$", "", re.sub(r"^https?://arxiv\.org/abs/", "", value.strip(), flags=re.I))
        elif key not in {"github_repository_id", "openalex", "semantic_scholar"}:
            continue
        value = value.strip()
        if not value:
            continue
        result.append((card.kind, key, value))
    return result


def merge_observations(state: RunState, batch: ObservationBatch) -> RunState:
    """Return a new state; reject invalid batches without mutating caller state."""
    state = RunState.from_dict(state.to_dict())
    batch = ObservationBatch.from_dict(batch.to_dict())
    validate_batch_evidence(batch, state.evidence)
    before = snapshot_id(state)
    state.evidence.update({e.evidence_id: e for e in batch.evidence})
    state.evidence = dict(sorted(state.evidence.items()))
    cards = list(state.candidates.values()) + batch.candidates
    parents = {c.candidate_id: c.candidate_id for c in cards}
    sources = {}
    for card in cards:
        for key, value in card.identifiers.items():
            if key == f"source_id:{value}":
                sources[value] = card.candidate_id

    def find(cid):
        cid = sources.get(cid, cid)
        if cid not in parents:
            raise ContractError("ObservationBatch.identity_relations", "references unknown candidate identifiers")
        while parents[cid] != cid:
            cid = parents[cid]
        return cid

    def union(a, b):
        a, b = find(a), find(b)
        parents[max(a, b)] = min(a, b)

    # IDs recorded during a previous merge resolve to their retained canonical card.
    for card in cards:
        if card.candidate_id in sources:
            union(card.candidate_id, sources[card.candidate_id])
    identities = {}
    for card in sorted(cards, key=lambda c: c.candidate_id):
        for key in _verified_identifiers(card, state.evidence):
            if key in identities:
                union(card.candidate_id, identities[key])
            identities[key] = card.candidate_id
    all_relations = list(batch.identity_relations)
    for card in cards:
        all_relations.extend(card.relations)
    for relation in all_relations:
        find(relation.source_id)
        find(relation.target_id)
        if relation.status == "verified" and relation.relation in {"same_work", "version_of", "moved_to"}:
            union(relation.source_id, relation.target_id)
    groups = {}
    for card in cards:
        groups.setdefault(find(card.candidate_id), []).append(card)
    state.candidates = {cid: _merge_cards(group, cid) for cid, group in sorted(groups.items())}
    for relation in all_relations:
        card = state.candidates[find(relation.source_id)]
        if relation.to_dict() not in [r.to_dict() for r in card.relations]:
            card.relations.append(relation)
        card.relations.sort(key=lambda r: canonical_json(r.to_dict()))
    events = {event.event_id: event for event in state.host_search_events}
    for event in batch.host_search_events:
        if event.event_id in events and event.to_dict() != events[event.event_id].to_dict():
            raise ContractError("ObservationBatch.host_search_events", "event identifier cannot be reassigned")
        events[event.event_id] = event
    policy = load_policy(Path(__file__).parent / "resources/policy-v1.json")
    if len(events) > policy.budgets.host_search:
        raise ContractError("ObservationBatch.host_search_events", "host_search budget exceeded")
    state.host_search_events = [events[k] for k in sorted(events)]
    limits = {limit.provider: limit for limit in state.limits}
    for limit in batch.provider_limits:
        old = limits.get(limit.provider)
        # No producer can silently relax a previously observed live limit.
        if old is None or old.remaining is None or (limit.remaining is not None and limit.remaining < old.remaining):
            limits[limit.provider] = limit
    state.limits = [limits[k] for k in sorted(limits)]
    after = snapshot_id(state)
    if after != before:
        state.assessments = {}
        state.invalidated = True
        state.invalidation_reason = "Facts or identities changed; submit assessments for the new snapshot"
    state.snapshot_id = after
    return state
