"""Reproducible frozen-group ranking with complete-group sensitivity."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from .contracts import ComparisonGroup, Policy, RankedReport, RunState
from .evidence import content_hash
from .groups import build_group, eligibility
from .scoring import (github_components, metric_value, paper_components, paper_metric, paper_venue_context,
                      score_paper, score_popularity, scoring_reference, weighted_score)
from .venues import resolve_venue
from .validation import ContractError


def rank_candidates(state: RunState, group: ComparisonGroup, policy: Policy) -> RankedReport:
    paper = state.request.skill == "paper-finding"
    venue_context = paper_venue_context(state) if paper else None
    expected = build_group(state, policy, venue_context=venue_context)
    if group.frozen_snapshot_id != state.snapshot_id or group.to_dict() != expected.to_dict():
        raise ContractError("ComparisonGroup", "frozen group does not match the current snapshot and policy")
    quality_key, scale_key = ("L", "citations") if paper else ("U", "stars")
    influence_key = "I" if paper else "P"
    components = {cid: paper_components(state, cid, policy, group.omitted_items, venue_context=venue_context)
                      if paper else github_components(state, cid, policy, group.omitted_items)
                  for cid in state.candidates if eligibility(state, cid, policy) == "eligible"}
    include_watch = "watch" not in group.missing_reasons
    popularity_weights = {} if paper else (policy.github.popularity_weights if include_watch else policy.github.without_watch_weights)
    if not paper:
        for cid in group.member_ids:
            row = components[cid]
            row["P"] = score_popularity(row["stars"], row["forks"], row["watchers"], include_watch, policy=policy)
    def score(cid, weights):
        row = components[cid]
        return min(policy.paper.maximum_index, weighted_score(row, weights) + row["award_bonus"]) if paper else weighted_score(row, weights)
    scores = {cid: score_paper(components[cid]["L"], components[cid]["I"], components[cid]["V"],
                             components[cid]["award_bonus"], group) if paper else score(cid, group.effective_weights)
              for cid in group.member_ids}

    def relevance(cid):
        assessment = state.assessments.get(cid)
        return int(assessment.relevance.level[1:]) if assessment and assessment.relevance.level else -1

    def ordering(values):
        return sorted(group.member_ids, key=lambda cid: (-relevance(cid), -values[cid],
                      -components[cid][quality_key],
                      -(components[cid][scale_key] if components[cid][scale_key] is not None else -1), cid))

    def apply_limits(ids):
        chosen, siblings, repository_counts = [], [], Counter()
        for cid in ids:
            card = state.candidates[cid]
            repo = card.identifiers.get("github_repository_id", cid)
            if card.kind == "skill" and repository_counts[repo] >= policy.capacity.skills_per_repository:
                siblings.append(cid)
                continue
            if len(chosen) < policy.capacity.formal:
                chosen.append(cid)
                repository_counts[repo] += 1
        return chosen, siblings[:policy.capacity.supplementary]

    formal, siblings = apply_limits(ordering(scores))
    pending, excluded, qualitative, discovery = [], [], [], []
    for cid in state.candidates:
        status = eligibility(state, cid, policy)
        if status == "eligible" and cid not in group.member_ids:
            qualitative.append(cid)
        elif status == "pending":
            pending.append(cid)
        elif status == "excluded":
            excluded.append(cid)
        elif status == "discovery":
            discovery.append(cid)

    def verified_ratio(cid):
        card = state.candidates[cid]
        if paper:
            assessment = state.assessments[cid]
            facts = {"identity": bool(card.identifiers) and bool(card.discovery_evidence_ids),
                     "publication_status": paper_metric(state, cid, "publication_status") is not None,
                     "citations": any(paper_metric(state, cid, "citations", provider) is not None for provider in ("openalex", "semantic_scholar")),
                     "method": assessment.reading_depth == "full_text" and assessment.landing["task_transfer"].status == "verified",
                     "implementation_resources": all(assessment.landing[key].status == "verified" for key in ("artifacts", "resources"))}
            names = policy.qualitative_fact_fields["paper"]
            return sum(bool(facts.get(name)) for name in names) / len(names) if names else 0
        facts = {"identity": bool(card.identifiers.get("github_repository_id")) and bool(card.discovery_evidence_ids or any(m.status == "verified" for m in card.metrics.values())),
                 "license": metric_value(card, "license") is not None,
                 "stars": components[cid]["stars"] is not None, "forks": components[cid]["forks"] is not None,
                 "updated_at": components[cid]["maintenance_days"] is not None}
        names = policy.qualitative_fact_fields["github"]
        return sum(bool(facts.get(name)) for name in names) / len(names) if names else 0

    qualitative.sort(key=lambda cid: (-relevance(cid), components[cid][quality_key] is None,
        -(components[cid][quality_key] if components[cid][quality_key] is not None else -1), -verified_ratio(cid), cid))
    qualitative = qualitative[:policy.capacity.supplementary if group.member_ids else policy.ranking.empty_group_qualitative_limit]
    # Prefer useful incomplete alternatives, then spend only the remaining
    # supplementary slots on already-scored siblings in their formal order.
    if group.member_ids:
        siblings = siblings[:max(0, policy.capacity.supplementary - len(qualitative))]
    sensitivity = {"baseline": {"first": formal[0] if formal else None, "top3": formal[:3]}, "first_changed": False}
    if group.member_ids and influence_key in group.effective_weights:
        for label, adjustment in (("lower", -policy.ranking.sensitivity_weight_delta), ("higher", policy.ranking.sensitivity_weight_delta)):
            original = group.effective_weights[influence_key]
            changed = max(0, min(1, original + adjustment))
            if original == 1:
                weights = dict(group.effective_weights)
            else:
                weights = {key: changed if key == influence_key else value * (1-changed)/(1-original)
                           for key, value in group.effective_weights.items()}
            alternate = {cid: score(cid, weights) for cid in group.member_ids}
            order, _ = apply_limits(ordering(alternate))
            sensitivity[label] = {"weights": weights, "scores": alternate, "first": order[0] if order else None, "top3": order[:3]}
            sensitivity["first_changed"] |= order[:1] != formal[:1]
        if sensitivity["first_changed"]:
            sensitivity["explanation"] = "取决于更重视影响力还是采用条件" if paper else "取决于更重视热度还是采用条件"
    else:
        sensitivity["skipped"] = "Landing-only group has no influence dimension" if group.member_ids and paper else "No complete comparison group"
    ordered = ordering(scores)
    close_pairs = [[left, right] for i,left in enumerate(ordered) for right in ordered[i+1:]
                   if relevance(left) == relevance(right) and abs(scores[left]-scores[right]) < policy.ranking.close_score_difference]
    limitations = ["建议指数是工程启发式，不是质量概率或百分比。" if paper else "建议指数是工程启发式，维护信号不代表正确性或安全性。"]
    if not formal:
        limitations.append("暂无可确认符合的候选；完整证据不足时仅列定性或待核实对象。")
    if "watch" in group.missing_reasons:
        limitations.append("冻结比较组统一移除 Watch；Star/Fork 按政策重新归一。")
    if paper and group.mode == "landing_only":
        limitations.append("纯 L 模式：未采用引用和渠道指标；跳过引用敏感性检查。")
    if paper and group.mode == "no_venue":
        limitations.append("冻结比较组统一移除 V；L:I 按政策使用 2:1。")
    if state.limits:
        limitations.extend(item.reason for item in state.limits if item.reason)
    venue_snapshot = _venue_snapshot(state, components, venue_context) if paper else {}
    return RankedReport(group=group if group.member_ids else None, formal=formal, qualitative=qualitative,
        pending=sorted(pending), excluded=sorted(excluded), same_repository_supplementary=siblings,
        scores=scores, sensitivity=sensitivity, limitations=limitations, provenance={
            "run_id": state.run_id, "contract_revision": state.request.contract_revision,
            "snapshot_id": state.snapshot_id, "policy_version": policy.policy_version,
            "policy": policy.to_dict(), "request": state.request.to_dict(),
            "scoring_reference_at": scoring_reference(state).isoformat(),
            "scoring_reference_source": "explicit as_of" if "as_of" in state.request.preferences else "latest observed fact",
            "generated_at": datetime.now(timezone.utc).isoformat(), "report_timezone": policy.report_timezone,
            "components": components, "popularity_weights": dict(popularity_weights),
            "missing_reasons": group.missing_reasons, "omitted_items": group.omitted_items,
            "supplementary_priority": "qualitative_then_same_repository",
            "close_pairs": close_pairs, "discovery_only": sorted(discovery),
            "candidates": {cid:card.to_dict() for cid,card in state.candidates.items()},
            "assessments": {cid:a.to_dict() for cid,a in state.assessments.items()},
            "evidence": {eid:e.to_dict() for eid,e in state.evidence.items()},
            "limits": [limit.to_dict() for limit in state.limits], "request_counts": dict(state.request_counts),
            "host_search_events": [item.to_dict() for item in state.host_search_events],
            "checked_counts": {"candidates": len(state.candidates), "assessed": len(state.assessments), "group": len(group.member_ids)},
            **venue_snapshot,
        })


def _venue_snapshot(state: RunState, components: dict, context: dict) -> dict:
    """Save the exact used mapping facts so reports never reopen mutable config."""
    used = {}
    for cid, row in components.items():
        record = resolve_venue(state.candidates[cid], context["records"], evidence=context["evidence"])
        if record is not None and row["venue_evidence_ids"]:
            used[record.venue_id] = record.to_dict()
    records = [used[key] for key in sorted(used)]
    ids = set()
    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "evidence_ids" or key.endswith("_evidence_ids"):
                    ids.update(item)
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    collect(records)
    evidence = {eid: context["evidence"][eid].to_dict() for eid in sorted(ids)}
    return {"venue_records": records, "venue_evidence": evidence,
            "venue_config_versions": sorted({row["version"] for row in records}),
            "venue_config_hash": content_hash({"records": records, "evidence": evidence})}
