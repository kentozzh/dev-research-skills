# Paper assessment handoff

The Agent records evidence-backed judgments; the engine validates eligibility and computes the versioned index. Reading is eligible without public code. When recommending reuse of a specific implementation, check code/model/data access, applicable license and resource requirements against the intended use. An unknown required license leaves reuse pending and an evidenced incompatible restriction makes it fail.

Every verified condition, relevance or L judgment must cite checked `status: verified` Evidence identifying this paper, a retained alias/merged source identity, or an explicit `scope.subject_ids` link. Both assessment and ranking reject failed/stale sources, host-search/Agent summaries and unrelated subjects. Retaining preprint/publication source identities preserves valid references after merge. Textual entailment remains the Agent's responsibility.

## Exact assessment shape

Submit an array using current `run.json` IDs/revision/snapshot. Evaluate every **prepared** hard-condition key exactly once. For a request whose only condition is `task`:

```json
[
  {
    "candidate_id": "doi:10.1234/example",
    "contract_revision": 1,
    "snapshot_id": "snapshot:use-the-current-value",
    "hard_constraints": {
      "task": {"result": "pass", "status": "verified", "evidence_ids": ["method:example"], "reason": "Read method implements the retrieval step requested in the contract"}
    },
    "relevance": {"level": "R4", "status": "verified", "evidence_ids": ["method:example"], "reason": "Direct retrieval method; inputs and outputs fit the target pipeline"},
    "usability": {},
    "landing": {
      "task_transfer": {"value": 100, "status": "verified", "evidence_ids": ["method:example"], "reason": "Method section specifies a directly transferable retrieval component"},
      "artifacts": {"value": 75, "status": "verified", "evidence_ids": ["artifacts:example"], "reason": "Data and reference outputs are available; the project needs a small adapter"},
      "resources": {"value": null, "status": "unavailable", "evidence_ids": [], "reason": "Inference memory and CPU latency were not reported"},
      "reproducibility": {"value": 75, "status": "verified", "evidence_ids": ["experiment:example"], "reason": "Read evaluation protocol specifies metrics and baseline; dataset preparation needs adaptation"}
    },
    "reading_depth": "full_text",
    "reason": "Read method and evaluation support transfer; target inference costs remain unverified. No experiment executed."
  }
]
```

Fixed L keys are `task_transfer` (任务迁移), `artifacts` (研究产物), `resources` (资源适配), `reproducibility` (实验复现支持). Keep all keys; `usability` stays empty. Every verified judgment points to current evidence and explains the actual method or condition. Values follow the shared rubric: 100 complete fit; 75 controlled small adaptation; 50 substantial explained adaptation; 25 a lead with large remaining work; 0 evidenced noncompliance; null unestablished. Unknown is never zero. Status uses `unavailable`, `conflict`, `failed`, `stale` or `not_applicable` as appropriate, not a new `unknown` enum. Pending hard conditions have a missing status/reason; pass/fail requires verified evidence. Unverified relevance has `level: null`.

Record `metadata`, `abstract`, or `full_text` according to actual reading and name the sections checked in the evidence. Abstract-only evidence supports a provisional task hypothesis. Leave unestablished L items null, label the candidate “摘要级判断 / 暂定”, and name which sections remain unread. Report experimental values from the actual read result and retain the version and original source.

A work can support “经过研究评估的候选框架” when its authors report a verifiable evaluation of the relevant workflow. Treat evaluation of only one stage as evidence for that stage. Identify the experiment's baseline, dataset and metric definition when making a method claim. Attribute author evaluation, independent replication and production evidence separately. Record any experiment in the target project as pending until actual results exist.

R4 directly solves the problem; R3 solves the main problem with a stated viable adaptation; R2 background/partial; R1 weak; R0 irrelevant. A proposed adaptation cannot violate a hard condition. For missing code, distinguish confirmed absence from unavailable evidence. A mathematical method may support a reading recommendation with documented artifacts/verification route even if it has no released implementation; it cannot be claimed ready to reuse.

## Shared scoring and authority

L is the mean of all effective fixed items. Whole-contract omissions use `preferences.not_applicable_items = {"item": "nonempty reason"}` and retain all keys; a candidate-specific missing value never authorizes omission. Formal eligibility needs all hard conditions passed and R4/R3. The engine forms G0 from complete L candidates, then, if any has valid I, freezes G from the I-bearing subset; others are qualitative. I is 100 times verified OpenAlex official normalized percentile. Total citations/top1/top10 remain display evidence and are not additional influence points. When G0 has no I, use pure L without V. When any G member lacks V, remove V for all G and use L:I = 2:1; otherwise use .60 L + .30 I + .10 V. The group freezes before Top 5 selection.

Use the maintained venue resolver and `paper_venue_scores` results rather than assigning V from a paper string. Its exact required primary-source metric keys are `venue`, `publication_year`, `publication_track`, `publication_type`; each must be verified, unambiguous and tied by evidence subject/identity to this candidate. V additionally requires a current-catalog mapping applicable to that track/type: A=100, B=75, C=50. Findings/workshop cannot inherit main-conference grade. Historical papers are labeled “按当前目录评价”; record catalog version and actual source/mirror limits, not publication-year grade. Missing/unlisted/preprint V stays null. Other venue measures are background, not a second aggregate score.

Publication resolution gives checked official/paper records and primary publication APIs priority over arXiv/OpenAlex/S2 bibliography. Unavailable provider fields are nonfacts; agreeing winning-authority observations retain their references, while conflicting authoritative facts remain unavailable. Official corrections can override database scope; do not erase raw provider observations or relax citation ambiguity. Scoring, venue resolution and displayed publication scope share this policy.

Official exact award mappings may add Best Paper +5, Outstanding/Distinguished +3, explicit Honorable Mention +1, taking the maximum per work. Oral/Spotlight and blogs are not award proof. Preserve raw award name, edition, track, matched paper identity and primary source. No verified bonus is not evidence of no award. The index is 0–105, not a percentage or objective quality probability.

Current mapping coverage is eight venues (ACL, EMNLP, NAACL, NeurIPS, ICML, ICLR, CVPR, AAAI), from the CCF-authored 2026 university-hosted mirror. Official-host byte equivalence and successful visual review remain unverified. The award configuration is partial: only ACL2022 Best Paper DOI `10.18653/v1/2022.acl-long.220` and Outstanding Papers DOI `10.18653/v1/2022.acl-long.506` have imported winner identities. An exact supported raw label/category, actual venue/year/track/type, matching DOI and candidate primary evidence exposing that DOI or the same official paper URL are required. A generic official-looking award string never creates points; an unmapped winner is unverified by this configuration, not confirmed nonwinning.

Official top1/top10 flags are independent of percentile: do not infer top1 from .99 or call OpenAlex flags ESI. S2 influential citations do not establish top1. Valid I requires positive OpenAlex core proof (`scope.corpus: "core"`) plus checked API/official OpenAlex evidence; unknown, absent or expansion corpus remains unavailable. The canonical metric scope is `field: "citation_normalized_percentile.value"`, `normalization: "type/publication_year/subfield"`; retain window/method provenance. Keep source/method versions, observation dates and an incomplete citation-window caveat for new papers. Apply ±10 percentage point influence sensitivity to the entire frozen group; pure L skips influence sensitivity with a reason.
