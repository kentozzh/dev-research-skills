# Persisted paper-selection workflow

Use Python 3.11+. If this skill contains `scripts/finder.py`, the command prefix is `python <skill-directory>/scripts/finder.py`; in a development checkout it is `python -m finder_core` from the repository root. Substitute the available prefix below. Bundled use needs no sibling skill, source checkout or global install.

## Prepare and discover

Write UTF-8 JSON in the task workspace. Persist the intent that matches the decision. A request for an evaluated workflow across the entire task uses `framework_discovery`. A question about which approach to use within one step, or what its comparisons show, uses `method_evidence` even on a first turn. For example, a comparison of retrieval methods can start with this contract.

```json
{
  "skill": "paper-finding",
  "raw_request": "Which document retrieval method should we use on a CPU? Find comparative experiments.",
  "hard_constraints": {"task": "The study compares retrieval methods under relevant resource conditions"},
  "preferences": {"paper_intent": "method_evidence"},
  "assumptions": ["Method reading first; no implementation or experiment has been executed"],
  "queries": [
    {"provider": "arxiv", "query": "document retrieval CPU latency relevance comparison", "route": "recent", "query_id": "recent-preprints"},
    {"provider": "openalex", "query": "document retrieval efficiency effectiveness evaluation", "route": "classic", "query_id": "classic-methods"},
    {"provider": "semantic_scholar", "query": "document retrieval CPU benchmark", "route": "recent", "query_id": "recent-related"}
  ]
}
```

Generate queries from the contract and reuse evidence that already answers a decision. Target follow-up searches only at decisions affected by new constraints.

- **Framework discovery** (`framework_discovery`). Preserve the user's domain and intended outcome when translating the task into Chinese and English search terms. Run the whole-task query alongside searches for neighboring tasks or method families. When screening results, open the original publication for a promising whole-task match and check the actual input, output and quality evaluated. When the papers cover only a different task or an isolated stage, spend a remaining query on the coverage gap. Use terminology from an original abstract, the field's name for the target application, or a different scholarly index. Stop when direct evidence is sufficient or the available budget or sources are exhausted, and identify any remaining gap.
- **Method evidence** (`method_evidence`). Start with the proposed method or choice, its baseline and the expected trade-off. Search for comparisons, ablations, metric definitions and known failure conditions. Use terminology from the target and neighboring tasks where their evaluation is comparable.

For intended implementation reuse, add explicit license and resource hard conditions describing the intended use and available CPU/GPU/memory. A reading request can include papers with unavailable code.

The intent guides query terms and evidence reading. Each `QuerySpec.route` still selects the recent or classic retrieval lane independently.

```text
python -m finder_core prepare --request request.json --run-dir runs/paper-choice
python -m finder_core discover --run-dir runs/paper-choice
python -m finder_core enrich --run-dir runs/paper-choice --ids selected-ids.json
```

Use the canonical IDs returned in `run.json` in the selected-ID array; do not construct identity from a title. Stable identity keys are `doi`, `arxiv`, `openalex`, `semantic_scholar`. For a supplied offline pool, prepare then import directly and omit live discovery. Label fixtures and preserve their actual observation dates.

The registered structured providers are `arxiv`, `openalex`, `semantic_scholar` (display S2). Explicit `recent` queries apply the rolling 24-month filter; `classic` is unrestricted. Interleave initial recent and classic queries before adding further queries for either route: merging retains the first 80 canonical papers, so early queries from one route can fill the pool. Request-budget balance does not reserve a 40/40 candidate quota or require balanced final recommendations. Initial structured requests share the 120-request run cap, initially 60 recent and 60 classic; enrichment uses the shared remaining budget. The persisted lane ledgers survive repeated commands and revisions. `general` is charged to classic with a recorded limitation, so author explicit routes. Upstream limits and cooldowns take precedence. Do not reset state to get more budget.

Use at most 8 host searches per run for ACL Anthology, HF Paper Pages, official proceedings, OpenReview, author resources or gaps the adapters do not cover; persist actual calls as host-search events. These are source entry points, not additional structured-provider names. Inspect official publication metadata to distinguish main, Findings, workshop, demo and other tracks. A HF paper-page association alone does not prove author ownership of a repository.

