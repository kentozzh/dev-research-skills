"""Provider orchestration; API facts merge through the canonical evidence boundary."""
from __future__ import annotations

from copy import deepcopy
from contextlib import nullcontext
from typing import Mapping, Sequence

from .contracts import Candidate, CohortSummary, Evidence, ObservationBatch, Policy, ProviderBatch, ProviderLimit, RunState
from .identity import merge_observations, snapshot_id
from .evidence import content_hash
from .providers.base import Provider
from .providers.github import GitHubProvider
from .validation import ContractError
from .skill_inventory import candidate_skill_path, extract_skill_candidates, normalize_skill_path, resolve_reference, skill_candidate_id


def validate_venue_statistics(state: RunState, payload: dict) -> dict:
    """Bind a derived cohort artifact to this exact run without importing papers.

    The original calculation preserves its complete manifests, query dates and
    normalized/cumulative windows. Hashes detect altered derived data; this does
    not upgrade the underlying source evidence or recompute scientific claims.
    """
    from .cohort_stats import METHOD
    if state.request.skill != "paper-finding":
        raise ContractError("venue-stats.provenance", "cohort background requires a paper-finding run")
    if not isinstance(payload, dict) or not isinstance(payload.get("provenance"), dict):
        raise ContractError("venue-stats.provenance", "derived artifact provenance unavailable; rerun venue-stats")
    provenance = payload["provenance"]
    expected = {"run_id": state.run_id, "contract_revision": state.request.contract_revision,
        "snapshot_id": state.snapshot_id, "state_hash": content_hash(state.to_dict()),
        "calculation_method": METHOD, "artifact_version": "1"}
    if any(provenance.get(key) != value for key, value in expected.items()):
        raise ContractError("venue-stats.provenance", "run/revision/snapshot/state/method mismatch; rerun venue-stats after current assessments")
    unsigned = deepcopy(payload)
    recorded_hash = unsigned["provenance"].pop("artifact_hash", None)
    if not recorded_hash or recorded_hash != content_hash(unsigned):
        raise ContractError("venue-stats.provenance.artifact_hash", "derived artifact changed; rerun venue-stats")
    summaries = []
    for key in ("annual", "combined"):
        if not isinstance(payload.get(key), list):
            raise ContractError("venue-stats." + key, "requires typed cohort summaries")
        for raw in payload[key]:
            summary = CohortSummary.from_dict(raw)
            if not summary.manifests or summary.calculation_method != METHOD:
                raise ContractError("venue-stats.method", "scoped complete-cohort calculation context unavailable")
            summaries.append(summary)
    scopes = [[manifest.to_dict() for manifest in summary.manifests] for summary in summaries]
    if provenance.get("query_scope_hash") != content_hash(scopes):
        raise ContractError("venue-stats.provenance.query_scope_hash", "cohort/database/query scope changed; rerun venue-stats")
    return deepcopy(payload)


def _skill_slot(card: Candidate) -> str:
    try:
        path = candidate_skill_path(card)
        identity = skill_candidate_id(card.identifiers["github_repository_id"], path) if path else card.candidate_id
    except (ContractError, KeyError):
        identity = card.candidate_id
    return "workflow_deep_skill-finding_" + content_hash(identity)


