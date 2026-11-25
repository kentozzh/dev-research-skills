# Finder contracts, schema 1.0 / policy 1.0

`finder_core/contracts.py` is the shared source of truth. It provides Python 3.11+
dataclasses for all three skills. `finder_core.__version__` is `1.0.0`; the JSON
schema and scoring policy each use version `1.0`. Distributed copies must be
generated from this shared source rather than edited independently.

## JSON boundary and errors

Every dataclass supports `Type.from_dict(payload)` and `instance.to_dict()`.
Nested dictionaries become typed nested dataclasses; serialization produces only
JSON values. Both constructors and deserialization validate. Unknown dataclass
fields and unknown policy configuration keys fail rather than being ignored.
There is no implicit string-to-number or integer-to-boolean conversion.

```python
import json
from pathlib import Path
from finder_core.contracts import Metric, RequestContract, RunState
from finder_core.validation import load_policy, validate_request

policy = load_policy(Path("finder_core/resources/policy-v1.json"))
request = validate_request({"skill": "tool-finding", "raw_request": "Offline search"})
assert request.contract_revision is None

# Run storage owns revision allocation. Never accept this value from user input.
stored_request = RequestContract.from_dict({**request.to_dict(), "contract_revision": 1})
state = RunState(run_id="run:example", request=stored_request, snapshot_id="snapshot:1")
encoded = json.dumps(state.to_dict(), ensure_ascii=False, allow_nan=False)
restored = RunState.from_dict(json.loads(encoded))
```

Failures use `finder_core.validation.ContractError`, a `ValueError` subclass with
`path` and `reason` attributes. Its string form is `field.path: short reason`.
Error messages do not echo rejected field values. Catch this exception at CLI and
provider/import boundaries. `load_policy` also wraps unreadable/malformed JSON.

All timestamps accept timezone-aware `datetime` objects or ISO 8601 strings and
normalize to UTC. Serialized UTC timestamps end in `Z`. Naive dates/times fail.
The display default is Asia/Shanghai; reporting is responsible for formatting.
Windows can load the default policy without an IANA timezone database. Other
configured display zones require the platform IANA database or `tzdata`.

Status literals are exactly `verified`, `unavailable`, `not_applicable`,
`conflict`, `failed`, and `stale`. Display code may translate them. Null represents
unknown and remains different from a measured zero. All JSON floats must be
finite, including floats in extension dictionaries. Counts are nonnegative
integers and reject booleans; `percentile`, `fraction`, `ratio`, and `coverage`
metric units require a number in [0, 1]. A verified metric requires a non-null
value and evidence; unavailable/not-applicable/failed metrics require null.
Stale/conflicting metrics may retain a previously observed value with their
explicit status. Strings such as licenses or dates may be metric values.

Evidence and source-document URLs must be absolute HTTP(S) URLs without embedded
credentials or recognized credential query parameters. Producers must redact
credentials from free text, queries, and source objects before constructing these
contracts. URL checks are an additional boundary check, not a general redactor.

## Request and assessment fields

`RequestContract` requires `skill` (`skill-finding`, `tool-finding`, or
`paper-finding`) and nonempty `raw_request`. The remaining fields default to:

| Field | Type / default |
|---|---|
| schema_version, policy_version | `"1.0"`, `"1.0"` |
| hard_constraints | `dict[str, str]`, empty; stable condition ID → description |
| preferences | JSON object, empty; preferences/extensions are explicit data |
| assumptions | `list[str]`, empty |
| queries | `list[QuerySpec]`, empty |
| contract_revision | positive integer for stored requests; null before prepare |
| deep_venue_stats | boolean, false |

`validate_request(payload: dict) -> RequestContract` is the untrusted request
boundary: `contract_revision` must be absent or null. `prepare_run` assigns 1 and
`revise_run` increments the stored revision. Trusted stored data is loaded with
`RequestContract.from_dict`, which accepts positive assigned revisions. Revision
allocation and invalidating previous evaluations are run-storage responsibilities.

