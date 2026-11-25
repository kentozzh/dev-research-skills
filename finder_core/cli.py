"""Stdlib CLI; every mutating load/network/save transaction holds a run lock."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
from typing import Sequence

from .cache import FileCache
from .contracts import Candidate, CohortManifest, RankedReport, RunState
from .cohort_stats import METHOD as COHORT_METHOD, calculate_cohort, combine_cohorts, eligible_cohort_years, load_saved_acl_cohort
from datetime import datetime, timezone
from .evidence import content_hash
from .groups import build_group, star_exclusion
from .providers.imported import validate_observations
from .ranking import rank_candidates
from .reporting import render_report
from .scoring import default_policy
from .store import _atomic_json, load_run, prepare_run, revise_run, save_run
from .transport import HttpClient
from .validation import ContractError, validate_assessment, validate_request
from .venues import load_venue_records, summarize_awards
from .workflow import merge_with_capacity, run_discovery, run_enrichment, run_skill_inspection, run_skill_inventory, validate_venue_statistics


def provider_registry(http):
    from .providers.github import GitHubProvider
    from .providers.arxiv import ArxivProvider
    from .providers.openalex import OpenAlexProvider
    from .providers.semantic_scholar import SemanticScholarProvider
    return {"github": GitHubProvider(http), "arxiv": ArxivProvider(http),
            "openalex": OpenAlexProvider(http), "semantic_scholar": SemanticScholarProvider(http)}


@contextmanager
def _command_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ContractError("run_dir", "command already active; inspect a confirmed stale .command.lock before removing it") from None
    try:
        os.close(descriptor)
        yield
    finally:
        path.unlink(missing_ok=True)


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError):
        raise ContractError("input", "cannot read valid JSON") from None


def _summary(state):
    return {"run_id": state.run_id, "contract_revision": state.request.contract_revision,
            "snapshot_id": state.snapshot_id, "candidates": len(state.candidates),
            "assessments": len(state.assessments), "limits": [item.to_dict() for item in state.limits],
            "request_counts": dict(state.request_counts)}


def _sync_http(state, http, original_limits=()):
    limits = list(http.provider_limits)
    known = {content_hash(item.to_dict()) for item in limits}
    for item in state.limits:
        key = content_hash(item.to_dict())
        if key not in known and key not in original_limits:
            limits.append(item)
            known.add(key)
    http.provider_limits[:] = limits
    # Contract normalization creates copies. Preserve workflow bookkeeping while
    # rebinding actual HTTP attempts to the live transport's authoritative map.
    for key,value in state.request_counts.items():
        if key.startswith("workflow_"):
            http.request_counts[key] = value
    state.request_counts = http.request_counts
    state.limits = http.provider_limits


def _parser():
    parser = argparse.ArgumentParser(prog="finder_core")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "revise", "discover", "import", "enrich", "inventory-skills", "inspect-skills", "assess", "rank", "report", "venue-stats"):
        command = sub.add_parser(name)
        command.add_argument("--run-dir", required=True)
        if name in {"prepare", "revise"}:
            command.add_argument("--request", required=True)
        if name in {"import", "assess", "inspect-skills"}:
            command.add_argument("--input", required=True)
        if name in {"enrich", "inventory-skills"}:
            command.add_argument("--ids", required=True, help="JSON array, or a JSON file containing an array")
        if name == "report":
            command.add_argument("--format", choices=("markdown", "json"), default="markdown")
            command.add_argument("--output")
        if name == "venue-stats":
            command.add_argument("--manifest", help="Typed complete CohortManifest JSON")
            command.add_argument("--records", help="Separate complete Candidate JSON array for --manifest")
            command.add_argument("--input", help="Separate JSON cohorts array of {manifest, records}; never recommendation candidates")
            command.add_argument("--acl-metadata", help="Saved official ACL2022 main/long metadata JSON")
            command.add_argument("--openalex-observations", help="Saved OpenAlex observation JSON paired with --acl-metadata")
    return parser


def _stale(state, policy):
    expected = {"skill-finding":"skill","tool-finding":"tool","paper-finding":"paper"}[state.request.skill]
    if state.invalidated and any(card.kind == expected and (expected == "paper" or not star_exclusion(state, cid, policy))
                                 for cid, card in state.candidates.items()):
        return True
    return any(a.contract_revision != state.request.contract_revision or a.snapshot_id != state.snapshot_id
               for a in state.assessments.values())


def _venue_statistics(args, state):
    if state.request.skill != "paper-finding":
        raise ContractError("venue-stats", "requires a paper-finding run")
    if (bool(args.acl_metadata) != bool(args.openalex_observations) or
            sum(bool(value) for value in (args.manifest, args.input, args.acl_metadata)) > 1 or
            (args.records and not args.manifest)):
        raise ContractError("venue-stats.input", "supply --manifest [--records], --input, or both saved ACL paths")
    annual, sources, limitations = [], [], []
    if args.manifest:
        manifest = CohortManifest.from_dict(_read(args.manifest))
        if args.records:
            payload = _read(args.records)
            if not isinstance(payload, list):
                raise ContractError("venue-stats.records", "requires separate Candidate JSON array")
            records = [Candidate.from_dict(record) for record in payload]
        else:
            records = [card for cid, card in state.candidates.items() if cid in manifest.member_ids]
        if {card.candidate_id for card in records} != set(manifest.member_ids):
            raise ContractError("venue-stats.records", "complete manifest records absent; provide a separate --records array")
        annual.append(calculate_cohort(manifest, records))
    elif args.acl_metadata:
        manifest, records, provenance = load_saved_acl_cohort(Path(args.acl_metadata), Path(args.openalex_observations))
        annual.append(calculate_cohort(manifest, records))
        sources.append(provenance)
    else:
        path = Path(args.input) if args.input else Path(args.run_dir) / "cohorts.json"
        if args.input or path.exists():
            payload = _read(path)
            if not isinstance(payload, dict) or not isinstance(payload.get("cohorts"), list):
                raise ContractError("venue-stats.input", "requires {cohorts:[{manifest,records}]}")
            for item in payload["cohorts"]:
                if not isinstance(item, dict) or not isinstance(item.get("manifest"), dict) or not isinstance(item.get("records"), list):
                    raise ContractError("venue-stats.input", "each cohort needs explicit manifest and separate records")
                manifest = CohortManifest.from_dict(item["manifest"])
                records = [Candidate.from_dict(record) for record in item["records"]]
                annual.append(calculate_cohort(manifest, records))
    if not annual:
        limitations.append("No verified complete cohort supplied or cached; no statistics calculated")
    if state.request.deep_venue_stats:
        limitations.append("Deep statistics requested; this version accepts supplied/cached complete cohorts and has no general venue collector")
    else:
        limitations.append("Deep statistics disabled; no additional batch enrichment performed")
    # Each venue/track/type/database remains an independent series. Never merge
    # unlike scopes merely because a CLI input contains several cohorts.
    grouped = {}
    for summary in annual:
        m = summary.manifests[0]
        grouped.setdefault((m.venue, m.track, m.type, m.database), []).append(summary)
    combined = []
    for summaries in grouped.values():
        if len(summaries) > 1:
            combined.append(combine_cohorts(summaries).to_dict())
    result = {"annual": [summary.to_dict() for summary in annual], "combined": combined,
        "eligible_default_years": eligible_cohort_years(datetime.now(timezone.utc)),
        "deep_venue_stats": state.request.deep_venue_stats,
        "awards": summarize_awards(load_venue_records()), "source_provenance": sources,
        "limitations": limitations, "provenance": {"run_id": state.run_id, "snapshot_id": state.snapshot_id,
            "contract_revision": state.request.contract_revision, "state_hash": content_hash(state.to_dict()),
            "artifact_version": "1", "calculation_method": COHORT_METHOD,
            "generated_at": datetime.now(timezone.utc).isoformat()}}
    result["provenance"]["query_scope_hash"] = content_hash([summary["manifests"] for summary in result["annual"] + result["combined"]])
    result["provenance"]["artifact_hash"] = content_hash(result)
    return result


def _execute(args):
    run_dir, policy = Path(args.run_dir), default_policy()
    if args.command == "prepare":
        # Separate sibling lock keeps prepare_run's empty-directory guarantee.
        lock = run_dir.parent / ("." + run_dir.name + ".prepare.command.lock")
        with _command_lock(lock):
            state = prepare_run(validate_request(_read(args.request)), run_dir)
        return 0, _summary(state)
    if args.command == "report":
        state = load_run(run_dir)
        path = run_dir / "ranking.json"
        if _stale(state, policy) or not path.exists():
            return 4, {"reason": "Ranking is missing or invalidated; assess and rank the current snapshot"}
        report = RankedReport.from_dict(_read(path))
        ranked_minimum = report.provenance.get("policy", {}).get("github", {}).get("minimum_repository_stars")
        if state.request.skill in {"tool-finding", "skill-finding"} and ranked_minimum != policy.github.minimum_repository_stars:
            return 4, {"reason": "Repository star threshold changed; rerun rank for the current snapshot"}
        if report.provenance.get("snapshot_id") != state.snapshot_id or report.provenance.get("contract_revision") != state.request.contract_revision or report.provenance.get("state_hash") != content_hash(state.to_dict()):
            return 4, {"reason": "Ranking does not match the canonical current run"}
        if "venue_statistics" in report.provenance:
            validate_venue_statistics(state, report.provenance["venue_statistics"])
        rendered = render_report(report, args.format)
        if args.output:
            Path(args.output).write_text(rendered, encoding="utf-8")
            return 0, {"output": str(Path(args.output).absolute())}
        return 0, rendered
    with _command_lock(run_dir / ".command.lock"):
        state = load_run(run_dir)
        if args.command == "venue-stats":
            result = _venue_statistics(args, state)
            _atomic_json(run_dir / "venue-stats.json", result)
            return 0, result
        elif args.command == "revise":
            state = revise_run(state, validate_request(_read(args.request)))
        elif args.command == "import":
            state = merge_with_capacity(state, validate_observations(_read(args.input)), policy)
        elif args.command == "assess":
            payload = _read(args.input)
            if not isinstance(payload, list):
                raise ContractError("assess.input", "requires an array of Assessment records")
            if any(not isinstance(item, dict) or item.get("candidate_id") not in state.candidates for item in payload):
                raise ContractError("assess.input", "requires known candidate IDs")
            assessments = [validate_assessment(item, state.request, state.snapshot_id, state.evidence,
                                               state.candidates[item["candidate_id"]]) for item in payload]
            if len({a.candidate_id for a in assessments}) != len(assessments) or any(a.candidate_id not in state.candidates for a in assessments):
                raise ContractError("assess.input", "requires unique known candidate IDs")
            state.assessments.update({a.candidate_id: a for a in assessments})
            if assessments:
                state.invalidated, state.invalidation_reason = False, None
        elif args.command == "rank":
            if _stale(state, policy):
                return 4, {"reason": state.invalidation_reason or "Assessments do not match the current snapshot"}
            report = rank_candidates(state, build_group(state, policy), policy)
            if state.request.skill == "paper-finding" and (run_dir / "venue-stats.json").exists():
                report.provenance["venue_statistics"] = validate_venue_statistics(state, _read(run_dir / "venue-stats.json"))
            report.provenance["state_hash"] = content_hash(state.to_dict())
            _atomic_json(run_dir / "ranking.json", report.to_dict())
            return 0, report.to_dict()
        elif args.command in {"discover", "enrich", "inventory-skills", "inspect-skills"}:
            http = HttpClient(FileCache(run_dir / "cache"), policy=policy, skill=state.request.skill,
                              request_counts=state.request_counts, provider_limits=state.limits)
            original_limits = {content_hash(item.to_dict()) for item in state.limits}
            try:
                providers = provider_registry(http)
                if args.command == "discover":
                    run_discovery(state, providers, policy)
                elif args.command == "inspect-skills":
                    run_skill_inspection(state, _read(args.input), providers, policy)
                else:
                    try:
                        ids = json.loads(args.ids)
                    except ValueError:
                        ids = _read(args.ids)
                    if not isinstance(ids, list) or any(type(cid) is not str for cid in ids):
                        raise ContractError("enrich.ids", "requires a JSON array of IDs")
                    if args.command == "inventory-skills":
                        run_skill_inventory(state, ids, providers, policy)
                    else:
                        run_enrichment(state, ids, providers, policy)
            finally:
                _sync_http(state, http, original_limits)
                save_run(state, run_dir)
            code = 3 if not state.candidates and state.request_counts.get("workflow_last_failures", 0) and not state.request_counts.get("workflow_last_successes", 0) else 0
            return code, _summary(state)
        save_run(state, run_dir)
        return 0, _summary(state)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as error:
        return int(error.code)
    try:
        code, result = _execute(args)
    except ContractError as error:
        print(json.dumps({"error": error.path, "reason": error.reason}, ensure_ascii=False), file=sys.stderr)
        return 2
    except (OSError, UnicodeError):
        print(json.dumps({"error": "filesystem", "reason": "Cannot complete filesystem operation"}), file=sys.stderr)
        return 2
    print(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, allow_nan=False))
    return code