def merge_with_capacity(state: RunState, batch: ObservationBatch, policy: Policy,
                        *, truncate: bool = False) -> RunState:
    """Count post-identity canonical entities; rejected imports are atomic.

    Provider truncation retains every existing entity (including renamed
    canonical IDs), then selects new canonical IDs in ascending order.
    """
    # Normalize the documented host-import alias at the shared T07 orchestration
    # boundary. Preserve the supplied alias and raw source evidence as provenance.
    batch = deepcopy(batch)
    for card in batch.candidates:
        if card.kind == "skill":
            path = candidate_skill_path(card)
            if path:
                card.identifiers["skill_path"] = path
    merged = merge_observations(state, batch)
    # Identity normalization keeps the strongest per-provider limit, while the
    # workflow also needs every observed coverage/failure explanation. Preserve
    # distinct records; transport reconstructs overlapping live restrictions
    # conservatively, so this cannot reset a quota or shorten a cooldown.
    for limit in [*state.limits, *batch.provider_limits]:
        if limit not in merged.limits:
            merged.limits.append(limit)
    maximum = policy.capacity.paper_initial if state.request.skill == "paper-finding" else policy.capacity.github_initial
    # Skill runs retain repository discovery metadata independently from concrete
    # source-read entities. Each lane remains bounded; no HTTP/host ledger resets.
    def lane(card):
        return "skill" if state.request.skill == "skill-finding" and card.kind == "skill" else "discovery"
    def lane_maximum(group):
        return policy.capacity.github_deep if group == "skill" else maximum
    recorded = {key for key in state.request_counts if key.startswith("workflow_deep_skill-finding_")} if state.request.skill == "skill-finding" else set()
    skill_slots = {_skill_slot(card) for card in merged.candidates.values() if lane(card) == "skill"}
    lanes = {lane(card) for card in merged.candidates.values()}
    if (len(recorded | skill_slots) <= policy.capacity.github_deep and
        all(sum(lane(card) == group for card in merged.candidates.values()) <= lane_maximum(group) for group in lanes)):
        return merged
    if not truncate:
        raise ContractError("ObservationBatch.candidates", "initial canonical candidate capacity exceeded; transaction rejected")
    existing = {cid for cid,card in merged.candidates.items() if cid in state.candidates or
        any(card.identifiers.get("source_id:" + old) == old for old in state.candidates)}
    if any(sum(lane(merged.candidates[cid]) == group for cid in existing) > lane_maximum(group) for group in lanes):
        raise ContractError("RunState.candidates", "existing canonical candidate capacity already exceeded")
    retained = set(existing)
    used_slots = recorded | {_skill_slot(merged.candidates[cid]) for cid in existing if lane(merged.candidates[cid]) == "skill"}
    if len(used_slots) > policy.capacity.github_deep:
        raise ContractError("RunState.candidates", "existing concrete read capacity already exceeded")
    for group in lanes:
        new = sorted(cid for cid in set(merged.candidates) - existing if lane(merged.candidates[cid]) == group)
        available = lane_maximum(group) - sum(lane(merged.candidates[cid]) == group for cid in existing)
        for cid in new:
            if available <= 0:
                break
            if group == "skill":
                slot = _skill_slot(merged.candidates[cid])
                if len(used_slots | {slot}) > policy.capacity.github_deep:
                    continue
                used_slots.add(slot)
            retained.add(cid)
            available -= 1
    merged.candidates = {cid: card for cid,card in merged.candidates.items() if cid in retained}
    # Removed entities may have been endpoints of new provider relations.
    sources = retained | {value for card in merged.candidates.values() for key,value in card.identifiers.items()
                          if key == "source_id:" + value}
    for card in merged.candidates.values():
        card.relations = [relation for relation in card.relations if relation.source_id in sources and relation.target_id in sources]
    merged.limits.append(ProviderLimit("workflow", reason="Initial canonical candidate capacity reached; new provider entities truncated"))
    merged.snapshot_id = snapshot_id(merged)
    if merged.snapshot_id == state.snapshot_id:
        # Temporary admission of later-discarded entities is not a fact change.
        # Keep live usage/limits from this merge, but preserve current judgments.
        merged.assessments = deepcopy(state.assessments)
        merged.invalidated = state.invalidated
        merged.invalidation_reason = state.invalidation_reason
    return merged


def _merge(state: RunState, batch: ProviderBatch, policy: Policy) -> RunState:
    limits = list(batch.provider_limits)
    if batch.partial and not limits:
        limits.append(ProviderLimit("workflow", reason="Provider returned partial results"))
    return merge_with_capacity(state, ObservationBatch(candidates=batch.candidates, evidence=batch.evidence, provider_limits=limits),
                               policy, truncate=True)


def _adopt(target: RunState, source: RunState) -> None:
    # Retain object identity so a failed command can still save completed earlier batches.
    for name in source.__dataclass_fields__:
        setattr(target, name, getattr(source, name))