New requests may set these optional preference keys.

| Key | Skill | Values | Behavior when omitted |
|---|---|---|---|
| `tool_intent` | `tool-finding` | `architecture_reference`, `component_reuse` | Component reuse |
| `paper_intent` | `paper-finding` | `framework_discovery`, `method_evidence` | Existing paper research workflow |

The input boundary rejects a reserved intent key on a different skill and rejects
unsupported values. The keys remain optional in serialized requests. Loading
or saving old runs preserves their request data and snapshot hashes. Using
`revise` to change intent assigns a new revision and invalidates the previous
assessments. The discovery and request ledger stay with the run.

Preparation preserves every supplied hard condition. Skill reuse and tool
component reuse require a condition that the license explicitly covers the
intended reuse. Tool architecture reference requires a condition that the
module or data-flow design can be checked. Preparation uses a fresh condition
ID if the usual key is occupied. Paper requests may state a license requirement
when they include implementation reuse.

Tool and skill recommendations require at least 10,000 verified GitHub stars on
the project repository or the repository containing the concrete skill. This
minimum applies before scoring, including for imported observations. A count
below the minimum or an unverified count can appear in the exclusion record.
Imported counts need a checked GitHub page or API response for that repository.
Skills sharing an immutable repository ID use its latest observed count.

`QuerySpec` requires `provider`, `query`, `route` (`recent`, `classic`, `general`),
and `query_id`. Query IDs are unique within a request. Credentials do not belong
in queries.

`Assessment` requires `candidate_id`, positive `contract_revision`, `snapshot_id`,
`hard_constraints`, `relevance`, and nonempty `reason`. `reading_depth` is one of
`metadata` (default), `abstract`, `readme`, `source`, or `full_text`. `usability`
and `landing` are dictionaries of typed `ScoreAssessment` values, default empty.

| Nested judgment | Fields |
|---|---|
| ConditionAssessment | `result`: pass/fail/pending; `status`, `evidence_ids`, nonempty `reason` |
| RelevanceAssessment | `level`: R0–R4 or null; `status`, `evidence_ids`, nonempty `reason` |
| ScoreAssessment | `value`: 0/25/50/75/100 or null; `status`, `evidence_ids`, nonempty `reason` |

Pass/fail requires verified evidence; other conditions are pending. Verified
relevance requires a level; unverified relevance uses null. Verified scores
require a value and evidence; unverified scores use null. An explicitly
not-applicable score remains a recorded subitem; the ranking stage may remove
it only if the request authorizes the same omission for the whole group.

`validate_assessment(payload, request, snapshot_id, evidence, candidate) -> Assessment`
rejects an unassigned request, old revision, different snapshot, unknown evidence
IDs, omitted/extra hard-condition decisions, and missing/extra score subitems.
`evidence` is the complete Evidence mapping and `candidate` the assessed Candidate;
the earlier ID-set-only signature is replaced. Each verified hard-condition,
relevance, usability or landing judgment requires verified checked sources
(host-search and Agent summaries are discovery only), all tied to the candidate
subject, retained alias/merged source identity, or an explicit `scope.subject_ids`
link. A concrete skill may share its identified repository's sources, including
`github:<repository ID>` and `github:<owner/name>`; sibling skill evidence is not
automatically shared. CLI assessment and ranking both enforce this boundary.
For skills, explicit repository file/directory scope must belong to the skill's
own path, a root repository document, an explicit candidate `scope.subject_ids`
link, or a `kind: shared` path referenced by checked concrete SKILL.md evidence
(`source_object.references`). Repository ID alone cannot authorize a sibling
skill's scoped source. A declared repository ID must match the skill's repository.
For `architecture_reference`, passing the prepared architecture condition
requires at least one cited source classified by the assessor with
`scope.architecture_evidence` of `source` or `design_document`. It must be
checked repository or official evidence, or a checked API file observation
with complete, nonempty content. With only a keyword hit, mark the condition
pending. A checked design section in a README can qualify. The assessor
explains the design using the cited material. The engine checks the
classification and source binding and leaves textual entailment to the assessor.

