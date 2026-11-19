"""Eligibility and complete-data groups, frozen before output limits."""
from __future__ import annotations

from .contracts import ComparisonGroup, Policy, RunState
from .scoring import github_components, paper_components, paper_venue_context, scoring_reference
from .validation import ContractError, validate_assessment


def omitted_items(state: RunState, policy: Policy) -> dict[str, str]:
    omitted = state.request.preferences.get("not_applicable_items", {})
    if not isinstance(omitted, dict) or any(key not in policy.assessment_items[state.request.skill]
            or not isinstance(reason, str) or not reason.strip() for key, reason in omitted.items()):
        raise ContractError("RequestContract.preferences.not_applicable_items", "requires configured item IDs and nonempty contract-wide reasons")
    if len(omitted) == len(policy.assessment_items[state.request.skill]):
        raise ContractError("RequestContract.preferences.not_applicable_items", "cannot omit every assessment item")
    return dict(omitted)


def eligibility(state: RunState, cid: str, policy: Policy) -> str:
    expected = {"skill-finding": "skill", "tool-finding": "tool", "paper-finding": "paper"}[state.request.skill]
    if state.candidates[cid].kind != expected:
        return "discovery"
    assessment = state.assessments.get(cid)
    if assessment is None:
        return "pending"
    validate_assessment(assessment.to_dict(), state.request, state.snapshot_id, state.evidence, state.candidates[cid])
    if any(item.result == "fail" for item in assessment.hard_constraints.values()):
        return "excluded"
    if any(item.result == "pending" for item in assessment.hard_constraints.values()):
        return "pending"
    relevance = assessment.relevance
    if relevance.status != "verified":
        return "pending"
    return "eligible" if relevance.level in policy.ranking.formal_relevance else "excluded"


def build_group(state: RunState, policy: Policy, *, venue_context: dict | None = None) -> ComparisonGroup:
    omitted = omitted_items(state, policy)
    scoring_reference(state)
    if state.request.skill == "paper-finding":
        return _paper_group(state, policy, omitted, venue_context if venue_context is not None else paper_venue_context(state))
    members, reasons = [], {}
    for cid in sorted(state.candidates):
        status = eligibility(state, cid, policy)
        if status != "eligible":
            reasons[cid] = status
            continue
        facts = github_components(state, cid, policy, omitted)
        missing = [name for name in policy.github.required_group_metrics if facts.get(name) is None]
        if missing:
            reasons[cid] = "Missing required dimensions: " + ", ".join(missing)
        else:
            members.append(cid)
    missing_watch = [cid for cid in members if github_components(state, cid, policy, omitted)["watchers"] is None]
    if missing_watch:
        reasons["watch"] = "Removed for entire frozen group; missing: " + ", ".join(missing_watch)
    return ComparisonGroup(members, "github", dict(policy.weights[state.request.skill]),
                           state.snapshot_id, reasons, omitted)


def _paper_group(state: RunState, policy: Policy, omitted: dict[str, str], venue_context: dict) -> ComparisonGroup:
    g0, facts, reasons = [], {}, {}
    for cid in sorted(state.candidates):
        status = eligibility(state, cid, policy)
        if status != "eligible":
            reasons[cid] = status
            continue
        facts[cid] = paper_components(state, cid, policy, omitted, venue_context=venue_context)
        if facts[cid]["L"] is None:
            reasons[cid] = "Missing complete L or full-text method evidence"
        else:
            g0.append(cid)
    members = [cid for cid in g0 if facts[cid]["I"] is not None]
    if not members:
        reasons["I"] = "No valid I in G0; citations and venue excluded for entire frozen group"
        return ComparisonGroup(g0, "landing_only", dict(policy.paper.landing_only_weights), state.snapshot_id, reasons, omitted)
    for cid in g0:
        if cid not in members:
            reasons[cid] = "Missing valid I; outside frozen G"
    missing_venue = [cid for cid in members if facts[cid]["V"] is None]
    if missing_venue:
        reasons["V"] = "Removed for entire frozen group; missing: " + ", ".join(missing_venue)
    return ComparisonGroup(members, "no_venue" if missing_venue else "full_paper",
        dict(policy.paper.no_venue_weights if missing_venue else policy.weights["paper-finding"]),
        state.snapshot_id, reasons, omitted)