def _rebind_transport(state: RunState, provider) -> None:
    """Normalization copies must not detach actual transport usage between calls."""
    client = getattr(provider, "client", None)
    if client is None:
        return
    for key,value in state.request_counts.items():
        if key.startswith("workflow_"):
            client.request_counts[key] = value
    state.request_counts = client.request_counts
    # Preserve source/partial limitations as distinct records after merge's
    # per-provider normalization. Live restrictions remain transport-owned.
    for limit in client.provider_limits:
        if limit not in state.limits:
            state.limits.append(limit)
    for limit in getattr(provider, "provider_limits", []):
        if limit not in state.limits:
            state.limits.append(limit)


def _record_outcome(state: RunState, batch: ProviderBatch) -> None:
    observed_valid_response = any(item.status == "verified" and item.scope.get("operation") == "search"
        and item.scope.get("valid_response") is True for item in batch.evidence)
    success = bool(batch.candidates) or observed_valid_response
    key = "workflow_last_successes" if success else "workflow_last_failures"
    state.request_counts[key] = state.request_counts.get(key, 0) + 1
    if not success:
        state.limits.append(ProviderLimit("workflow", reason="No fresh valid response or usable candidate in provider batch"))


def run_discovery(state: RunState, providers: Mapping[str, Provider], policy: Policy) -> RunState:
    state.request_counts["workflow_last_successes"] = state.request_counts["workflow_last_failures"] = 0
    for query in state.request.queries:
        provider = providers.get(query.provider)
        if provider is None:
            state.limits.append(ProviderLimit(query.provider, reason="Provider is not registered"))
            state.request_counts["workflow_last_failures"] += 1
            continue
        try:
            client = getattr(provider, "client", None)
            scoped = state.request.skill == "paper-finding" and client is not None
            route = query.route if query.route in {"recent", "classic"} else "classic"
            if scoped and query.route == "general":
                limit = ProviderLimit("workflow", reason="Paper general query charged to classic initial lane; author explicit recent/classic routes")
                if limit not in state.limits:
                    state.limits.append(limit)
            with client.paper_initial_scope(route) if scoped else nullcontext():
                if state.request.skill != "paper-finding" and isinstance(provider, GitHubProvider):
                    batch = provider.search(query, existing=state.candidates.values())
                else:
                    batch = provider.search(query)
            merged = _merge(state, batch, policy)
        except Exception:
            # Provider messages can contain credentials or response bodies.
            state.limits.append(ProviderLimit(query.provider, reason="Provider discovery failed; no usable batch returned"))
            state.request_counts["workflow_last_failures"] += 1
            _rebind_transport(state, provider)
            continue
        _adopt(state, merged)
        _record_outcome(state, batch)
        _rebind_transport(state, provider)
    return state


def run_enrichment(state: RunState, ids: Sequence[str], providers: Mapping[str, Provider], policy: Policy) -> RunState:
    maximum = policy.capacity.paper_deep if state.request.skill == "paper-finding" else policy.capacity.github_deep
    metadata_only = state.request.skill == "skill-finding"
    if metadata_only:
        maximum = policy.capacity.github_initial
    if len(ids) != len(set(ids)) or len(ids) > maximum or any(cid not in state.candidates for cid in ids):
        raise ContractError("enrich.ids", "requires unique known candidate IDs within the deep-read capacity")
    prefix = "workflow_deep_" + state.request.skill + "_"
    recorded = {key for key in state.request_counts if key.startswith(prefix)}
    requested = {prefix + content_hash(cid) for cid in ids} if not metadata_only else set()
    if not metadata_only and len(recorded | requested) > maximum:
        raise ContractError("enrich.ids", "run-wide deep-read capacity would be exceeded")
    if metadata_only and any(state.candidates[cid].kind != "tool" for cid in ids):
        raise ContractError("enrich.ids", "skill runs enrich repository discovery cards; use inspect-skills for concrete skill reads")
    state.request_counts["workflow_last_successes"] = state.request_counts["workflow_last_failures"] = 0
    grouped = {}
    for cid in ids:
        card = state.candidates[cid]
        compatible = ["github"] if card.kind in {"tool", "skill"} else [name for name,keys in (
            ("arxiv", {"arxiv"}), ("openalex", {"openalex", "doi", "arxiv"}),
            ("semantic_scholar", {"semantic_scholar", "doi", "arxiv"}))
            if name in providers and keys.intersection(card.identifiers)]
        if not compatible or any(name not in providers for name in compatible):
            state.limits.append(ProviderLimit("unknown", reason="No compatible registered provider for explicit identity"))
            state.request_counts["workflow_last_failures"] += 1
            continue
        for name in compatible:
            grouped.setdefault(name, []).append(card)
    for name, cards in grouped.items():
        if not metadata_only:
            for card in cards:
                state.request_counts[prefix + content_hash(card.candidate_id)] = 1
        try:
            batch = providers[name].enrich(cards)
            merged = _merge(state, batch, policy)
        except Exception:
            state.limits.append(ProviderLimit(name, reason="Provider enrichment failed; no usable batch returned"))
            state.request_counts["workflow_last_failures"] += 1
            _rebind_transport(state, providers[name])
            continue
        _adopt(state, merged)
        _record_outcome(state, batch)
        _rebind_transport(state, providers[name])
    return state


