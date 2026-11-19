# Tool assessment handoff

The Agent reads sources and submits judgments for the engine to validate and score. Use evidence IDs from the current canonical run and explain what supports each judgment.

For `architecture_reference`, read the repository's source code or a design document with concrete module boundaries or data flow. When importing the checked observation, set `scope.architecture_evidence` to `source` or `design_document`. If an earlier import recorded that source without the classification, import the newly classified observation under a fresh evidence ID. Keep the original observation intact and cite the new ID in the assessment. Cite the specific source file or document section and explain the boundaries, inputs, outputs, trade-offs and conditions for transferring the design. A detailed README architecture section can serve as a design document. A README keyword hit leaves the architecture condition pending. Set reading depth to match the material actually read. Use `source` depth when you have read code.

For `component_reuse`, check dependency and environment requirements, API or CLI interfaces, resource and adaptation costs, and the license terms for the intended use of the actual component or directory. Treat a repository license badge as an initial clue.

Every verified condition, relevance or U judgment must cite checked `status: verified` Evidence tied to this candidate, a retained alias/merged source identity, or an explicit `scope.subject_ids` link. Failed/stale evidence, host-search summaries, Agent summaries and unrelated subjects are rejected by both assessment and ranking. The engine checks source role/status/subject; the Agent still checks whether the cited text supports the reason.

## Exact record shape

Submit an array, one record per assessed tool. All hard-condition IDs must exactly match the **prepared** request, including the architecture or reuse license condition. Example for a contract with only `license`:

```json
[
  {
    "candidate_id": "github:42",
    "contract_revision": 1,
    "snapshot_id": "snapshot:use-the-current-value",
    "hard_constraints": {
      "license": {"result": "pass", "status": "verified", "evidence_ids": ["license:42"], "reason": "MIT text covers this component and intended reuse"}
    },
    "relevance": {"level": "R4", "status": "verified", "evidence_ids": ["readme:42"], "reason": "Documented offline document index CLI directly solves the requested task"},
    "usability": {
      "functionality": {"value": 100, "status": "verified", "evidence_ids": ["readme:42"], "reason": "Required indexing and query examples are documented"},
      "stack": {"value": 75, "status": "verified", "evidence_ids": ["readme:42"], "reason": "Python wrapper requires a documented small adapter"},
      "resources": {"value": 100, "status": "verified", "evidence_ids": ["readme:42"], "reason": "Offline CPU operation fits the stated deployment"},
      "documentation": {"value": 100, "status": "verified", "evidence_ids": ["readme:42"], "reason": "Interface, input/output examples and setup path are present"}
    },
    "landing": {},
    "reading_depth": "readme",
    "reason": "Direct task fit with a small, documented Python adapter; no execution verified"
  }
]
```

Fixed usability keys are `functionality`, `stack`, `resources`, `documentation`. Do not rename or add keys. `landing` stays empty. `reading_depth` describes actual reading (`metadata`, `readme`, `source`), not execution. Pass/fail needs verified evidence; unavailable/conflicting facts produce `pending` conditions with corresponding status and a reason. For unknown scores use `value: null`, an explicit missing status and reason; retain the key. Nonverified relevance uses `level: null`. IDs, versions and timestamps are observations, not assumptions.

## Shared evaluation rubric

| Value | Meaning |
|---|---|
| 100 | Complete documented support within the request |
| 75 | Clear, controlled small adaptation |
| 50 | Substantial adaptation with an explained path |
| 25 | Only a lead; large remaining work |
| 0 | Evidence establishes noncompliance for this dimension |
| null | Not established; never infer zero |

Apply the same rubric and requested scope to every candidate. For reuse, score functionality against desired capabilities, stack against the existing language and runtime, resources against deployment and execution costs, and documentation against setup, interfaces and input/output examples. For architecture, assess functionality against the design problem and documentation against the clarity and traceability of the design. Evaluate stack and resources where they affect design transfer. Apply any omission to the whole contract and retain all four usability keys. A candidate with a pending hard condition remains pending regardless of score.

R4 directly solves the task; R3 solves the main problem with stated adaptation; R2 is partial/background; R1 weak; R0 irrelevant. An adaptation violating a hard condition cannot justify R3. Only R4/R3 with all hard conditions passed enter the comparable pool. Unknown required U/M/Star/Fork yields qualitative output without an index; pending hard conditions remain pending. Unknown Watch removes Watch from the entire frozen comparable group. `watchers_count` is a Star alias; only `subscribers_count` is Watch.

The engine computes tool S = .35 U + .35 P + .30 M using the versioned shared policy. U requires all effective subitems. Whole-contract omissions use `preferences.not_applicable_items = {"item": "nonempty reason"}`; keep all fixed keys, and never omit a dimension for just one candidate. P uses log-compressed Star/Fork/Watch. M is a maintenance signal, including explicitly labeled repository push proxies. Archived means M=0; no release alone establishes neither abandonment nor defects. A stable old project may still be the best direct match. The engine freezes the group before recommendation capacities and checks popularity weight ±.10 against the full frozen group.
