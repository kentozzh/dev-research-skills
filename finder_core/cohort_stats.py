"""Offline statistics on complete mother sets, outside recommendation capacity.

High citation uses provider flags, zero citation uses cumulative counts. Missing
data ranges are extreme bounds, not confidence intervals. No network I/O occurs.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Sequence

from .contracts import Candidate, CohortManifest, CohortSummary, Metric
from .evidence import get_metric
from .validation import ContractError, load_policy

METHOD = "complete-cohort-observed-denominators-v1"
ZERO_WINDOW = "cumulative citations as of manifest.queried_at"
POLICY_PATH = Path(__file__).parent / "resources/policy-v1.json"


def _doi(value: str) -> str:
    return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", "", value.strip(), flags=re.I).lower()


def _summary(H, n_h, Z, n_c, N, *, manifests, high_window, zero_window=ZERO_WINDOW, comparable=True, reasons=()):
    reasons = list(dict.fromkeys(reasons))
    threshold = load_policy(POLICY_PATH).paper.venue_coverage_threshold
    if N == 0:
        reasons.append("Empty complete mother set: N=0; statistics unavailable")
    if n_h == 0:
        reasons.append("High-citation denominator is zero; proportion unavailable")
    if n_c == 0:
        reasons.append("Cumulative-citation denominator is zero; proportion unavailable")
    if N and (n_h / N < threshold or n_c / N < threshold):
        reasons.append("Annual coverage below threshold: observed matched subset; no cross-venue ranking")
    valid = bool(N and n_h and n_c and n_h / N >= threshold and n_c / N >= threshold)
    return CohortSummary(H, n_h, Z, n_c, N,
        high_ratio=H / n_h if n_h else None, zero_ratio=Z / n_c if n_c else None,
        high_coverage=n_h / N if N else None, zero_coverage=n_c / N if N else None,
        high_lower=H / N if N else None, high_upper=(H + N - n_h) / N if N else None,
        zero_lower=Z / N if N else None, zero_upper=(Z + N - n_c) / N if N else None,
        comparable=comparable and valid, missing_reasons=reasons, manifests=manifests,
        calculation_method=METHOD, high_window=high_window, zero_window=zero_window)


def _valid_metric(candidate, name, manifest):
    metric = get_metric(candidate, name, provider=manifest.database)
    subjects = {candidate.candidate_id, *candidate.identifiers.values()}
    if metric is None or metric.status != "verified" or metric.subject_id not in subjects:
        return None
    if not metric.evidence_ids or metric.fetched_at > manifest.queried_at:
        return None
    if name == "top1" and type(metric.value) is not bool:
        return None
    if name == "citations" and (type(metric.value) is not int or metric.value < 0):
        return None
    if name == "publication_year" and (type(metric.value) is not int or metric.value <= 0):
        return None
    return metric


def calculate_cohort(manifest: CohortManifest, records: Sequence[Candidate]) -> CohortSummary:
    """Compute only manifest members; never substitute discovery search results.

    Candidate IDs are manifest membership keys. Missing candidate observations
    remain unknown. Duplicate/out-of-scope identities are rejected. Normalized
    window/method metadata is required for comparison, independent of coverage.
    """
    manifest = CohortManifest.from_dict(manifest.to_dict())
    records = [Candidate.from_dict(c.to_dict()) for c in records]
    if not manifest.complete or not manifest.source_urls:
        return CohortSummary(0, 0, 0, 0, manifest.N, missing_reasons=[
            "Complete official mother set unavailable; statistics not calculated"], manifests=[manifest],
            calculation_method=METHOD, zero_window=ZERO_WINDOW)
    members = set(manifest.member_ids)
    seen, identities = set(), set()
    for card in records:
        if card.kind != "paper" or card.candidate_id not in members or card.candidate_id in seen:
            raise ContractError("Cohort.records", "unique paper records must belong to the explicit manifest")
        seen.add(card.candidate_id)
        for key in ("doi", "openalex", "semantic_scholar", "arxiv"):
            if key in card.identifiers:
                value = _doi(card.identifiers[key]) if key == "doi" else card.identifiers[key].strip()
                identity = (key, value)
                if identity in identities:
                    raise ContractError("Cohort.records", "duplicate stable paper identity")
                identities.add(identity)
    H = n_h = Z = n_c = 0
    reasons, methods, windows, corpora = [], set(), set(), set()
    for card in records:
        high = _valid_metric(card, "top1", manifest)
        count = _valid_metric(card, "citations", manifest)
        if high is not None:
            n_h += 1
            H += int(high.value)
            method = high.scope.get("normalization_method")
            window = high.scope.get("normalized_window")
            # T08's actual adapter labels the documented normalization directly;
            # its adapter version is explicitly distinct from a missing saved
            # snapshot method. Never promote arbitrary adapter-v1 strings.
            if (high.provider == "openalex" and high.method_version == "openalex-citation-normalized-percentile-2026-11-10"
                    and high.scope.get("normalization") == "type/publication_year/subfield"
                    and high.scope.get("citation_window") == "publication year plus following three years"):
                method, window = high.method_version, high.scope["citation_window"]
            if high.scope.get("provisional_window") is True:
                reasons.append("Normalized observation window incomplete; no cross-venue ranking")
            if not isinstance(method, str) or not method.strip() or not isinstance(window, str) or not window.strip():
                reasons.append("Normalized flag method/window provenance unavailable; no cross-venue ranking")
            else:
                methods.add(method)
                windows.add(window)
        if count is not None:
            n_c += 1
            Z += int(count.value == 0)
        for metric in (high, count):
            if metric is not None and metric.scope.get("corpus"):
                corpora.add(str(metric.scope["corpus"]))
        year = _valid_metric(card, "publication_year", manifest)
        if high is not None and year is None:
            reasons.append("Provider publication year unavailable; normalized reference window uncertain")
        elif year is not None and year.value != manifest.year:
            reasons.append("Provider publication year differs from official cohort year; normalized reference window uncertain")
    if len(methods) > 1 or len(windows) > 1:
        reasons.append("Mixed normalized flag method/window definitions; no cross-venue ranking")
    if len(corpora) > 1:
        reasons.append("Mixed database corpus scopes; no cross-venue ranking")
    high_window = json.dumps({"window": sorted(windows), "method": sorted(methods), "corpus": sorted(corpora)}, sort_keys=True)
    zero_window = json.dumps({"window": ZERO_WINDOW, "corpus": sorted(corpora)}, sort_keys=True)
    return _summary(H, n_h, Z, n_c, manifest.N, manifests=[manifest], high_window=high_window,
                    zero_window=zero_window, comparable=not reasons, reasons=reasons)


def combine_cohorts(summaries: Sequence[CohortSummary]) -> CohortSummary:
    """Sum counts over disjoint annual cohorts with matching definitions.

    Legacy count-only summaries are intentionally insufficient to establish a
    comparable merge. Every annual veto propagates even if pooled coverage rises.
    """
    summaries = [CohortSummary.from_dict(s.to_dict()) for s in summaries]
    if not summaries:
        return _summary(0, 0, 0, 0, 0, manifests=[], high_window="", comparable=False)
    manifests, members, scopes, signatures = [], set(), set(), set()
    for summary in summaries:
        if not summary.manifests or not summary.calculation_method or not summary.high_window or not summary.zero_window:
            raise ContractError("CohortSummary.manifests", "scoped calculation/window context required for combination")
        if sum(m.N for m in summary.manifests) != summary.N or any(not m.complete for m in summary.manifests):
            raise ContractError("CohortSummary.manifests", "complete manifest counts must reconcile with summary")
        for manifest in summary.manifests:
            scope = (manifest.venue, manifest.year, manifest.track, manifest.type)
            if scope in scopes or members.intersection(manifest.member_ids):
                raise ContractError("CohortSummary.manifests", "duplicate cohort or overlapping members")
            scopes.add(scope)
            members.update(manifest.member_ids)
            signatures.add((manifest.venue, manifest.track, manifest.type, manifest.database,
                manifest.queried_at.date(), summary.calculation_method, summary.high_window, summary.zero_window))
            manifests.append(manifest)
    if len(signatures) != 1:
        raise ContractError("CohortSummary.manifests", "incompatible venue/track/type/database/query date/method/window")
    return _summary(*(sum(getattr(s, field) for s in summaries) for field in ("H", "n_h", "Z", "n_c", "N")),
        manifests=manifests, high_window=summaries[0].high_window, zero_window=summaries[0].zero_window,
        comparable=all(s.comparable and s.N and s.n_h/s.N >= load_policy(POLICY_PATH).paper.venue_coverage_threshold
                       and s.n_c/s.N >= load_policy(POLICY_PATH).paper.venue_coverage_threshold for s in summaries),
        reasons=[reason for summary in summaries for reason in summary.missing_reasons])


def eligible_cohort_years(as_of: datetime) -> list[int]:
    """Latest three completed publication-year-plus-three-year windows."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ContractError("as_of", "timezone-aware query datetime required")
    return [as_of.year - offset for offset in load_policy(POLICY_PATH).paper.mature_year_offsets]