def run_skill_inventory(state: RunState, ids: Sequence[str], providers: Mapping[str, Provider], policy: Policy) -> RunState:
    """Persist bounded tree metadata as discovery clues, without reading files."""
    if (state.request.skill != "skill-finding" or not isinstance(ids, list) or
        len(ids) > policy.capacity.github_initial or len(ids) != len(set(ids)) or
        any(not isinstance(cid, str) or cid not in state.candidates or state.candidates[cid].kind != "tool" or
            not state.candidates[cid].identifiers.get("full_name") for cid in ids)):
        raise ContractError("inventory-skills.ids", "requires unique known repository discovery IDs within capacity")
    state.request_counts["workflow_last_successes"] = state.request_counts["workflow_last_failures"] = 0
    provider = providers.get("github")
    if provider is None:
        state.limits.append(ProviderLimit("github", reason="Provider is not registered"))
        state.request_counts["workflow_last_failures"] += 1
        return state
    for cid in ids:
        card = state.candidates[cid]
        start_evidence, start_limits = len(provider.evidence), len(provider.provider_limits)
        complete = False
        limits = []
        try:
            tree = provider.list_tree(card.identifiers["full_name"], card.identifiers.get("default_branch", "HEAD"))
            complete = not tree.truncated
            if tree.truncated:
                limits.append(ProviderLimit("workflow", reason="Skill path inventory incomplete; file entries are discovery clues only"))
        except Exception:
            limits.append(ProviderLimit("github", reason="Skill path inventory unavailable"))
        evidence = list({e.evidence_id:e for e in provider.evidence[start_evidence:]}.values())
        _adopt(state, merge_with_capacity(state, ObservationBatch(evidence=evidence,
            provider_limits=provider.provider_limits[start_limits:] + limits), policy))
        key = "workflow_last_successes" if complete or evidence else "workflow_last_failures"
        state.request_counts[key] = state.request_counts.get(key, 0) + 1
    return state