The validator requires these exact stable subitem keys (`ASSESSMENT_ITEMS` is also exported
from `finder_core.validation`):

| Skill | Dictionary | Four equal-weight keys |
|---|---|---|
| skill-finding | usability | host_tools, dependencies_permissions, installation, io_examples |
| tool-finding | usability | functionality, stack, resources, documentation |
| paper-finding | landing | task_transfer, artifacts, resources, reproducibility |

The other score dictionary must be empty. Missing knowledge is an explicit null
subitem, never an omitted key. Reading depth is recorded, not treated as proof
of real execution. Ranking must route abstract-only paper judgments to provisional
recommendations; T01 does not implement ranking or a natural-language evaluator.

## Remaining shared types

The table lists constructor fields in order. Fields with an empty default can be
omitted in JSON. Consult the dataclass annotations for nested types.

| Type | Fields |
|---|---|
| Evidence | evidence_id, source_url, subject_id, fetched_at, scope (JSON object), excerpt, source_category, status, check_method; source_object={} |
| Metric | value (JSON), status, unit, provider, subject_id, fetched_at, scope, evidence_ids, method_version |
| IdentityRelation | source_id, target_id, relation, evidence_ids; status=verified, reason="" |
| Candidate | candidate_id, kind (skill/tool/paper); identifiers={}, aliases=[], urls={}, versions=[], relations=[], metrics={}, discovery_evidence_ids=[] |
| ProviderLimit | provider; remaining=null, reset_at=null, reason="" |
| HostSearchEvent | event_id, query, searched_at |
| ObservationBatch | candidates=[], evidence=[], identity_relations=[], provider_limits=[], host_search_events=[] |
| ProviderBatch | candidates=[], evidence=[], provider_limits=[], partial=false, next_cursor=null |
| SourceDocument | subject_id, source_url, path, ref, content_text, truncated, fetched_at, evidence_ids |
| FileEntry | path, type (file/directory/symlink/submodule) |
| FileInventory | repo_id, ref, entries, truncated, evidence_ids |
| RunState | run_id, request, snapshot_id; candidates={}, evidence={}, assessments={}, invalidated=false, invalidation_reason=null, limits=[], host_search_events=[], request_counts={} |
| ComparisonGroup | member_ids, mode, effective_weights, frozen_snapshot_id; missing_reasons={}, omitted_items={} |
| RankedReport | group=null; formal=[], qualitative=[], pending=[], excluded=[], same_repository_supplementary=[], scores={}, sensitivity={}, limitations=[], provenance={} |
| CohortManifest | venue, year, track, type, member_ids, N, source_urls, exclusion_rules, database, queried_at, complete; evidence_ids=[] |
| CohortSummary | H, n_h, Z, n_c, N; high_ratio/zero_ratio/high_coverage/zero_coverage/high_lower/high_upper/zero_lower/zero_upper=null, comparable=false, missing_reasons=[], manifests=[], calculation_method="", high_window="", zero_window="" |
| VenueEdition | year, ended (boolean/null), evidence_ids |
| VenueRecord | version, venue_id, aliases, applicable_types, applicable_tracks; editions=[], ccf=null (Metric), acceptance_numerator/acceptance_denominator=null, acceptance_scope="", acceptance_evidence_ids=[], award_scope={}, award_evidence_ids=[] |
| Policy | schema_version, policy_version, weights, budgets, capacity, cache, maintenance, github, paper, ranking, assessment_items, qualitative_fact_fields, report_timezone, external_read_only, execute_candidates, auto_create_accounts, auto_purchase_quota, auto_enable_services; transport=TransportPolicy() |
| TransportPolicy | max_retries=2, timeout_seconds=30, max_wait_seconds=120, arxiv_interval_seconds=3 |

