"""Transparent policy-driven arithmetic; unknown values never become zero."""
from __future__ import annotations

import math
import posixpath
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlsplit

from . import venues
from .contracts import Candidate, ComparisonGroup, Policy, RunState
from .evidence import get_metric
from .skill_inventory import candidate_skill_path
from .validation import ContractError, load_policy


def default_policy() -> Policy:
    return load_policy(Path(__file__).parent / "resources/policy-v1.json")


def score_popularity(stars: int, forks: int, watchers: int | None, include_watch: bool,
                     *, policy: Policy | None = None) -> float:
    p = policy or default_policy()
    values = {"stars": stars, "forks": forks, "watch": watchers}
    weights = p.github.popularity_weights if include_watch else p.github.without_watch_weights
    for name in weights:
        if type(values[name]) is not int or values[name] < 0:
            raise ContractError("popularity." + name, "requires a verified nonnegative integer")
    return sum(weight * 100 * min(1, math.log1p(values[name]) / math.log1p(p.github.log_caps[name]))
               for name, weight in weights.items())


def score_recency(days: int | None, archived: bool, *, policy: Policy | None = None) -> float | None:
    p = policy or default_policy()
    if type(archived) is not bool:
        raise ContractError("recency.archived", "requires a known boolean")
    if archived:
        return float(p.maintenance.archived_score)
    if days is None:
        return p.maintenance.unknown_score
    if type(days) is not int or days < 0:
        raise ContractError("recency.days", "requires nonnegative elapsed days")
    for band in p.maintenance.bands:
        if days <= band.max_days:
            return float(band.score)
    return float(p.maintenance.older_score)


def score_assessment(items: Sequence[dict]) -> float | None:
    if not items or any(item.get("status") != "verified" or item.get("value") is None for item in items):
        return None
    for item in items:
        if type(item["value"]) is not int or item["value"] not in (0, 25, 50, 75, 100):
            raise ContractError("assessment", "requires the supported evidence scale")
    return sum(item["value"] for item in items) / len(items)


def weighted_score(values: Mapping[str, float], weights: Mapping[str, float]) -> float:
    if any(name not in values or values[name] is None for name in weights):
        raise ContractError("score", "all effective dimensions must be complete")
    return sum(values[name] * weight for name, weight in weights.items())


def parse_timestamp(value, path="timestamp") -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
        if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        raise ContractError(path, "requires a timezone-aware timestamp") from None


def scoring_reference(state: RunState) -> datetime:
    if "as_of" in state.request.preferences:
        return parse_timestamp(state.request.preferences["as_of"], "RequestContract.preferences.as_of")
    dates = [item.fetched_at for item in state.evidence.values()]
    dates.extend(m.fetched_at for c in state.candidates.values() for m in c.metrics.values())
    return max(dates) if dates else datetime.now(timezone.utc)


def metric_value(card: Candidate, name: str):
    metric = get_metric(card, name)
    if metric is None or metric.status != "verified":
        return None
    subjects = {card.candidate_id, *card.aliases}
    repo = card.identifiers.get("github_repository_id")
    if repo:
        subjects.update({repo, "github:" + repo})
    if metric.subject_id not in subjects:
        return None
    if "repository_id" in metric.scope and str(metric.scope["repository_id"]) != repo:
        return None
    if name == "path_updated_at":
        path = candidate_skill_path(card)
        observed = metric.scope.get("path")
        directory = (posixpath.dirname(path) or ".") if path else None
        exact_directory = metric.scope.get("level") == "skill_path" and observed == directory
        if not path or not (observed == path or exact_directory):
            return None
    return metric.value


def github_components(state: RunState, cid: str, policy: Policy, omitted: Mapping[str, str]) -> dict:
    card = state.candidates[cid]
    assessment = state.assessments.get(cid)
    names = [key for key in policy.assessment_items[state.request.skill] if key not in omitted]
    usability = score_assessment([assessment.usability[key].to_dict() for key in names]) if assessment else None
    stars, forks, watchers = (metric_value(card, name) for name in ("stars", "forks", "watchers"))
    stars = stars if type(stars) is int and stars >= 0 else None
    forks = forks if type(forks) is int and forks >= 0 else None
    watchers = watchers if type(watchers) is int and watchers >= 0 else None
    archived = metric_value(card, "archived")
    updated_name, updated = None, None
    options = ["path_updated_at", "released_at", "pushed_at"] if card.kind == "skill" else ["released_at", "pushed_at"]
    for name in options:
        value = metric_value(card, name)
        if value is not None:
            try:
                date = parse_timestamp(value)
            except ContractError:
                continue
            if date <= scoring_reference(state):
                # A verified path-specific update wins. Otherwise use the latest substantive proxy.
                if updated is None or date > updated:
                    updated_name, updated = name, date
                if name == "path_updated_at":
                    break
    days = (scoring_reference(state) - updated).days if updated else None
    maintenance = score_recency(days, archived, policy=policy) if type(archived) is bool else None
    scope = dict(get_metric(card, updated_name).scope) if updated_name else {}
    directory_proxy = updated_name == "path_updated_at" and scope.get("path") != candidate_skill_path(card)
    result = {"U": usability, "M": maintenance, "stars": stars, "forks": forks,
            "watchers": watchers, "maintenance_source": updated_name, "maintenance_days": days,
            "maintenance_proxy": updated_name == "pushed_at" or directory_proxy}
    if card.kind == "skill":
        result["maintenance_scope"] = scope
    return result


