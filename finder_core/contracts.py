"""Typed JSON contracts. Use ``Type.from_dict`` and ``instance.to_dict`` at boundaries.

Constructors apply the same validation as deserialization. Timestamps normalize to
UTC and serialize as RFC 3339 strings; null always remains distinct from zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any, Literal, TypeVar

Status = Literal["verified", "unavailable", "not_applicable", "conflict", "failed", "stale"]
Skill = Literal["skill-finding", "tool-finding", "paper-finding"]
T = TypeVar("T", bound="Contract")
MIN_REPOSITORY_STARS = 10_000


class Contract:
    def __post_init__(self) -> None:
        from .validation import validate_contract
        validate_contract(self)

    @classmethod
    def from_dict(cls: type[T], payload: dict[str, Any]) -> T:
        from .validation import decode_contract
        return decode_contract(cls, payload, cls.__name__)

    def to_dict(self) -> dict[str, Any]:
        from .validation import encode_value, validate_contract
        validate_contract(self)
        return {f.name: encode_value(getattr(self, f.name)) for f in fields(self)}


@dataclass
class QuerySpec(Contract):
    provider: str
    query: str
    route: Literal["recent", "classic", "general"]
    query_id: str


@dataclass
class RequestContract(Contract):
    skill: Skill
    raw_request: str
    hard_constraints: dict[str, str] = field(default_factory=dict)
    preferences: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    queries: list[QuerySpec] = field(default_factory=list)
    schema_version: str = "1.0"
    policy_version: str = "1.0"
    contract_revision: int | None = None
    deep_venue_stats: bool = False


@dataclass
class Evidence(Contract):
    evidence_id: str
    source_url: str
    subject_id: str
    fetched_at: datetime
    scope: dict[str, Any]
    excerpt: str
    source_category: Literal["api", "official", "repository", "paper", "host_search", "third_party", "agent"]
    status: Status
    check_method: str
    source_object: dict[str, Any] = field(default_factory=dict)


@dataclass
class Metric(Contract):
    value: Any
    status: Status
    unit: str
    provider: str
    subject_id: str
    fetched_at: datetime
    scope: dict[str, Any]
    evidence_ids: list[str]
    method_version: str


@dataclass
class IdentityRelation(Contract):
    source_id: str
    target_id: str
    relation: Literal["same_work", "version_of", "fork_of", "mirror_of", "upstream_of", "moved_to", "possible_match"]
    evidence_ids: list[str]
    status: Status = "verified"
    reason: str = ""


@dataclass
class Candidate(Contract):
    candidate_id: str
    kind: Literal["skill", "tool", "paper"]
    identifiers: dict[str, str] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)
    urls: dict[str, str] = field(default_factory=dict)
    versions: list[str] = field(default_factory=list)
    relations: list[IdentityRelation] = field(default_factory=list)
    metrics: dict[str, Metric] = field(default_factory=dict)
    discovery_evidence_ids: list[str] = field(default_factory=list)


@dataclass
class ConditionAssessment(Contract):
    result: Literal["pass", "fail", "pending"]
    status: Status
    evidence_ids: list[str]
    reason: str


@dataclass
class RelevanceAssessment(Contract):
    level: Literal["R0", "R1", "R2", "R3", "R4"] | None
    status: Status
    evidence_ids: list[str]
    reason: str


@dataclass
class ScoreAssessment(Contract):
    value: int | None
    status: Status
    evidence_ids: list[str]
    reason: str


@dataclass
class Assessment(Contract):
    candidate_id: str
    contract_revision: int
    snapshot_id: str
    hard_constraints: dict[str, ConditionAssessment]
    relevance: RelevanceAssessment
    usability: dict[str, ScoreAssessment] = field(default_factory=dict)
    landing: dict[str, ScoreAssessment] = field(default_factory=dict)
    reading_depth: Literal["metadata", "abstract", "readme", "source", "full_text"] = "metadata"
    reason: str = ""


@dataclass
class ProviderLimit(Contract):
    provider: str
    remaining: int | None = None
    reset_at: datetime | None = None
    reason: str = ""


@dataclass
class HostSearchEvent(Contract):
    event_id: str
    query: str
    searched_at: datetime


@dataclass
class ObservationBatch(Contract):
    candidates: list[Candidate] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    identity_relations: list[IdentityRelation] = field(default_factory=list)
    provider_limits: list[ProviderLimit] = field(default_factory=list)
    host_search_events: list[HostSearchEvent] = field(default_factory=list)


@dataclass
class ProviderBatch(Contract):
    candidates: list[Candidate] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    provider_limits: list[ProviderLimit] = field(default_factory=list)
    partial: bool = False
    next_cursor: str | None = None


@dataclass
class SourceDocument(Contract):
    subject_id: str
    source_url: str
    path: str
    ref: str
    content_text: str
    truncated: bool
    fetched_at: datetime
    evidence_ids: list[str]


@dataclass
class FileEntry(Contract):
    path: str
    type: Literal["file", "directory", "symlink", "submodule"]


@dataclass
class FileInventory(Contract):
    repo_id: str
    ref: str
    entries: list[FileEntry]
    truncated: bool
    evidence_ids: list[str]


@dataclass
class RunState(Contract):
    run_id: str
    request: RequestContract
    snapshot_id: str
    candidates: dict[str, Candidate] = field(default_factory=dict)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    assessments: dict[str, Assessment] = field(default_factory=dict)
    invalidated: bool = False
    invalidation_reason: str | None = None
    limits: list[ProviderLimit] = field(default_factory=list)
    host_search_events: list[HostSearchEvent] = field(default_factory=list)
    request_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class BudgetPolicy(Contract):
    host_search: int
    github_authenticated: int
    github_anonymous: int
    paper_structured: int


@dataclass
class CapacityPolicy(Contract):
    formal: int
    supplementary: int
    skills_per_repository: int
    github_initial: int
    github_deep: int
    paper_initial: int
    paper_deep: int
    paper_read: int


@dataclass
class CachePolicy(Contract):
    counts_seconds: int
    queries_seconds: int
    paper_identity_seconds: int
    sha_files_indefinite: bool


@dataclass
class MaintenanceBand(Contract):
    max_days: int
    score: int


@dataclass
class MaintenancePolicy(Contract):
    bands: list[MaintenanceBand]
    older_score: int
    archived_score: int
    unknown_score: None


@dataclass
class GithubPolicy(Contract):
    popularity_weights: dict[str, float]
    log_caps: dict[str, int]
    without_watch_weights: dict[str, float]
    required_group_metrics: list[str]
    minimum_repository_stars: int = MIN_REPOSITORY_STARS


@dataclass
class PaperPolicy(Contract):
    recent_months: int
    route_budget_shares: dict[str, float]
    ccf_scores: dict[str, int]
    award_bonus: dict[str, int]
    award_aggregation: Literal["max"]
    maximum_index: int
    no_venue_weights: dict[str, float]
    landing_only_weights: dict[str, float]
    group_order: list[str]
    venue_coverage_threshold: float
    mature_year_offsets: list[int]


@dataclass
class RankingPolicy(Contract):
    formal_relevance: list[str]
    formal_order: list[str]
    qualitative_order: list[str]
    close_score_difference: float
    sensitivity_weight_delta: float
    freeze_before_limits: bool
    hard_constraints_first: bool
    empty_group_qualitative_limit: int


@dataclass
class TransportPolicy(Contract):
    max_retries: int = 2
    timeout_seconds: float = 30.0
    max_wait_seconds: float = 120.0
    arxiv_interval_seconds: float = 3.0


@dataclass
class Policy(Contract):
    schema_version: str
    policy_version: str
    weights: dict[str, dict[str, float]]
    budgets: BudgetPolicy
    capacity: CapacityPolicy
    cache: CachePolicy
    maintenance: MaintenancePolicy
    github: GithubPolicy
    paper: PaperPolicy
    ranking: RankingPolicy
    assessment_items: dict[str, list[str]]
    qualitative_fact_fields: dict[str, list[str]]
    report_timezone: str
    external_read_only: bool
    execute_candidates: bool
    auto_create_accounts: bool
    auto_purchase_quota: bool
    auto_enable_services: bool
    transport: TransportPolicy = field(default_factory=TransportPolicy)


@dataclass
class ComparisonGroup(Contract):
    member_ids: list[str]
    mode: Literal["github", "full_paper", "no_venue", "landing_only"]
    effective_weights: dict[str, float]
    frozen_snapshot_id: str
    missing_reasons: dict[str, str] = field(default_factory=dict)
    omitted_items: dict[str, str] = field(default_factory=dict)


@dataclass
class RankedReport(Contract):
    group: ComparisonGroup | None = None
    formal: list[str] = field(default_factory=list)
    qualitative: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    same_repository_supplementary: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    sensitivity: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class CohortManifest(Contract):
    venue: str
    year: int
    track: str
    type: str
    member_ids: list[str]
    N: int
    source_urls: list[str]
    exclusion_rules: list[str]
    database: str
    queried_at: datetime
    complete: bool
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class CohortSummary(Contract):
    H: int
    n_h: int
    Z: int
    n_c: int
    N: int
    high_ratio: float | None = None
    zero_ratio: float | None = None
    high_coverage: float | None = None
    zero_coverage: float | None = None
    high_lower: float | None = None
    high_upper: float | None = None
    zero_lower: float | None = None
    zero_upper: float | None = None
    comparable: bool = False
    missing_reasons: list[str] = field(default_factory=list)
    manifests: list[CohortManifest] = field(default_factory=list)
    calculation_method: str = ""
    high_window: str = ""
    zero_window: str = ""


@dataclass
class VenueEdition(Contract):
    year: int
    ended: bool | None
    evidence_ids: list[str]


@dataclass
class VenueRecord(Contract):
    version: str
    venue_id: str
    aliases: list[str]
    applicable_types: list[str]
    applicable_tracks: list[str]
    editions: list[VenueEdition] = field(default_factory=list)
    ccf: Metric | None = None
    acceptance_numerator: int | None = None
    acceptance_denominator: int | None = None
    acceptance_scope: str = ""
    acceptance_evidence_ids: list[str] = field(default_factory=list)
    award_scope: dict[str, Any] = field(default_factory=dict)
    award_evidence_ids: list[str] = field(default_factory=list)