Evidence source categories are `api`, `official`, `repository`, `paper`,
`host_search`, `third_party`, and `agent`. `check_method` is a nonempty producer
description; a host import does not automatically make an observation official.
Identity relations are `same_work`, `version_of`, `fork_of`, `mirror_of`,
`upstream_of`, `moved_to`, and `possible_match`; verified relations need evidence.
Source content is analysis data, not instructions to execute.

RunState collections are ID-keyed typed maps; keys must match record identity.
Report section lists hold candidate IDs, while scores map candidate IDs to
numbers; additional explanations belong in provenance/limitations. Comparison
modes are `github`, `full_paper`, `no_venue`, and `landing_only`; weights must be
finite fractions summing to 1. Members must be unique. A group with no comparable
candidates should be represented by `RankedReport.group = None`.

Run persistence uses `run.json` as its sole atomic commit point and verifies the
full saved state against immutable `history/<full-state-sha256>.json`. The full
state contains its fact snapshot ID, so a second snapshot-hash directory is
unnecessary and would exceed native Windows path limits for ordinary deep run
directories. Loading also supports the older
`history/<snapshot-sha256>/<full-state-sha256>.json` layout; subsequent saves write
the flat layout and retain existing history. `request.json`, `candidates.json`,
`evidence.json`, `assessments.json` and `manifest.json` are diagnostic projections,
not independent transaction state. Temporary files stay beside their destination;
each is flushed and atomically replaced before `run.json` commits. Shorter history
paths reduce overhead by 65 characters without changing hashes, integrity checks
or the requirement that the complete native path must fit the host filesystem.

ObservationBatch rejects duplicate event IDs within one batch. Run storage must
deduplicate previously imported event IDs across batches, retain budgets on
revision, and enforce the host-search ledger. That ledger records observed host
searches; it cannot control the host tool itself. API budget interception belongs
to HttpClient. All paper structured requests share one 120-call allowance,
including GitHub lookups, and must also respect provider-specific limits.

Cohort raw counts require `H <= n_h <= N` and `Z <= n_c <= N`; ratios are finite
fractions. Complete manifests require unique member IDs with count exactly N.
Statistics computation, valid denominators, matched-paper evidence, and per-year
comparability decisions remain the cohort calculator's responsibility.

T09 calculations preserve typed `manifests` plus the calculation and metric-window
definitions in each summary. Count-only legacy summaries can still deserialize;
`combine_cohorts` rejects them because they cannot establish compatible scope.
Combination requires disjoint members/annual scopes and the same venue, track,
paper type, database, query date, and calculation/window definitions. Every annual
comparability veto survives pooling. Verified field coverage and comparability are
separate: saved OpenAlex flags can have full coverage while missing normalization
provenance or a provider/official publication-year discrepancy prevents comparison.

`venue-stats --run-dir RUN --manifest manifest.json --records records.json` accepts
a typed `CohortManifest` and a separate complete Candidate array. Without `--records`,
the canonical run must already contain every manifest member; otherwise it fails
clearly. The complete cohort is never inserted into the recommendation pool.
`--input cohorts.json` accepts `{ "cohorts": [{ "manifest": {...}, "records": [...] }] }`
for several separately scoped cohorts; by default it uses `RUN/cohorts.json` if
available. `--acl-metadata official.json --openalex-observations saved.json` adapts
the saved ACL2022 main/long snapshots, retaining their provenance gaps. These
options are mutually exclusive. The derived `RUN/venue-stats.json` is bound to the
current canonical snapshot/revision/state hash and does not change run facts or
request counters. All modes are offline. `deep_venue_stats=true` records an explicit
request but does not imply network completion: this version has no general venue
collector and reports the missing capability. Missing complete inputs remain
unavailable, rather than being replaced by a recommendation search sample.

