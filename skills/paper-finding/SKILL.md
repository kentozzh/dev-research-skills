---
name: paper-finding
description: Use when finding research-tested frameworks for a concrete project or checking a proposed method against published comparisons, ablations, and limitations.
---

# Paper finding

When explicitly selected as $dev-research-skill:paper-finding or by its short name, handle the paper or method question directly. A design research handoff may supply the project context and evidence to reuse.

Set `preferences.paper_intent` from the question being answered. Use `framework_discovery` for research-tested workflows spanning the target inputs and outputs. Use `method_evidence` to check a proposed method or design choice against experiments. This includes asking how to choose an individual step and requesting comparative evidence before naming any candidate method. If both questions arise, use the intent for the current phase and carry relevant observations into the next. Preserve the existing paper-selection workflow for saved requests without an intent.

For framework discovery, include a first-round query using the user's domain, input, transformation and intended output or quality in ordinary task language. Leave paper, model and dataset names out of that query. When only neighboring tasks or single stages surface, check the remaining gap with a different task formulation. For a method follow-up, start from comparisons already read in this conversation and their original tables or sections.

1. Record the research task, inputs/outputs, baseline, desired improvement, environment and resource limits in a request contract. Distinguish reading/method transfer from implementation reuse: reading eligibility does not require open code; intended code/model/data reuse requires applicable license and resource evidence. Use [workflow.md](references/workflow.md) for queries by intent, original sources and the persisted pipeline.
2. Recall recent work (last 24 months) and classics (unrestricted year), initially splitting the structured search budget equally. Merge at most 80 initial candidates, deep-screen 12, and try to read methods, experiments and limitations for the leading 5. The final list has no recent/classic quota; recommend at most 5 formal papers and 2 worthwhile supplements.
3. Resolve versions and publications by explicit identities. In the user-visible answer, pair each cited paper's verified publication page, DOI or original preprint page with the full text actually read. Cite a table or section by its label. Add a PDF page fragment only after confirming the cited evidence on that physical page of the linked PDF, counting from the first page. If the page position is uncertain, link the plain PDF and give the verified table or section label. Identify any missing source.
4. Read and assess the actual sources using [assessment.md](references/assessment.md). Preserve publication status, venue/year/track/type, each database's citation count and observation date, official top1/top10 flags, exact award names and limits. Keep abstract-only judgments provisional and base empirical claims on the sections actually read.
5. Normalize each source observation once before its first import, assess the current revision/snapshot, rank and render the report. Formal R4 papers precede R3; only within a relevance tier does the index decide order. Use [report.md](references/report.md) to explain findings by intent and link the original sources near each recommendation, citation and alternative. Missing complete proceedings means no venue citation percentage; missing facts stay typed missing, never zero.

Use the existing shared policy and venue mappings; do not create a second scoring system. Keep formal engine order visible when a conditional project choice differs. Discovery is read-only: no candidate installation, experiment execution, account creation or quota purchase is implied. Report actual source coverage and work performed, including valid empty searches and failed routes.