def run_skill_inspection(state: RunState, selections: Sequence[dict], providers: Mapping[str, Provider], policy: Policy) -> RunState:
    """Read explicit SKILL.md selections and requested repository references only.

    A concrete identity spends one of twelve run-wide deep slots before its
    network read, including failed reads. Re-reading its version shares the slot.
    Reference files use the same provider and HTTP budget and are never executed.
    """
    if state.request.skill != "skill-finding" or not isinstance(selections, list):
        raise ContractError("inspect-skills.input", "requires a skill-finding run and an array of selections")
    planned, seen = [], set()
    prefix = "workflow_deep_skill-finding_"
    for item in selections:
        if not isinstance(item, dict) or set(item) - {"repository_id", "path", "ref", "references"}:
            raise ContractError("inspect-skills.input", "selection requires repository_id, path and optional ref/references")
        cid = item.get("repository_id")
        if not isinstance(cid, str) or cid not in state.candidates or state.candidates[cid].kind != "tool":
            raise ContractError("inspect-skills.repository_id", "requires a known repository discovery card")
        repo = state.candidates[cid]
        if not repo.identifiers.get("github_repository_id") or not repo.identifiers.get("full_name"):
            raise ContractError("inspect-skills.repository_id", "repository needs immutable ID and full_name; enrich metadata first")
        path = normalize_skill_path(item.get("path"))
        ref = item.get("ref", repo.identifiers.get("default_branch", "HEAD"))
        references = item.get("references", [])
        if not isinstance(ref, str) or not ref.strip() or not isinstance(references, list) or any(not isinstance(r, str) or not r for r in references):
            raise ContractError("inspect-skills.input", "ref must be nonempty and references must be an array of nonempty strings")
        identity = skill_candidate_id(repo.identifiers["github_repository_id"], path)
        if identity in seen:
            raise ContractError("inspect-skills.input", "requires unique concrete skill paths")
        seen.add(identity)
        planned.append((repo, path, ref, references, identity))
    recorded = {key for key in state.request_counts if key.startswith(prefix)}
    for card in state.candidates.values():
        if card.kind == "skill":
            recorded.add(_skill_slot(card))
    requested = {prefix + content_hash(item[-1]) for item in planned}
    if len(recorded | requested) > policy.capacity.github_deep:
        raise ContractError("inspect-skills.input", "run-wide concrete skill deep-read capacity would be exceeded")
    state.request_counts["workflow_last_successes"] = state.request_counts["workflow_last_failures"] = 0
    provider = providers.get("github")
    if provider is None:
        state.limits.append(ProviderLimit("github", reason="Provider is not registered"))
        state.request_counts["workflow_last_failures"] += 1
        return state
    resolved = {}
    for repo, path, ref, references, identity in planned:
        state.request_counts[prefix + content_hash(identity)] = 1
        start_evidence, start_limits = len(provider.evidence), len(provider.provider_limits)
        batch = ObservationBatch()
        try:
            name = repo.identifiers["full_name"]
            key = (name, ref)
            if key not in resolved:
                resolved[key] = provider.resolve_ref(name, ref)
            sha = resolved[key]
            read_ref = sha or ref
            doc = provider.read_file(name, path, read_ref)
            # Build a source card without storage-owned identity provenance.
            source_repo = Candidate(repo.candidate_id, "tool", {key: value for key, value in repo.identifiers.items()
                if not key.startswith(("source_id:", "identifier_source:")) and "@" not in key}, metrics=deepcopy(repo.metrics))
            source_repo.identifiers.pop("commit_sha", None)
            if sha:
                source_repo.identifiers["commit_sha"] = sha
            batch = extract_skill_candidates(source_repo, [doc])
            # Every discovered reference remains a source-scoped fact, even when
            # external, shared, missing or rejected at a repository boundary.
            discovered = list(batch.evidence[0].source_object["references"]) if batch.evidence else []
            for target in references:
                record = resolve_reference(path, target)
                if record not in discovered:
                    discovered.append(record)
                if record["kind"] in {"skill", "shared"} and record["path"] != path:
                    provider.read_file(name, record["path"], read_ref)
            for record in discovered:
                scope = {"repository_id": repo.identifiers["github_repository_id"], "path": path,
                         "ref": read_ref, "reference_kind": record["kind"]}
                data = {"reference": record, "action": "read-only; external/local references require separate review"}
                eid = "skill-reference:" + content_hash({"identity": identity, "scope": scope, "data": data, "at": doc.fetched_at.isoformat()})
                batch.evidence.append(Evidence(eid, doc.source_url, identity, doc.fetched_at, scope,
                    "Reference discovered; no installation or execution", "repository", "verified", "source path classification", data))
        except Exception:
            # Preserve successful preceding reads and actual provider limitations.
            state.limits.append(ProviderLimit("github", reason="Skill inspection incomplete; no candidate content executed"))
        batch.evidence.extend(provider.evidence[start_evidence:])
        batch.evidence = list({item.evidence_id: item for item in batch.evidence}.values())
        batch.provider_limits.extend(provider.provider_limits[start_limits:])
        # Existing repository metric evidence is resolved against canonical state.
        merged = merge_with_capacity(state, batch, policy)
        _adopt(state, merged)
        _record_outcome(state, ProviderBatch(candidates=batch.candidates, evidence=batch.evidence))
    return state