def score_paper(landing: float, influence: float | None, venue: float | None,
                award_bonus: int, group: ComparisonGroup) -> float:
    """Apply the frozen group's shared dimensions, then its verified award bonus."""
    if group.mode not in {"full_paper", "no_venue", "landing_only"}:
        raise ContractError("score_paper.group", "requires a paper comparison group")
    if type(award_bonus) is not int or not 0 <= award_bonus <= 5:
        raise ContractError("score_paper.award_bonus", "requires verified bonus in 0..5")
    values = {"L": landing, "I": influence, "V": venue}
    for name in group.effective_weights:
        value = values.get(name)
        if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 100:
            raise ContractError("score_paper." + name, "requires a complete score in 0..100")
    return min(105.0, weighted_score(values, group.effective_weights) + award_bonus)


def paper_metric(state: RunState, cid: str, name: str, provider: str | None = None):
    """Read one checked, paper-scoped observation without merging source counts."""
    card = state.candidates[cid]
    metric = get_metric(card, name, provider)
    subjects = {cid, *card.aliases, *card.identifiers.values()}
    if metric is None or metric.status != "verified" or metric.subject_id not in subjects:
        return None
    if metric.scope.get("level", "paper") != "paper":
        return None
    if not metric.evidence_ids:
        return None
    for eid in metric.evidence_ids:
        evidence = state.evidence.get(eid)
        if evidence is None or evidence.status != "verified" or evidence.source_category not in {"api", "official", "paper", "repository"}:
            return None
        if evidence.subject_id not in subjects and not subjects.intersection(evidence.scope.get("subject_ids", [])):
            return None
    return metric


def paper_venue_context(state: RunState) -> dict:
    """Load one mapping/evidence generation for a whole scoring operation."""
    evidence = venues.load_venue_evidence()
    for eid, item in state.evidence.items():
        if eid in evidence and evidence[eid].to_dict() != item.to_dict():
            raise ContractError("Venue.evidence", "run and mapping evidence identifiers conflict")
        if eid not in evidence:
            evidence[eid] = item
    return {"records": venues.load_venue_records(), "evidence": evidence}


def _normalized_percentile(state: RunState, cid: str):
    metric = paper_metric(state, cid, "percentile", "openalex")
    if metric is None or metric.unit != "percentile":
        return None
    scope = metric.scope
    # Positive core proof is required even for legacy normalized observations;
    # a missing corpus is not evidence of default-list membership.
    if scope.get("corpus") != "core":
        return None
    for eid in metric.evidence_ids:
        evidence = state.evidence[eid]
        database = evidence.scope.get("database", "")
        official_source = (urlsplit(evidence.source_url).hostname in {"api.openalex.org", "openalex.org"}
                           or isinstance(database, str) and database.casefold() == "openalex")
        if evidence.source_category not in {"api", "official"} or not official_source:
            return None
        if evidence.scope.get("corpus") is not None and evidence.scope["corpus"] != "core":
            return None
    canonical = (scope.get("field") == "citation_normalized_percentile.value"
                 and scope.get("normalization") == "type/publication_year/subfield")
    year = scope.get("publication_year")
    legacy = (isinstance(scope.get("work_type"), str) and bool(scope["work_type"].strip())
              and type(year) is int and year > 0
              and isinstance(scope.get("subfield"), str) and bool(scope["subfield"].strip())
              and isinstance(scope.get("citation_window"), str)
              and scope.get("citation_window") in {
                  f"publication year {year} through {year + 3}",
                  "publication year plus following three years"})
    return metric if canonical or legacy else None


def paper_components(state: RunState, cid: str, policy: Policy, omitted: Mapping[str, str],
                     *, venue_context: dict | None = None) -> dict:
    assessment = state.assessments.get(cid)
    names = [key for key in policy.assessment_items["paper-finding"] if key not in omitted]
    landing = score_assessment([assessment.landing[key].to_dict() for key in names]) if assessment and assessment.reading_depth == "full_text" else None
    percentile = _normalized_percentile(state, cid)
    value = percentile.value if percentile else None
    influence = 100 * value if type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 1 else None
    citations = paper_metric(state, cid, "citations", "openalex")
    count = citations.value if citations and type(citations.value) is int and citations.value >= 0 else None
    context = venue_context if venue_context is not None else paper_venue_context(state)
    venue = venues.paper_venue_scores(state.candidates[cid], context["evidence"], policy, records=context["records"])
    provisional = bool(percentile and (percentile.scope.get("provisional_window") is True
                       or percentile.scope.get("window_complete") is False))
    return {"L": landing, "I": influence, "V": venue["V"], "award_bonus": venue["award_bonus"],
            "venue_evidence_ids": venue["evidence_ids"], "venue_limitations": venue["limitations"],
            "citations": count, "citations_provider": "openalex",
            "provisional_influence": provisional,
            "influence_scope": dict(percentile.scope) if percentile else None,
            "influence_method": percentile.method_version if percentile else None}