`paper_venue_scores(candidate, evidence, policy, *, records=None)` owns the scoped
CCF/award scoring gate and returns `V`, `award_bonus`, `evidence_ids`, `limitations`.
Actual venue/year/track/publication_type must be verified primary-source Metrics.
`publication_fact(candidate, field, evidence)` resolves these four fields before
venue scoring or display. Checked official/paper publication records and primary
publication APIs take priority over arXiv/OpenAlex/S2 bibliographic observations.
Unavailable/null observations do not compete; agreeing facts at the winning
authority combine their evidence references. Conflicting winning-authority facts
remain unavailable, including explicit conflict status. An explicit checked
official correction overrides database metadata; equal-authority corrections must
be disambiguated or replace the prior same-provider observation through merge.
All raw metrics remain stored. Generic metric/citation ambiguity is unchanged.
`resolve_venue(candidate, records, *, evidence)` requires the same Evidence mapping
and uses this resolver, as do report scope headings and exact award display.
It uses versioned current-catalog mappings and exact identified official winners,
never raw candidate CCF/award labels. Award identity needs actual candidate primary
evidence exposing the DOI or the same official paper URL as the versioned proof.
The bundled catalogue and award identities are explicitly verified subsets; a
catalogue miss means uncovered, and missing award membership means unverified.

## Policy constant audit

All entries below are encoded in `finder_core/resources/policy-v1.json`. Nested
policy sections are typed dataclasses; arbitrary additional keys fail. Weight
sets require known dimensions, nonnegative fractions, and sum 1; capacities and
budgets reject invalid counts, and read/deep limits cannot exceed their parent
candidate limits. Consumers must use the loaded values rather than duplicate
them as independently edited constants.

| Policy field | Version 1.0 value / rule |
|---|---|
| weights | skill U/P/M=.40/.35/.25; tool=.35/.35/.30; paper L/I/V=.60/.30/.10 |
| capacity | formal 5; supplementary 2; skills/repo 2; GitHub initial/deep 60/12; paper initial/deep/read 80/12/5 |
| budgets | host search 8; GitHub authenticated/anonymous 120/40; all paper structured calls 120; stricter live limits win |
| cache | counts/citations 86400s; queries 21600s; static paper identity 2592000s; SHA-fixed files reusable indefinitely |
| transport | at most 2 retries; 30s per-request timeout; 120s cumulative request/wait allowance per run; arXiv one connection with at least 3s between request starts; provider limits take precedence |
| maintenance.bands | <=30d:100, <=90d:80, <=180d:60, <=365d:40; older 20; archived 0; unknown null |
| github.minimum_repository_stars | 10000 by default. Tool and skill recommendations require a verified count at or above this value. The policy accepts a higher minimum. |
| github.popularity_weights | stars/forks/watch=.60/.30/.10; missing watch removes it for the frozen group, remaining weights 2/3 and 1/3 |
| github.log_caps | stars 100000; forks 10000; watch 1000; log1p compression, capped score, raw count retained |
| github.required_group_metrics | U, M, stars, forks. After the star minimum is met, missing U, M or forks can yield a qualitative result |
| paper routes | recent 24 months; classic unlimited year; initial budget shares .5/.5; no final split quota |
| paper.ccf_scores | A 100, B 75, C 50; missing/inapplicable V is null |
| paper.award_bonus | formal Best Paper 5; Outstanding 3; Distinguished 3; explicit Honorable Mention 1; max of awards, never sum |
| paper.maximum_index | 105; an index rather than a percentage |
| paper.no_venue_weights | L/I=2/3,1/3; landing-only L=1 |
| paper.group_order | eligibility/R4/R3 → complete-L G0 → inspect I in G0 → G with I if any → inspect V only in G → otherwise whole G0 uses L → freeze before Top/repo limits |
| paper.venue_coverage_threshold | .90, an observation threshold rather than a confidence guarantee; complete mother set required |
| paper.mature_year_offsets | query year minus 6,5,4; on 2026-11-17 yields 2020,2021,2022 (latest three completed publication-year-plus-three-year windows) |
| ranking.formal_relevance | R4 before R3; hard constraints first |
| ranking.formal_order | R desc → score desc → complete U/L desc → raw stars or same-database citations desc → stable ID asc |
| ranking.qualitative_order | R desc → complete U/L first → complete U/L desc → verified required-fact ratio desc → stable ID asc |
| ranking.close_score_difference | difference <3 means close; no claim of statistical significance |
| ranking.sensitivity_weight_delta | +/- .10 to P/I, other effective base weights redistributed proportionally; fixed group and awards; skip landing-only |
| ranking.freeze_before_limits | true; includes candidates later cut by Top 5/repository quota |
| ranking.empty_group_qualitative_limit | 5, with explicit limitations; never synthesize numeric indices |
| qualitative_fact_fields | GitHub identity/license/stars/forks/update; paper identity/publication/citations/method/implementation-resources |
| report_timezone | Asia/Shanghai unless explicitly configured by user |
| external_read_only | true; candidate execution, account creation, purchases and persistent-service activation all false |