For bounded reference/citation discovery, add a query to the same request with `query` equal to `references:<stable-id>` or `citations:<stable-id>`, an explicit route and a fresh query ID. OpenAlex accepts explicit OpenAlex/DOI/arXiv identities (for example `citations:W1001`); S2 accepts S2/DOI/arXiv identities (for example `references:ARXIV:2401.01234`). These invoke documented chain endpoints/filters, not title similarity. arXiv has no chain endpoint; use OpenAlex or S2 and report unavailable chains honestly. Revise the request before executing added queries; do not infer same-work relations from a title match.

## Open original sources

Use the available `Candidate.urls` roles. `publisher` is a source-reported publication landing page, `doi` is a resolver, and `pdf` is a reported full-text entry. OpenAlex and Semantic Scholar catalog links are discovery leads even when recorded under the legacy `paper` key. arXiv `paper` can point to a versioned preprint abstract. The official paper page in an anthology can establish paper facts when read. For linked research artifacts, check first-party author or project material before attributing them to the paper.

Follow a DOI to its destination when useful. Record which source, version and sections you actually read. A URL or successful metadata response only establishes an entry point. When access stops at the abstract, keep that reading depth and record the specific unread sections. Keep failed or unavailable access visible without filling it from an index summary.

For a PDF table or section, locate the evidence in the exact linked file. A `#page=N` fragment uses the one-based physical PDF viewer page. Check that the table or passage is visible on that page before adding the fragment. A printed folio, a zero-based tool index or the start of the surrounding section does not establish the viewer page for the cited evidence. If it cannot be confirmed, give the verified publication page and plain full-text URL with the observed table or section label.

## Import, read and assess

An observation import is a self-contained `ObservationBatch` object: `candidates`, `evidence`, optional `identity_relations`, `provider_limits`, `host_search_events`. Each candidate has `kind: "paper"`, a canonical `candidate_id`, explicit identifiers, version/publication/resource URLs and metric records. Each metric keeps `value`, `status`, `unit`, `provider`, `subject_id`, `fetched_at`, `scope`, `evidence_ids`, `method_version`. Each Evidence keeps its URL, subject, actual fetched time, scope, excerpt, source category, status and check method; include primary source objects where required for identity/track checks. All referenced evidence must be in the batch. The canonical statuses are `verified`, `unavailable`, `not_applicable`, `conflict`, `failed`, `stale`.

Before the initial import, translate the supplied source's supported fields into one canonical representation of each observation. Check its identity, units, explicit normalization/corpus/window and publication scope against the actual contract. Preserve the source values and missing facts; representation normalization cannot supply absent core proof or publication identity. Do not first import a raw representation and then overlay an equivalent representation with different scope keys as if it were a new observation: the engine intentionally preserves both, and unqualified lookup becomes ambiguous. Genuine later observations retain their actual provenance. If ambiguous records are already in a run, preserve and disclose that history and resulting unavailable comparison; do not edit state or reset live budgets to hide it.

For the leading candidates, seek these sections in the available full-text sources.

- **Framework discovery.** Read the workflow stages and their inputs/outputs, data construction, evaluation settings, baselines and limitations. Track which stage each source tested so partial studies can inform a specific part of a project design.
- **Method evidence.** Read the relevant treatment and controls, ablations, metric definitions, datasets or splits, assumptions and limits. When the evidence answers a pending design choice, retain the compared variants, reported values with units or direction of change, evaluation conditions and original section or table. Attribute a result to the combination actually tested when several factors changed together. Keep this observation available in the conversation or current run. On a follow-up, reuse it with its locator. Check the same source for missing details and search further only for a remaining evidence gap.

