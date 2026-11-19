# Persisted tool-selection workflow

Use Python 3.11+. When this skill contains `scripts/finder.py`, use `python <skill-directory>/scripts/finder.py` as the command prefix. In a repository development checkout, use `python -m finder_core` from its root. Substitute the available prefix for every command below. The bundled mode requires no source checkout, sibling skill, or global installation.

## Request and discovery

With a supplied offline candidate pool, prepare the contract and import its observations directly; live discovery is unnecessary. When there is no supplied pool and host search is available, use a small part of the existing host-search budget first to identify representative seed repositories and search terms. For each exact seed query, use `repo:OWNER/REPO` and confirm the returned repository's canonical `full_name` matches the intended seed. An owner filter combined with `in:name` can return similarly named repositories and is not equivalent to that exact qualifier. [GitHub's repository search documentation](https://docs.github.com/en/search-github/searching-on-github/searching-for-repositories) documents the specific-repository syntax. Put these seed queries before broader category, function and alternative queries, then fill the remaining pool within the same run-wide budgets. If the pool is already full, report the coverage limitation and any relevant leads left outside it; retain the existing pool and ledger rather than pruning or resetting them to admit more candidates.

Create UTF-8 JSON input in the task workspace. This example selects a reusable component.

```json
{
  "skill": "tool-finding",
  "raw_request": "Choose a Windows offline document-indexing CLI for Python 3.11",
  "hard_constraints": {
    "windows": "Windows supported",
    "offline": "No document uploads or required remote API",
    "license": "License explicitly covers the intended reuse",
    "active": "Current development excludes archived repositories"
  },
  "preferences": {"tool_intent": "component_reuse"},
  "assumptions": ["No candidate has been executed"],
  "queries": [
    {"provider": "github", "query": "offline document index CLI", "route": "general", "query_id": "function"},
    {"provider": "github", "query": "document search python", "route": "general", "query_id": "category"}
  ]
}
```

For component reuse, extract the required function, interfaces, stack, deployment, resource limits and permissions. The license must cover the intended use, including any specified distribution restrictions. Missing license evidence is pending. An evidenced restriction that conflicts with the intended use fails the condition. For current development, record the usual exclusion of archived components unless the user accepts them. A stable project without releases remains eligible.

For architecture research, use `"preferences": {"tool_intent": "architecture_reference"}` and formulate the design decision the examples need to inform. Preparation requires verifiable module or data-flow design and preserves every explicit hard condition, including license, stack or deployment when the user requires it. An archived project can provide design evidence if the contract allows it. If both purposes are requested for the same repository, prepare one contract and run directory per purpose. Reuse relevant observations through import and assess against each run's own contract.

```text
python -m finder_core prepare --request request.json --run-dir runs/tool-choice
python -m finder_core discover --run-dir runs/tool-choice
python -m finder_core enrich --run-dir runs/tool-choice --ids selected-ids.json
```

`selected-ids.json` is an array such as `["github:42"]`. IDs use immutable numeric repository IDs, not mutable owner/name. Search functional terms, category terms, and alternatives separately; do not impose a high-Star minimum. The GitHub adapter handles public-scope queries, credentials already in the environment, API caps and pagination. The initial/deep ceilings are run-wide rather than reset by issuing another command. Current live provider limits take precedence over policy budgets (anonymous GitHub 40 requests; authenticated 120). Host search is an optional seed/discovery route with at most 8 calls per run, recorded as host-search events in imports. Failure to find a candidate is distinct from failure to search.

Read facts returned by enrichment and additional official documents through the host's available read-only capabilities. Import additional observations as a self-contained `ObservationBatch` JSON with `candidates`, `evidence`, and optionally `identity_relations`, `provider_limits`, `host_search_events`. Each new fact must retain subject, status, scope, source URL and actual fetched time. A local offline fixture may stand in for the transport; label it as a fixture and preserve its observation dates. Do not claim live retrieval from a scoring reference date.

```text
python -m finder_core import --run-dir runs/tool-choice --input observations.json
python -m finder_core assess --run-dir runs/tool-choice --input assessments.json
python -m finder_core rank --run-dir runs/tool-choice
python -m finder_core report --run-dir runs/tool-choice --format json
python -m finder_core report --run-dir runs/tool-choice --format markdown
```

`prepare` returns the assigned revision and snapshot. Use the canonical `run.json` to inspect the prepared request and facts. The prepared contract includes the architecture or reuse license condition and uses a fresh key when an input key is already present. Evaluate every prepared condition. Diagnostic projections are not state to edit. `assessments.json` is an array of the records described in [assessment.md](assessment.md). Import all facts before assessing, since fact changes invalidate judgments. Ranking emits structured output; report emits text. No implicit report file is written; `--output <file>` requests an explicit export.

## Revision and incomplete runs

`revise --request revised-request.json --run-dir runs/tool-choice` increments the contract revision while retaining discovery and the request ledger. Send a new unassigned request containing the current user conditions and the new intent if it changed. Preparation derives the mandatory condition for that intent. Reassess current facts using the returned revision and snapshot, then rank again before reporting. Report rejects stale ranking, even if only assessments changed.

Exit codes: 0 is a successful/usable partial or valid-empty result; 2 is invalid input/contract; 3 is discovery failure without useful results; 4 requires current assessment/ranking. A valid empty search yields an honest empty report, not invented substitutes. Preserve useful candidates and source-specific limitations after failures. Do not retry by resetting the run or deleting its budgets.