`TransportPolicy` rejects booleans, negative retries, nonfinite values, nonpositive
timeouts/wait allowances, and arXiv intervals below three seconds. Older policy
payloads without `transport` receive these defaults; unknown keys still fail.

## HTTP and cache integration (T03)

```python
from finder_core.cache import FileCache
from finder_core.transport import HttpClient

# The caller loads RunState and Policy, then persists the changed state at the
# end of the command, including commands that yield only partial results.
http = HttpClient(FileCache(run_dir / "cache"), policy=policy,
                  skill=state.request.skill, request_counts=state.request_counts,
                  provider_limits=state.limits)
result = http.get("github", "https://api.github.com/search/repositories",
                  {"q": "offline search", "per_page": 30},
                  policy.cache.queries_seconds)
state.request_counts = http.request_counts
state.limits = http.provider_limits
# Persist state with the run store after processing result.
```

`HttpClient(cache, *, policy, skill, request_counts=None, provider_limits=None,
environ=None, request=..., now=..., monotonic=..., sleep=...)` keeps the supplied
counts dictionary and limits list by reference. Its supported provider strings
are `github`, `arxiv`, `openalex`, and `semantic_scholar`. Calls permit the HTTPS
official API hosts (GitHub also permits anonymous `raw.githubusercontent.com`).
Only the three existing environment variables `GITHUB_TOKEN`, `OPENALEX_API_KEY`,
and `SEMANTIC_SCHOLAR_API_KEY` are read. Missing keys use anonymous requests.
The optional `environ` mapping replaces environment lookup in offline tests.
`http.is_authenticated(provider: str) -> bool` reports whether an existing
credential is available for that provider, without exposing it or issuing I/O.
arXiv and unknown providers return false.

`get(provider, url, params, ttl_seconds)` returns `HttpResult(status, body,
source_url, fetched_at, state="verified", limits=[], from_cache=False)`.
`status` is an HTTP integer, or null when a request was blocked or failed before
a response; `body` is redacted UTF-8 bytes. `state` is `verified`, `failed`, or
`stale`, describing transport/cache freshness rather than source-fact verification.
`partial` is true when limits exist or state is not verified. Providers must
inspect HTTP status, parse the body, and preserve candidates/evidence already
collected when a subsequent call fails. Limits explain budget, access, retry,
redirect, or cache-write degradation; they never synthesize result items.