Save these readings as actual Evidence in the existing import format. Keep the paper identity, read version, section or table, observation time and a short excerpt or structured result. Attach the experiment's own source to experimental judgments. Import/save only necessary short excerpts, structured observations, source URL, read version and actual observation time, plus a verified response/file hash when available. Record unavailable hashes honestly. Put compact identity/source metadata in `source_object`; do not embed full HTML or paper text in Evidence, ObservationBatch or report provenance. A local read/cache artifact is separate from the portable evidence report; retain its reference/hash rather than copying its full body into every observation.

Keep OpenAlex and S2 cumulative `citations` as provider-qualified observations, never a sum. Relevant metric names include `percentile`, `top1`, `top10`, `publication_year`, `publication_track`, `publication_type`, `venue`, `ccf`, `award`, `official_implementation`, `code_license`. For I, retain positive `corpus: "core"` and official normalization scope, with separate checked API/official OpenAlex evidence (OpenAlex URL or explicit `database: "OpenAlex"` source scope). Paper-reading notes alone do not prove database metrics. Retain scope and raw official names; raw ccf/award strings do not authorize points. Import all four verified primary identity facts `venue`, `publication_year`, `publication_track`, `publication_type`; a DOI string alone is not proof. Tie their evidence to this candidate, exposing the DOI or official paper URL for the supported exact award match. For ACL track imports, retain the actually read `publication_track` in source scope or source object. When checking an implementation, import primary author/repository evidence rather than upgrading a HF association. Missing metrics use null; keep an unverified award claim's raw label in its source evidence rather than a nonnull unavailable Metric.

```text
python -m finder_core import --run-dir runs/paper-choice --input observations.json
python -m finder_core assess --run-dir runs/paper-choice --input assessments.json
python -m finder_core rank --run-dir runs/paper-choice
python -m finder_core report --run-dir runs/paper-choice --format json
python -m finder_core report --run-dir runs/paper-choice --format markdown
```

Read abstracts for the 12 deep-screened candidates and seek the relevant full-text sections for the leading 5. Save the read observations before submitting the array in [assessment.md](assessment.md). Importing new facts invalidates old judgments. `prepare`/`revise` assigns the revision; use the current `run.json` snapshot and every prepared condition key. Diagnostic projections are read-only views. `--output <file>` explicitly exports a report; ordinary reporting writes no report file.

## Venue background and revision

Default venue background uses verified mappings and supplied/cached complete cohorts; it does not trigger a new venue-wide collection. With separate complete-cohort input, run `venue-stats --run-dir runs/paper-choice --input cohorts.json`, where the object is `{"cohorts": [{"manifest": {...}, "records": [...]}]}`. Cohort records are independent of recommendation candidates. Inspect the actual `CohortManifest` schema and loader before authoring input; do not call a search sample complete. The CLI also accepts the paired saved paths `--acl-metadata` and `--openalex-observations` for its supported ACL sample. Record `deep_venue_stats: true` only when requested: the current implementation accepts complete imports/caches and has no arbitrary-venue collector.

For a separate typed manifest, `venue-stats --run-dir runs/paper-choice --manifest manifest.json --records records.json` accepts the complete Candidate array independently of the 80-paper recommendation pool. Without `--records`, canonical candidates must cover the entire manifest. Compute venue statistics after all fact imports and assessments, then rerun `rank`: it attaches the matching `venue-stats.json` as an immutable background snapshot. Artifacts bind run ID, contract revision, snapshot, full canonical state, calculation method, complete manifests/database/query scope and content hash. Any stale or altered artifact is rejected; rerun `venue-stats` instead of editing its provenance. Later report rendering uses the ranked snapshot and does not reopen changed mappings or an overwritten statistics file. Background statistics do not change paper scores or capacity. The current mapping coverage and primary proof requirements are in [assessment.md](assessment.md).

`revise --request revised-request.json --run-dir runs/paper-choice` retains discovery/budgets and changes the contract revision. Reassess and rerank current facts before reporting. A stale `ranking.json` is rejected. Exit codes are 0 for usable partial/valid-empty, 2 for invalid input, 3 for discovery failure without useful results, 4 for missing/current assessment or ranking. A failed search is incomplete coverage; a valid empty search is evidence of no results from that query. Preserve both distinctions in the report.