def load_saved_acl_cohort(metadata_path: Path, observations_path: Path):
    """Adapt the saved ACL2022 main/long snapshots, preserving their limitations.

    Returns (manifest, records, provenance). It does not claim original raw
    requests or normalized method versions exist, and performs no enrichment.
    """
    try:
        return _load_saved_acl_cohort(Path(metadata_path), Path(observations_path))
    except ContractError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ContractError("ACL.snapshot", "malformed saved ACL/OpenAlex snapshot schema") from None


def _load_saved_acl_cohort(metadata_path, observations_path):
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    observations = json.loads(observations_path.read_text(encoding="utf-8"))
    if (metadata.get("venue"), metadata.get("year"), metadata.get("track"), metadata.get("paper_type")) != ("ACL", 2022, "main", "long"):
        raise ContractError("ACL.snapshot", "only official ACL 2022 main/long saved schema supported")
    official = metadata["papers"]
    if metadata["source_url"] != "https://aclanthology.org/volumes/2022.acl-long.bib":
        raise ContractError("ACL.snapshot.source_url", "expected official ACL2022 main/long BibTeX source")
    if any(not isinstance(p.get("bib_key"), str) or not p["bib_key"] or
           p.get("url") != "https://aclanthology.org/" + _doi(p["doi"]).split("/", 2)[-1] + "/" for p in official):
        raise ContractError("ACL.snapshot.papers", "official DOI, URL and bibliographic identity must agree")
    if len({p["bib_key"] for p in official}) != len(official):
        raise ContractError("ACL.snapshot.papers", "duplicate official bibliographic keys")
    ids = ["doi:" + _doi(p["doi"]) for p in official]
    if any(not re.fullmatch(r"doi:10\.18653/v1/2022\.acl-long\.\d+", cid) for cid in ids):
        raise ContractError("ACL.snapshot", "unexpected official DOI scope")
    if set(ids) != {f"doi:10.18653/v1/2022.acl-long.{i}" for i in range(1, 604)} or metadata["N"] != 603:
        raise ContractError("ACL.snapshot", "official 603-member volume completeness does not reconcile")
    queried_at = datetime.fromisoformat(observations["retrieved_at"])
    manifest = CohortManifest("ACL", 2022, "main", "long", ids, metadata["N"],
        [metadata["source_url"], "https://aclanthology.org/volumes/2022.acl-long/"],
        [metadata.get("excluded", "proceedings/preface entries; only inproceedings records with DOI and URL")],
        "openalex", queried_at, True, ["acl-2022-official-saved-members"])
    batches = observations.get("batches", [])
    slots = [i for batch in batches for i in range(batch["start"], batch["start"] + batch["requested"])]
    if observations.get("cohort_N") != 603 or sorted(slots) != list(range(603)) or sum(b["returned"] for b in batches) != len(observations["works"]) or any(
            b["requested"] != b["returned"] or b["returned"] != b["count"] for b in batches):
        raise ContractError("ACL.snapshot.batches", "saved batch ledger does not reconcile")
    rows, works, mismatches, records = {}, set(), [], []
    for work in observations["works"]:
        cid = "doi:" + _doi(work["doi"])
        wid = work["id"]
        if cid not in set(ids) or cid in rows or wid in works or not re.fullmatch(r"https://openalex.org/W\d+", wid):
            raise ContractError("ACL.snapshot.works", "duplicate, invalid or out-of-cohort DOI/OpenAlex identity")
        rows[cid] = work
        works.add(wid)
        metrics = {}
        percentile = work.get("citation_normalized_percentile") or {}
        for name, value, unit in [("top1", percentile.get("is_in_top_1_percent"), "boolean"),
                                  ("citations", work.get("cited_by_count"), "count"),
                                  ("publication_year", work.get("publication_year"), "year")]:
            valid = type(value) is bool if name == "top1" else type(value) is int and value >= 0
            metrics[name] = Metric(value if valid else None, "verified" if valid else "unavailable", unit,
                "openalex", wid, queried_at, {"source_snapshot": observations_path.name,
                "normalized_window": None, "normalization_method": None},
                ["openalex-saved:" + wid.rsplit("/", 1)[-1]] if valid else [], "saved-field-adapter-v1")
        if work.get("publication_year") != 2022:
            mismatches.append({"doi": _doi(work["doi"]), "openalex_id": wid,
                "official_venue_year": 2022, "openalex_publication_year": work.get("publication_year")})
        records.append(Candidate(cid, "paper", identifiers={"doi": _doi(work["doi"]), "openalex": wid}, metrics=metrics))
    provenance = {"official_source_url": metadata["source_url"], "official_observed_at": metadata["observed_at"],
        "openalex_retrieved_at": observations["retrieved_at"], "raw_responses_available": False,
        "normalized_method_version": None, "publication_year_mismatches": mismatches,
        "saved_batch_count": len(batches), "matched_records": len(rows),
        "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (metadata_path, observations_path)},
        "limitations": ["Saved list omits raw BibTeX and excluded-record counts; official volume separately reports 603 DOI papers",
            "Saved API fields omit raw responses, URLs/filters/headers, per-batch timestamps and normalized method/window metadata",
            "High flags describe OpenAlex normalized windows; zero citation is cumulative at saved query time",
            "Year mismatch retained in primary counts; normalized-window comparability is uncertain",
            "No coverage of other years or venues; no fresh network verification"]}
    return manifest, records, provenance
