# Persisted skill discovery and source reading

Use Python 3.11+. When the skill includes `scripts/finder.py`, replace the command prefix below with `python <skill-directory>/scripts/finder.py`. During repository development use `python -m finder_core` from the checkout root. The distributed entrypoint requires no checkout, sibling skill or global package installation.

## Prepare and discover

Write UTF-8 JSON in the task workspace. Example:

```json
{
  "skill": "skill-finding",
  "raw_request": "Find a research skill reusable in Codex with source links",
  "hard_constraints": {
    "host": "Required tools are available or have a documented allowed replacement",
    "license": "License explicitly covers the intended reuse"
  },
  "preferences": {"target_host": "Codex", "available_tools": ["read-only search", "browser"]},
  "assumptions": ["Candidate content has not been installed or executed"],
  "queries": [
    {"provider": "github", "query": "research filename:SKILL.md", "route": "general", "query_id": "skill-source"},
    {"provider": "github", "query": "research agent skills", "route": "general", "query_id": "function"}
  ]
}
```

```text
python -m finder_core prepare --request request.json --run-dir runs/skill-choice
python -m finder_core discover --run-dir runs/skill-choice
python -m finder_core enrich --run-dir runs/skill-choice --ids repositories.json
python -m finder_core inventory-skills --run-dir runs/skill-choice --ids repositories.json
```

`repositories.json` is an array of discovered repository card IDs, e.g. `["github:42"]`. Enrichment gets repository metrics/license metadata. Inventory stores tree entries as evidence, including truncation, without reading their contents or creating skills. Inspect `run.json` for `urls["file:<path>"]` from code search and tree evidence `source_object.entries`; choose concrete file entries ending in `SKILL.md`. A file listing alone does not establish content, license coverage or task fit. Do not follow inventory symlinks/submodules as ordinary files. Missing paths in a truncated inventory do not prove absence.

Authenticated GitHub code search can reveal paths directly; anonymous search falls back to repositories and requires file inspection. Optional host search can seed repositories or linked sources: at most 8 calls per run, recorded as `host_search_events` in observation imports. With a supplied offline pool, skip live discovery and preserve original observation dates. Use `stars:>=10000` on repository searches. For code-search hits, host-search leads and imported skills, verify that the repository containing the selected `SKILL.md` meets the same minimum before shortlisting the skill. Keep collections/tutorials as discovery cards and follow only relevant leads within the budgets.

## Read concrete skills and references

Create `selections.json`:

```json
[
  {"repository_id": "github:42", "path": "skills/research/SKILL.md", "ref": "main", "references": ["references/workflow.md", "../../LICENSE"]}
]
```

```text
python -m finder_core inspect-skills --run-dir runs/skill-choice --input selections.json
```

Omit `ref` to use the recorded default branch, otherwise `HEAD`. The command resolves a commit through the commit API and reads the file at that pin when verified. Contents blob SHA and tree SHA remain separate evidence; unsuccessful commit resolution leaves `source_ref` without a verified `commit_sha`. Candidate identity is immutable repository ID plus normalized, case-sensitive `SKILL.md` path; changing the SHA changes its version, not its identity. Use the actual returned candidate ID for assessment.

First inspect the skill with an empty reference list if references are unknown. Its complete source text is retained in `skill-read` evidence `source_object.content_text`; Markdown/literal-path discovery appears under `references`. Read that text, then call inspection again for the same identity with the relevant reference paths. Additional references consume HTTP requests but not a second skill slot. Reference strings are relative to the skill directory. `../` may reach a shared file within the repository; repository escape, filesystem paths and external URLs are classified without being read. External sources need a separate read-only source check and their own evidence; no local-filesystem or cross-repository fallback is performed. Shared files need their own applicable license/dependency review. Helpers are read as text, never run.

The runtime scanner identifies paths and retains text; it does not parse general YAML or decide host compatibility. The Agent reads semantic frontmatter, allowed/required tools, environment variables, scripts, installation and examples. Import additional evidence for those observations, including exact excerpts, path/ref scope, URL and actual fetched time. Missing references and unavailable tools are assessment gaps or adaptation conditions, never permission to execute candidate content.

## Assess, rank and report

```text
python -m finder_core import --run-dir runs/skill-choice --input observations.json
python -m finder_core assess --run-dir runs/skill-choice --input assessments.json
python -m finder_core rank --run-dir runs/skill-choice
python -m finder_core report --run-dir runs/skill-choice --format json
python -m finder_core report --run-dir runs/skill-choice --format markdown
```

An observation import is an `ObservationBatch` with `candidates`, `evidence`, and optional `identity_relations`, `provider_limits`, `host_search_events`. Facts remain distinct from Agent judgments. Read the actual prepared contract in canonical `run.json`, since prepare may add a license condition; evaluate every actual condition key using [assessment.md](assessment.md). Import all facts before assessment. Diagnostic projection JSON is not editable state. `--output <file>` explicitly exports a report; no report file is written by default.

For host-imported concrete skills, `identifiers.skill_path` is the canonical SKILL.md path; `identifiers.path` is an accepted alias. If both appear they must normalize to the same path. Imports normalize the canonical key while preserving the alias and source evidence. A `path_updated_at` metric may scope the exact SKILL.md file, or its exact containing directory with explicit `scope.level: "skill_path"`; directory history is a skill-directory update proxy and does not establish a change to SKILL.md itself. Broader ancestor and sibling paths do not establish this skill's update.

There are separate admission bounds: 60 repository discovery cards and 12 concrete skills. A concrete read attempt consumes one run-wide skill slot even on failure; versions/references of the same identity share that slot. Imported concrete skills also count. Metadata enrichment/inventory does not consume a skill slot. GitHub HTTP requests remain shared across every stage (40 anonymous or 120 authenticated, with live provider limits taking precedence); no command resets host/HTTP budgets. Do not start a new run merely to evade limits. State, evidence and limitations survive partial failures.

`revise --request revised-request.json --run-dir runs/skill-choice` retains facts and usage, increments the contract revision and requires reassessment/ranking. Reports reject stale ranking. Exit codes: 0 usable/partial/valid-empty; 2 invalid input; 3 discovery failure without useful candidates; 4 current assessment/ranking required. Report actual coverage when fewer than five qualify.
