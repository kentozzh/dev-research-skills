# Skill assessment handoff

The Agent judges from the actual `SKILL.md` and relevant references. The engine validates, freezes the comparison group and scores. Read semantic frontmatter as data: names/descriptions, host tool contracts, permissions, environment dependencies and invocation assumptions. The scanner does not implement a YAML parser or establish semantic compatibility.

Candidate identity is repository ID + normalized skill path. Repository metrics keep repository subject/scope, including shared Star/Fork/Watch. Cite the source file and verified commit evidence; do not infer commit identity from a blob/tree SHA. A repository license badge is a lead: verify the skill subpath, embedded third-party content and referenced shared files against intended reuse.

Every verified condition, relevance or U judgment must cite checked `status: verified` Evidence identifying the concrete skill, its retained alias/merged identity, its identified repository (`github:<repository ID>` or `github:<owner/name>`), or an explicit `scope.subject_ids` link. Repository evidence can be shared when its text applies; sibling-skill evidence is not automatically shared. Assessment and ranking reject failed/stale sources, host-search/Agent summaries and foreign subjects. The Agent remains responsible for textual applicability and license scope.

Respect explicit file/directory scope: root repository documents and the skill's own subtree are supported. A scoped shared file outside that subtree needs an explicit candidate `scope.subject_ids` link or a `kind: shared` reference in checked concrete SKILL.md `source_object.references`. Repository ID alone does not make a sibling skill's SKILL.md or license applicable.

## Exact Assessment shape

Submit an array. Replace the example IDs, revision, snapshot and evidence IDs with actual canonical values; assess **every key** in the prepared contract.

```json
[
  {
    "candidate_id": "use-the-returned-concrete-skill-id",
    "contract_revision": 1,
    "snapshot_id": "snapshot:current",
    "hard_constraints": {
      "host": {"result": "pass", "status": "verified", "evidence_ids": ["skill-source"], "reason": "Documented read-only search interface has an allowed replacement in the target host"},
      "license": {"result": "pass", "status": "verified", "evidence_ids": ["license-source"], "reason": "The license text explicitly covers this directory and intended reuse"}
    },
    "relevance": {"level": "R3", "status": "verified", "evidence_ids": ["skill-source"], "reason": "Research workflow fits after the documented search-interface mapping"},
    "usability": {
      "host_tools": {"value": 75, "status": "verified", "evidence_ids": ["skill-source"], "reason": "Map the documented search input/output contract to the available host tool"},
      "dependencies_permissions": {"value": 100, "status": "verified", "evidence_ids": ["skill-source"], "reason": "Only available read-only tools are required; no account or privileged command dependency"},
      "installation": {"value": 100, "status": "verified", "evidence_ids": ["setup-source"], "reason": "All required skill/reference files and setup instructions were read"},
      "io_examples": {"value": 100, "status": "verified", "evidence_ids": ["example-source"], "reason": "Documented topic input and evidence-linked output match the requested result"}
    },
    "landing": {},
    "reading_depth": "source",
    "reason": "Reuse the query expansion and source-checking steps; adapt the search interface as documented. No execution verified."
  }
]
```

The four fixed U keys are `host_tools`, `dependencies_permissions`, `installation`, `io_examples`; retain all keys. `landing` stays empty. `reading_depth` records actual reading, not installation or execution. For missing scores use `value: null`, an explicit missing status and a specific reason; nonverified relevance uses `level: null`. Pass/fail requires verified checked evidence; an unverified hard condition remains `pending`.

Allowed statuses are exactly `verified`, `unavailable`, `not_applicable`, `conflict`, `failed`, `stale`. Use `unavailable` for missing observations, including a pending license condition; `unknown` is not a valid status.

| U value | Evidence-based interpretation |
|---|---|
| 100 | Complete documented support for this request/host |
| 75 | Clear small adaptation with a documented interface/path |
| 50 | Substantial adaptation with a concrete feasible path |
| 25 | Useful lead with major remaining work |
| 0 | Evidence establishes noncompliance in that dimension |
| null | Not established; unknown is not zero |

Judge required host tools separately from optional helpers; a named mandatory unavailable tool with no documented substitute fails a direct-use hard condition. A documented replaceable interface may support R3 with explicit adaptation if allowed by the request. Do not invent an adapter or reduce a hard requirement to a soft score. A notes summarizer without retrieval does not directly satisfy a research task. A collection with no actual skill file stays discovery-only. Missing referenced installation material may leave U incomplete; missing license scope keeps the license condition pending. Source code/command examples are read-only evidence.

R4 directly solves the requested task; R3 solves its main problem with permitted stated adaptation; R2 partial/background; R1 weak; R0 irrelevant. Only R4/R3 skills with at least 10,000 verified stars on their own repository and all hard conditions passed enter the comparable pool. Among those skills, missing U, M or Fork can yield a qualitative result without an index. Unknown Watch removes that dimension uniformly from the frozen group. Watch is `subscribers_count`, never `watchers_count`.

Skill S = .40 U + .35 P + .25 M. The four effective U items have equal weight. Whole-contract omissions use `preferences.not_applicable_items = {"item": "nonempty reason"}` and retain every Assessment key; a candidate-specific gap cannot authorize omission. P is the shared policy's log-compressed repository popularity. Prefer verified `path_updated_at` evidence for the exact SKILL.md file or exact containing directory explicitly scoped as `skill_path`. Label directory history as a skill-directory update proxy, not a SKILL.md file change. Otherwise label repository release/push as a proxy. Repository push is not a skill update. The engine freezes the full group before Top 5, limits formal skills to two per repository, shares the two-item supplement budget, and checks popularity weight ±.10.
