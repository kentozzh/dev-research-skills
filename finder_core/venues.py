"""Versioned venue facts, exact scoped awards, and conservative scoring gates.

The bundled CCF2026 catalogue is a verified subset of a CCF-authored PDF hosted
by a university. It is not a complete catalogue or publication-year grading.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Mapping, Sequence

from .contracts import Candidate, Evidence, Metric, Policy, VenueEdition, VenueRecord
from .evidence import candidate_subject_ids, _supports_subject, metric_name
from .validation import ContractError

RESOURCE_ROOT = Path(__file__).parent / "resources/venues"


def _resource(name):
    return json.loads((RESOURCE_ROOT / name).read_text(encoding="utf-8"))


def load_venue_evidence() -> dict[str, Evidence]:
    result = {}
    for name in ("ccf-2026.json", "aliases.json", "editions.json", "awards.json"):
        for item in _resource(name).get("evidence", []):
            ev = Evidence.from_dict(item)
            if ev.evidence_id in result and result[ev.evidence_id] != ev:
                raise ContractError("Venue.evidence", "conflicting evidence identifiers")
            result[ev.evidence_id] = ev
    return result


def load_venue_records() -> list[VenueRecord]:
    """Return fresh typed records, without I/O beyond the bundled JSON files."""
    records = [VenueRecord.from_dict(item) for item in _resource("ccf-2026.json")["records"]]
    aliases, editions, awards = [_resource(name).get("records", {}) for name in ("aliases.json", "editions.json", "awards.json")]
    for record in records:
        record.aliases = aliases.get(record.venue_id, {}).get("aliases", [])
        edition = editions.get(record.venue_id, {})
        record.editions = [VenueEdition.from_dict(item) for item in edition.get("editions", [])]
        record.acceptance_numerator = edition.get("acceptance_numerator")
        record.acceptance_denominator = edition.get("acceptance_denominator")
        record.acceptance_scope = edition.get("acceptance_scope", "")
        record.acceptance_evidence_ids = edition.get("acceptance_evidence_ids", [])
        record.award_scope = awards.get(record.venue_id, {})
        record.award_evidence_ids = record.award_scope.get("evidence_ids", [])
        record.to_dict()
    return records


PUBLICATION_FIELDS = {"venue", "publication_year", "publication_track", "publication_type"}


def publication_fact(candidate: Candidate, name: str, evidence: Mapping[str, Evidence]) -> Metric | None:
    """Resolve publication fields by checked publication-source authority.

    Official/paper records and publication APIs outrank bibliographic discovery
    APIs. Unknown observations are nonfacts; equal-authority disagreement remains
    unavailable. Raw observations and generic citation ambiguity are unchanged.
    """
    if name not in PUBLICATION_FIELDS:
        raise ValueError("requires a publication field")
    subjects = candidate_subject_ids(candidate)
    ranked = []
    for key, metric in candidate.metrics.items():
        if metric_name(key, metric) != name or metric.subject_id not in subjects or not metric.evidence_ids:
            continue
        sources = [evidence.get(eid) for eid in metric.evidence_ids]
        if any(item is None or item.status != "verified" or item.source_category not in {"official", "api", "paper"}
               or not _supports_subject(item, subjects) for item in sources):
            continue
        if metric.status not in {"verified", "conflict"}:
            continue
        authority = 2 if all(item.source_category in {"official", "paper"} or
            (item.source_category == "api" and metric.provider not in {"openalex", "semantic_scholar", "arxiv"})
            for item in sources) else 1
        ranked.append((authority, metric))
    if not ranked:
        return None
    best = [metric for rank, metric in ranked if rank == max(rank for rank, _ in ranked)]
    if any(metric.status != "verified" or metric.value != best[0].value for metric in best):
        return None
    result = Metric.from_dict(best[0].to_dict())
    result.evidence_ids = sorted({eid for metric in best for eid in metric.evidence_ids})
    return result


def resolve_venue(candidate: Candidate, records: Sequence[VenueRecord], *, evidence: Mapping[str, Evidence]) -> VenueRecord | None:
    """Exact alias + actual track/type; unknown Findings/workshop never inherit.

    Uses the same provenance-aware publication facts as scoring and display.
    """
    if candidate.kind != "paper":
        return None
    facts = [publication_fact(candidate, name, evidence) for name in ("venue", "publication_track", "publication_type")]
    venue, track, paper_type = [metric.value if metric else None for metric in facts]
    if not all(isinstance(value, str) and value for value in (venue, track, paper_type)):
        return None
    matches = [record for record in records if venue.casefold() in {a.casefold() for a in [record.venue_id, *record.aliases]}
               and track in record.applicable_tracks and paper_type in record.applicable_types]
    return matches[0] if len(matches) == 1 else None


def venue_catalog_status(venue: str) -> str:
    """A miss in a verified subset means uncovered, never absent from CCF."""
    return "已覆盖" if any(venue.casefold() in {r.venue_id.casefold(), *(a.casefold() for a in r.aliases)}
                           for r in load_venue_records()) else "未覆盖"


def summarize_awards(records: Sequence[VenueRecord]) -> dict:
    """Separate setting persistence, evidence coverage, and scoped award rates.

    Records are the versioned verified-evidence configuration boundary. Unknown
    editions never count as 'no awards'. Missing/partial lists yield no rate.
    """
    output = {}
    for record in records:
        scope = record.award_scope
        if not scope:
            continue
        target = set(scope.get("target_years", []))
        verified, rates = {}, {}
        for edition in scope.get("editions", []):
            year = edition.get("year")
            if year not in target or edition.get("status") != "verified" or type(edition.get("setting")) is not bool or not edition.get("evidence_ids"):
                continue
            if year in verified and verified[year] != edition["setting"]:
                raise ContractError("Venue.awards", "conflicting award-setting evidence for one edition")
            verified[year] = edition["setting"]
            for award in edition.get("awards", []):
                tracks, types = sorted(set(award.get("tracks", []))), sorted(set(award.get("types", [])))
                key = (year, award.get("category"), tuple(tracks), tuple(types))
                members = set(award.get("member_ids", []))
                denom = award.get("denominator")
                compatible = (bool(tracks and types) and type(denom) is int and denom > 0
                    and sorted(set(award.get("denominator_tracks", []))) == tracks
                    and sorted(set(award.get("denominator_types", []))) == types
                    and award.get("list_complete", True) is True)
                if key not in rates:
                    rates[key] = {"year": year, "category": award.get("category"), "raw_names": [],
                        "tracks": tracks, "types": types, "member_ids": set(), "denominator": denom,
                        "compatible": compatible}
                item = rates[key]
                item["member_ids"].update(members)
                item["raw_names"].append(award.get("raw_name"))
                item["compatible"] = item["compatible"] and compatible and item["denominator"] == denom
        serialized = []
        for rate in rates.values():
            members = rate.pop("member_ids")
            compatible = rate.pop("compatible")
            rate["numerator"] = len(members)
            rate["ratio"] = len(members) / rate["denominator"] if compatible and len(members) <= rate["denominator"] else None
            rate["limitation"] = "" if rate["ratio"] is not None else "Missing complete matched award list or same-scope accepted-paper denominator"
            serialized.append(rate)
        count = len(verified)
        settings = sum(verified.values())
        output[record.venue_id] = {"setting_numerator": settings, "setting_denominator": count,
            "setting_ratio": settings / count if count else None, "verified_editions": count,
            "target_editions": len(target), "evidence_coverage": count / len(target) if target else None,
            "award_rates": serialized, "scope_note": scope.get("coverage_note", "")}
    return output


def paper_venue_scores(candidate: Candidate, evidence: Mapping[str, Evidence], policy: Policy,
                       *, records: Sequence[VenueRecord] | None = None) -> dict:
    """Only verified actual scope and versioned primary mappings earn V/bonus.

    Raw candidate ccf/award strings are deliberately not scoring inputs. Config
    defines exact award categories and identified winners; unknown is zero bonus
    (unverified award), while unknown V is None. Award points take max, never sum.
    """
    known = load_venue_evidence() if records is None else {}
    # Callers cannot replace a bundled evidence ID with an unrelated observation.
    for eid, item in evidence.items():
        if eid not in known:
            known[eid] = item
    records = load_venue_records() if records is None else records
    facts = {name: publication_fact(candidate, name, known) for name in
             ("venue", "publication_year", "publication_track", "publication_type")}
    result = {"V": None, "award_bonus": 0, "evidence_ids": [], "limitations": []}
    if any(metric is None for metric in facts.values()):
        result["limitations"].append("Verified primary venue/year/track/type scope unavailable")
        return result
    year = facts["publication_year"].value
    if type(year) is not int or year <= 0:
        result["limitations"].append("Verified publication year unavailable")
        return result
    record = resolve_venue(candidate, records, evidence=known)
    if record is None:
        result["limitations"].append("Venue/track/type not covered by verified subset; CCF applicability unknown")
        return result
    refs = [eid for metric in facts.values() for eid in metric.evidence_ids]
    ccf = record.ccf
    if ccf is not None and ccf.status == "verified" and ccf.subject_id == record.venue_id and ccf.value in policy.paper.ccf_scores:
        scope = ccf.scope
        valid_scope = (scope.get("evaluation_basis") == "current_catalog" and scope.get("catalog_version")
            and facts["publication_track"].value in scope.get("applicable_tracks", [])
            and facts["publication_type"].value in scope.get("applicable_types", []))
        checked = bool(ccf.evidence_ids)
        for eid in ccf.evidence_ids:
            item = known.get(eid)
            checked = checked and bool(item and item.status == "verified" and
                item.scope.get("author") == "CCF" and item.scope.get("catalog_version") == scope.get("catalog_version")
                and item.scope.get("venue_grades", {}).get(record.venue_id) == ccf.value
                and (item.source_category in {"official", "paper"} or item.scope.get("source_hosting") == "CCF-authored university mirror"))
        if valid_scope and checked:
            result["V"] = policy.paper.ccf_scores[ccf.value]
            refs += ccf.evidence_ids
            result["limitations"].append("Current-catalog venue evaluation; publication-year grade unverified")
            if scope.get("source_hosting") == "CCF-authored university mirror":
                result["limitations"].append("CCF-authored university mirror text verified; official-host hash equivalence and visual review unverified")
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", "", candidate.identifiers.get("doi", "").strip(), flags=re.I).lower()
    track, paper_type = facts["publication_track"].value, facts["publication_type"].value
    for edition in record.award_scope.get("editions", []):
        if edition.get("year") != year or edition.get("status") != "verified" or edition.get("setting") is not True:
            continue
        for award in edition.get("awards", []):
            if track not in award.get("tracks", []) or paper_type not in award.get("types", []):
                continue
            category = award.get("category")
            if category not in policy.paper.award_bonus or award.get("status") != "verified":
                continue
            if not doi or "doi:" + doi not in award.get("member_ids", []):
                continue
            ids = award.get("evidence_ids", [])
            if not ids or any(eid not in known or known[eid].status != "verified" or
                    known[eid].source_category not in {"official", "paper"} for eid in ids):
                continue
            if not any(known[eid].scope.get("award_types", {}).get(award.get("raw_name")) == category for eid in ids):
                continue
            identity_proofs = [known[eid] for eid in ids if known[eid].scope.get("doi") == doi
                and known[eid].scope.get("venue") == record.venue_id and known[eid].scope.get("year") == year
                and known[eid].scope.get("track") == track and known[eid].scope.get("type") == paper_type]
            if not identity_proofs:
                continue
            actual_refs = {eid for metric in facts.values() for eid in metric.evidence_ids}
            # A DOI string alone is not an authenticated paper identity. Require
            # actual primary evidence tied to this candidate to expose that DOI
            # or the same official paper URL as the versioned identity proof.
            if not any(known[eid].scope.get("doi") == doi or
                       known[eid].source_object.get("doi") == doi or
                       known[eid].source_url in {proof.source_url for proof in identity_proofs}
                       for eid in actual_refs):
                continue
            # Exact raw label is mapped in a versioned official record, never by substring.
            if not record.version or not award.get("raw_name"):
                continue
            result["award_bonus"] = max(result["award_bonus"], policy.paper.award_bonus[category])
            refs += ids
    if not result["award_bonus"]:
        result["limitations"].append("Award unverified for this paper; partial mapping is not proof of absence")
    result["evidence_ids"] = sorted(set(refs))
    return result