Every issued attempt (including retries and allowed same-origin redirects)
increments the provider counter. Paper runs also increment `paper_structured`,
including GitHub lookups. Fresh cache hits do not spend budget. Cumulative wait
includes measured request time and retry/arXiv sleeps; the next timeout is clipped
to the remaining allowance. Retry-After supports seconds and HTTP dates. 401/403
are not retried. Exhausted live quotas and 429 cooldowns survive client recreation
through `provider_limits`; live restrictions with a reset date expire at that
date. Overlapping quota reset and Retry-After restrictions retain the latest
deadline; an indefinite restriction takes precedence. Reconstruction combines
all persisted same-provider restrictions, so list ordering cannot shorten them.
A restriction without reset remains until explicitly resolved.

Persist these reserved integer `request_counts` entries with provider counters:

- `transport_wait_milliseconds`: cumulative wait, rounded up to milliseconds.
- `transport_arxiv_last_milliseconds`: UTC Unix time of the last arXiv attempt.

These are bookkeeping values, never HTTP attempt counts; do not sum all dictionary
values as request totals. Preserve them on revision. Serialize commands for a
single run; a client lock serializes concurrent calls to that client, while the
run store must handle process-level exclusion. Rebind state to the client's
collections before every save, since contract validation may normalize collections
into new objects. A recreated client must receive both persisted collections.

The injected request callable has signature `(url: str, headers: dict[str, str],
timeout: float) -> WireResponse(status: int, body: bytes, headers: dict[str, str])`.
It must perform exactly one GET without following redirects. `now()` returns an
aware datetime, `monotonic()` returns seconds, and `sleep(seconds)` is the waiter.
An injected request implementation must itself honor its whole-call timeout.
Offline tests inject all four and do not access the network or actually sleep.
The standard-library adapter disables urllib's automatic redirects. The client
allows at most five same-origin redirects; all cross-origin redirects are blocked,
so credentials cannot reach unrelated hosts or HTTP downgrade targets.

The default adapter executes each GET in one owned, short-lived `spawn` child.
The parent's absolute deadline covers child startup, DNS/connect, progressing
headers/body, bounded IPC transfer, and child completion. IPC messages are at most
4096 bytes. On timeout the parent terminates and joins the child and closes both
connections; process teardown closes the child's response socket. No request
thread/service remains. Startup/IPC overhead counts toward the request/run
allowance. Scheduling and synchronous teardown may add up to the documented 250ms
verification tolerance beyond the deadline; actual elapsed time is charged, and
an exhausted run cannot issue another attempt. The Windows loopback check observed
3–9ms teardown excess at 0.45–0.6s deadlines.

Standalone launchers must guard command execution with `if __name__ == "__main__":`
so spawn cannot repeat CLI actions. Packaging/T12 must verify Windows spawn through
the distributed standalone launcher, including successful response transfer and
timeout cleanup; this is a concrete integration requirement.

`FileCache(directory).get(key, now, allow_stale=False)` returns `CacheEntry` or
null; `.put(key, entry)` atomically replaces a hashed file within its directory.
`CacheEntry(payload: bytes, source_url: str, saved_at: datetime,
ttl_seconds: int | None, status: int = 200)` retains original observation time.
Expiry is inclusive at the TTL boundary. Null TTL is for SHA-fixed files only;
callers select this only when the source is pinned. Zero TTL never yields a fresh
hit. The shorter of the cached and requested TTL governs freshness. Failed refresh
can return stale payload with its old date and current failure limits.

Cache keys include provider, sorted normalized request, and visibility scope.
Anonymous and authenticated entries are separate; authenticated scope includes a
one-way credential fingerprint so different accounts cannot share cached private
responses. Raw credentials, credential query fields, URL userinfo, and response
credential values are redacted before provenance and cache writes. Public metadata
remains reusable within the same visibility scope. Changing credentials creates a
different scope. An already recorded authentication failure without reset needs
explicit resolution of the persisted limit before retrying that provider.

`finder_core.providers.base.Provider` is a structural protocol defining
`search(query: QuerySpec) -> ProviderBatch` and
`enrich(candidates: Sequence[Candidate]) -> ProviderBatch`.

Ranking, source-specific discovery, and packaging are later tasks. No candidate
content is installed or executed by this package.
