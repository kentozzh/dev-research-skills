"""Strict JSON conversion and cross-record contract validation (no network I/O)."""
from __future__ import annotations

import json
import math
import types
from dataclasses import MISSING, fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints
from urllib.parse import parse_qsl, urlsplit

from .cache import SECRET_KEYS


class ContractError(ValueError):
    """An invalid field; ``path`` and ``reason`` are safe for user diagnostics."""

    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"{path}: {reason}")


def _fail(path: str, reason: str) -> None:
    raise ContractError(path, reason)


def _json_value(value: Any, path: str) -> Any:
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            _fail(path, "must be finite")
        return value
    if isinstance(value, list):
        return [_json_value(v, f"{path}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, dict):
        if any(type(k) is not str for k in value):
            _fail(path, "object keys must be strings")
        return {k: _json_value(v, f"{path}.{k}") for k, v in value.items()}
    _fail(path, "must be a JSON value")


def _decode(value: Any, annotation: Any, path: str) -> Any:
    if annotation is Any:
        return _json_value(value, path)
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, types.UnionType):
        for option in args:
            try:
                return _decode(value, option, path)
            except ContractError:
                pass
        _fail(path, "does not match the allowed type")
    if origin is Literal:
        if not any(type(value) is type(option) and value == option for option in args):
            _fail(path, "invalid enum value")
        return value
    if annotation is type(None):
        if value is not None:
            _fail(path, "must be null")
        return None
    if annotation is datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
            if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
                _fail(path, "timestamp must include a timezone")
            return parsed.astimezone(timezone.utc)
        except (ValueError, OverflowError):
            _fail(path, "invalid timezone-aware timestamp")
    if origin in (dict, list):
        if type(value) is not origin:
            _fail(path, f"must be a {origin.__name__}")
        if origin is list:
            return [_decode(v, args[0], f"{path}[{i}]") for i, v in enumerate(value)]
        return {_decode(k, args[0], path): _decode(v, args[1], f"{path}.{k}") for k, v in value.items()}
    if isinstance(annotation, type) and is_dataclass(annotation):
        if type(value) is annotation:
            validate_contract(value)
            return value
        return decode_contract(annotation, value, path)
    if annotation in (str, int, bool, float):
        valid = type(value) in (int, float) if annotation is float else type(value) is annotation
        if not valid:
            _fail(path, f"must be {annotation.__name__}")
        if annotation is float:
            if not math.isfinite(value):
                _fail(path, "must be finite")
            return float(value)
        return value
    _fail(path, "unsupported contract type")


def decode_contract(cls, payload: dict, path: str):
    if type(payload) is not dict:
        _fail(path, "must be an object")
    known = {f.name: f for f in fields(cls)}
    for key in payload:
        if key not in known:
            _fail(f"{path}.{key}", "unknown field")
    hints = get_type_hints(cls)
    converted = {}
    for name, f in known.items():
        if name in payload:
            converted[name] = _decode(payload[name], hints[name], f"{path}.{name}")
        elif f.default is MISSING and f.default_factory is MISSING:
            _fail(f"{path}.{name}", "required field missing")
    try:
        return cls(**converted)
    except ContractError as exc:
        old_prefix = cls.__name__
        if exc.path.startswith(old_prefix):
            raise ContractError(path + exc.path[len(old_prefix):], exc.reason) from None
        raise


def encode_value(value: Any) -> Any:
    if is_dataclass(value):
        return value.to_dict()
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {k: encode_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [encode_value(v) for v in value]
    return value


def _count(value: Any, path: str, *, positive: bool = False) -> None:
    if type(value) is not int or value < (1 if positive else 0):
        _fail(path, "must be a positive integer" if positive else "must be a nonnegative integer")


def _fraction(value: Any, path: str) -> None:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        _fail(path, "must be a finite number in [0, 1]")


def _unique(values: list, path: str) -> None:
    if len(values) != len(set(values)):
        _fail(path, "duplicate identifiers")


def _weights(values: dict, path: str, expected_keys: set[str] | None = None) -> None:
    if expected_keys is not None:
        _known_keys(values, expected_keys, path)
    if not values:
        _fail(path, "weights cannot be empty")
    for key, value in values.items():
        _fraction(value, f"{path}.{key}")
    if not math.isclose(sum(values.values()), 1.0, abs_tol=1e-9):
        _fail(path, "weights must sum to 1")


def _known_keys(values: dict, expected: set[str], path: str) -> None:
    extra = set(values) - expected
    if extra:
        _fail(f"{path}.{sorted(extra)[0]}", "unknown field")
    missing = expected - set(values)
    if missing:
        _fail(f"{path}.{sorted(missing)[0]}", "required field missing")


def _safe_url(value: str, path: str) -> None:
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError:
        _fail(path, "malformed URL")
    sensitive = {"token", "access_token", "api_key", "apikey", "authorization", "password", "key"}
    if parsed.username or parsed.password or any(k.lower() in sensitive for k, _ in parse_qsl(parsed.query)):
        _fail(path, "credentials must be removed from URLs")
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        _fail(path, "must be an absolute HTTP(S) URL")


def reportable_url(url: object) -> bool:
    """Whether an upstream URL can be persisted and shown as a public source."""
    if not isinstance(url, str) or "\\" in url or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        return False
    try:
        _safe_url(url, "source URL")
    except ContractError:
        return False
    parsed = urlsplit(url)
    if not parsed.hostname:
        return False
    secrets = SECRET_KEYS | {"signature", "sig", "awsaccesskeyid", "googleaccessid"}
    return not any(key.lower() in secrets or key.lower().startswith(("x-amz-", "x-goog-"))
                   for field in (parsed.query, parsed.fragment) for key, _ in parse_qsl(field, keep_blank_values=True))


def validate_contract(obj) -> None:
    """Validate and normalize a dataclass, including direct constructor calls."""
    from . import contracts as c

    prefix = type(obj).__name__
    hints = get_type_hints(type(obj))
    for f in fields(obj):
        normalized = _decode(getattr(obj, f.name), hints[f.name], f"{prefix}.{f.name}")
        setattr(obj, f.name, normalized)

    def path(name):
        return f"{prefix}.{name}"

    for f in fields(obj):
        value = getattr(obj, f.name)
        if f.name.endswith("_id") and isinstance(value, str) and not value.strip():
            _fail(path(f.name), "identifier cannot be empty")
        if f.name.endswith("evidence_ids"):
            _unique(value, path(f.name))
            if any(not item.strip() for item in value):
                _fail(path(f.name), "evidence identifiers cannot be empty")
    if hasattr(obj, "status") and obj.status == "verified" and hasattr(obj, "evidence_ids") and not obj.evidence_ids:
        _fail(path("evidence_ids"), "verified values require evidence")
    if hasattr(obj, "source_url"):
        _safe_url(obj.source_url, path("source_url"))

    if isinstance(obj, c.QuerySpec):
        if not obj.provider.strip() or not obj.query.strip():
            _fail(prefix, "provider and query cannot be empty")
    elif isinstance(obj, c.RequestContract):
        if obj.schema_version != "1.0":
            _fail(path("schema_version"), "unsupported schema version")
        if obj.policy_version != "1.0":
            _fail(path("policy_version"), "unsupported policy version")
        if not obj.raw_request.strip():
            _fail(path("raw_request"), "request cannot be empty")
        if obj.contract_revision is not None:
            _count(obj.contract_revision, path("contract_revision"), positive=True)
        if any(not k.strip() or not v.strip() for k, v in obj.hard_constraints.items()):
            _fail(path("hard_constraints"), "constraint IDs and descriptions cannot be empty")
        _unique([q.query_id for q in obj.queries], path("queries.query_id"))
    elif isinstance(obj, c.Evidence):
        if not obj.check_method.strip():
            _fail(path("check_method"), "must describe how the source was checked")
        if obj.status == "verified" and not obj.excerpt.strip():
            _fail(path("excerpt"), "verified evidence needs a short supporting excerpt")
    elif isinstance(obj, c.Metric):
        if obj.status == "verified" and obj.value is None:
            _fail(path("value"), "verified metric cannot be null")
        if obj.status in ("unavailable", "not_applicable", "failed") and obj.value is not None:
            _fail(path("value"), "missing metrics must use null")
        if obj.value is not None:
            if obj.unit in ("count", "days", "year"):
                _count(obj.value, path("value"))
            elif obj.unit in ("percentile", "fraction", "ratio", "coverage"):
                _fraction(obj.value, path("value"))
    elif isinstance(obj, (c.ScoreAssessment, c.RelevanceAssessment, c.ConditionAssessment)):
        if not obj.reason.strip():
            _fail(path("reason"), "judgments require a reason")
        if isinstance(obj, c.ScoreAssessment):
            if obj.value not in (None, 0, 25, 50, 75, 100):
                _fail(path("value"), "score must be null or 0/25/50/75/100")
            if obj.status == "verified" and obj.value is None:
                _fail(path("value"), "verified score cannot be null")
            if obj.status != "verified" and obj.value is not None:
                _fail(path("value"), "unverified score must be null")
        elif isinstance(obj, c.RelevanceAssessment):
            if (obj.status == "verified") != (obj.level is not None):
                _fail(path("level"), "only verified relevance may have a level")
        elif (obj.result != "pending") != (obj.status == "verified"):
            _fail(path("result"), "pass/fail requires verified evidence; unverified results must be pending")
    elif isinstance(obj, c.Assessment):
        _count(obj.contract_revision, path("contract_revision"), positive=True)
        if not obj.reason.strip():
            _fail(path("reason"), "assessment requires a reason")
    elif isinstance(obj, c.ProviderLimit):
        if obj.remaining is not None:
            _count(obj.remaining, path("remaining"))
    elif isinstance(obj, c.ObservationBatch):
        _unique([event.event_id for event in obj.host_search_events], path("host_search_events.event_id"))
    elif isinstance(obj, c.RunState):
        if obj.request.contract_revision is None:
            _fail(path("request.contract_revision"), "stored runs need an assigned revision")
        for key, value in obj.request_counts.items():
            _count(value, path(f"request_counts.{key}"))
        for name, identity in (("candidates", "candidate_id"), ("evidence", "evidence_id"), ("assessments", "candidate_id")):
            if any(key != getattr(value, identity) for key, value in getattr(obj, name).items()):
                _fail(path(name), "mapping key must match record identity")
    elif isinstance(obj, c.ComparisonGroup):
        _unique(obj.member_ids, path("member_ids"))
        _weights(obj.effective_weights, path("effective_weights"))
    elif isinstance(obj, c.CohortManifest):
        _count(obj.year, path("year"), positive=True)
        _count(obj.N, path("N"))
        _unique(obj.member_ids, path("member_ids"))
        if obj.complete and len(obj.member_ids) != obj.N:
            _fail(path("N"), "complete manifest size must equal N")
    elif isinstance(obj, c.CohortSummary):
        for key in ("H", "n_h", "Z", "n_c", "N"):
            _count(getattr(obj, key), path(key))
        if not obj.H <= obj.n_h <= obj.N or not obj.Z <= obj.n_c <= obj.N:
            _fail(prefix, "counts require H <= n_h <= N and Z <= n_c <= N")
        for key in ("high_ratio", "zero_ratio", "high_coverage", "zero_coverage", "high_lower", "high_upper", "zero_lower", "zero_upper"):
            if getattr(obj, key) is not None:
                _fraction(getattr(obj, key), path(key))
    elif isinstance(obj, c.VenueRecord):
        for key in ("acceptance_numerator", "acceptance_denominator"):
            if getattr(obj, key) is not None:
                _count(getattr(obj, key), path(key))
        if obj.acceptance_numerator is not None and obj.acceptance_denominator is not None and obj.acceptance_numerator > obj.acceptance_denominator:
            _fail(path("acceptance_numerator"), "cannot exceed denominator")
    elif isinstance(obj, c.GithubPolicy):
        if obj.minimum_repository_stars < c.MIN_REPOSITORY_STARS:
            _fail(path("minimum_repository_stars"), f"requires at least {c.MIN_REPOSITORY_STARS} stars")
    elif isinstance(obj, c.TransportPolicy):
        _count(obj.max_retries, path("max_retries"))
        if obj.timeout_seconds <= 0:
            _fail(path("timeout_seconds"), "must be positive")
        if obj.max_wait_seconds <= 0:
            _fail(path("max_wait_seconds"), "must be positive")
        if obj.arxiv_interval_seconds < 3:
            _fail(path("arxiv_interval_seconds"), "must respect the minimum three-second interval")
    elif isinstance(obj, c.Policy):
        _validate_policy(obj)
    elif isinstance(obj, (c.BudgetPolicy, c.CapacityPolicy, c.CachePolicy, c.MaintenanceBand)):
        for f in fields(obj):
            if hints[f.name] is int:
                _count(getattr(obj, f.name), path(f.name))
        if isinstance(obj, c.CapacityPolicy):
            for child, parent in (("github_deep", "github_initial"), ("paper_deep", "paper_initial"), ("paper_read", "paper_deep")):
                if getattr(obj, child) > getattr(obj, parent):
                    _fail(path(child), f"cannot exceed {parent}")


def _validate_policy(policy) -> None:
    if policy.schema_version != "1.0" or policy.policy_version != "1.0":
        _fail("Policy.policy_version", "unsupported policy/schema version")
    weight_keys = {"skill-finding": {"U", "P", "M"}, "tool-finding": {"U", "P", "M"}, "paper-finding": {"L", "I", "V"}}
    _known_keys(policy.weights, set(weight_keys), "Policy.weights")
    for skill, expected in weight_keys.items():
        _weights(policy.weights[skill], f"Policy.weights.{skill}", expected)
    _weights(policy.github.popularity_weights, "Policy.github.popularity_weights", {"stars", "forks", "watch"})
    _weights(policy.github.without_watch_weights, "Policy.github.without_watch_weights", {"stars", "forks"})
    _known_keys(policy.github.log_caps, {"stars", "forks", "watch"}, "Policy.github.log_caps")
    for key, value in policy.github.log_caps.items():
        _count(value, f"Policy.github.log_caps.{key}", positive=True)
    _weights(policy.paper.route_budget_shares, "Policy.paper.route_budget_shares", {"recent", "classic"})
    _weights(policy.paper.no_venue_weights, "Policy.paper.no_venue_weights", {"L", "I"})
    _weights(policy.paper.landing_only_weights, "Policy.paper.landing_only_weights", {"L"})
    _known_keys(policy.paper.ccf_scores, {"A", "B", "C"}, "Policy.paper.ccf_scores")
    _known_keys(policy.paper.award_bonus, {"best_paper", "outstanding", "distinguished", "honorable_mention"}, "Policy.paper.award_bonus")
    for name, values in (("ccf_scores", policy.paper.ccf_scores), ("award_bonus", policy.paper.award_bonus)):
        for key, value in values.items():
            _count(value, f"Policy.paper.{name}.{key}")
    _fraction(policy.paper.venue_coverage_threshold, "Policy.paper.venue_coverage_threshold")
    _known_keys(policy.assessment_items, set(ASSESSMENT_ITEMS), "Policy.assessment_items")
    for skill, supported in ASSESSMENT_ITEMS.items():
        items = policy.assessment_items[skill]
        path = f"Policy.assessment_items.{skill}"
        _unique(items, path)
        if set(items) != set(supported):
            _fail(path, "must contain exactly the schema 1.0 assessment subitems")
    _known_keys(policy.qualitative_fact_fields, {"github", "paper"}, "Policy.qualitative_fact_fields")
    bands = policy.maintenance.bands
    if not bands or any(a.max_days >= b.max_days for a, b in zip(bands, bands[1:])):
        _fail("Policy.maintenance.bands", "day bounds must be strictly increasing")
    for key in ("older_score", "archived_score"):
        value = getattr(policy.maintenance, key)
        _count(value, f"Policy.maintenance.{key}")
        if value > 100:
            _fail(f"Policy.maintenance.{key}", "score cannot exceed 100")
    if any(b.score > 100 for b in bands):
        _fail("Policy.maintenance.bands", "score cannot exceed 100")
    for key in ("recent_months", "maximum_index"):
        _count(getattr(policy.paper, key), f"Policy.paper.{key}", positive=True)
    for offset in policy.paper.mature_year_offsets:
        _count(offset, "Policy.paper.mature_year_offsets", positive=True)
    _fraction(policy.ranking.sensitivity_weight_delta, "Policy.ranking.sensitivity_weight_delta")
    if policy.ranking.close_score_difference < 0:
        _fail("Policy.ranking.close_score_difference", "must be nonnegative")
    _count(policy.ranking.empty_group_qualitative_limit, "Policy.ranking.empty_group_qualitative_limit")
    # Windows Python often ships without an IANA database. These two required
    # display zones have unambiguous modern offsets; other zones need tzdata.
    if policy.report_timezone not in ("Asia/Shanghai", "UTC"):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(policy.report_timezone)
        except (ZoneInfoNotFoundError, ValueError):
            _fail("Policy.report_timezone", "unknown timezone or timezone database unavailable")


ARCHITECTURE_CONDITION = "有可核查的模块或数据流设计"


def validate_request(payload: dict):
    """Validate unassigned user input; only run storage may allocate a revision."""
    from .contracts import RequestContract
    if type(payload) is not dict:
        _fail("RequestContract", "must be an object")
    if payload.get("contract_revision") is not None:
        _fail("RequestContract.contract_revision", "revision is assigned by run storage")
    request = RequestContract.from_dict(payload)
    for key, skill, choices in (
        ("tool_intent", "tool-finding", ("architecture_reference", "component_reuse")),
        ("paper_intent", "paper-finding", ("framework_discovery", "method_evidence")),
    ):
        if key not in request.preferences:
            continue
        path = f"RequestContract.preferences.{key}"
        if request.skill != skill:
            _fail(path, f"only supported for {skill}")
        if request.preferences[key] not in choices:
            _fail(path, "requires " + " or ".join(choices))
    return request


ASSESSMENT_ITEMS = {
    "skill-finding": ("host_tools", "dependencies_permissions", "installation", "io_examples"),
    "tool-finding": ("functionality", "stack", "resources", "documentation"),
    "paper-finding": ("task_transfer", "artifacts", "resources", "reproducibility"),
}


def validate_assessment(payload: dict, request, snapshot_id: str, evidence, candidate):
    """Validate structure plus checked, subject-linked support for judgments."""
    from .contracts import Assessment
    from .evidence import supports_assessment_subject, require_references
    assessment = Assessment.from_dict(payload)
    if assessment.candidate_id != candidate.candidate_id:
        _fail("Assessment.candidate_id", "assessment must identify the supplied candidate")
    if request.contract_revision is None or assessment.contract_revision != request.contract_revision:
        _fail("Assessment.contract_revision", "assessment revision does not match the stored request")
    if assessment.snapshot_id != snapshot_id:
        _fail("Assessment.snapshot_id", "assessment snapshot does not match current data")
    if set(assessment.hard_constraints) != set(request.hard_constraints):
        _fail("Assessment.hard_constraints", "must evaluate every requested hard condition exactly once")
    scores = assessment.landing if request.skill == "paper-finding" else assessment.usability
    unused = assessment.usability if request.skill == "paper-finding" else assessment.landing
    if set(scores) != set(ASSESSMENT_ITEMS[request.skill]) or unused:
        _fail("Assessment.landing" if request.skill == "paper-finding" else "Assessment.usability", "must evaluate exactly the configured subitems; use null for unknown")

    def check_refs(value, path):
        if is_dataclass(value):
            if getattr(value, "status", None) == "verified":
                require_references(value.evidence_ids, evidence, path + ".evidence_ids", verified=True)
                if any(not supports_assessment_subject(evidence[eid], candidate, evidence) for eid in value.evidence_ids):
                    _fail(path + ".evidence_ids", "evidence subject and path scope must support this candidate or its explicit shared repository")
            for f in fields(value):
                check_refs(getattr(value, f.name), f"{path}.{f.name}")
        elif isinstance(value, dict):
            for key, item in value.items():
                check_refs(item, f"{path}.{key}")
        elif isinstance(value, list):
            if path.endswith("evidence_ids"):
                if set(value) - evidence.keys():
                    _fail(path, "references unknown evidence identifiers")
            else:
                for i, item in enumerate(value):
                    check_refs(item, f"{path}[{i}]")
    check_refs(assessment, "Assessment")
    if request.skill == "tool-finding" and request.preferences.get("tool_intent") == "architecture_reference":
        for key, description in request.hard_constraints.items():
            condition = assessment.hard_constraints[key]
            if description != ARCHITECTURE_CONDITION or condition.result != "pass":
                continue
            if not any(_is_architecture_source(evidence[eid]) for eid in condition.evidence_ids):
                _fail(f"Assessment.hard_constraints.{key}.evidence_ids",
                      "verified architecture requires checked source code or a design document")
    return assessment


def _is_architecture_source(item):
    if item.scope.get("architecture_evidence") not in ("source", "design_document"):
        return False
    if item.source_category in {"repository", "official"}:
        return True
    return (item.source_category == "api" and item.scope.get("level") == "file"
            and item.source_object.get("truncated") is False
            and isinstance(item.source_object.get("content_text"), str)
            and bool(item.source_object["content_text"].strip()))


def load_policy(path: Path):
    """Read a strict versioned JSON policy; malformed input is a ContractError."""
    from .contracts import Policy
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        _fail("Policy", "cannot read valid policy JSON")
    return Policy.from_dict(payload)
