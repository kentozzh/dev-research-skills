---
name: using-dev-research
description: Use when designing a new software project, feature, or workflow and the user has stated its core goal, input and expected output, including in a reply to a clarifying question or in a brief. This applies before anyone mentions architecture if external evidence could guide how to build it. It also applies when external evidence could guide a choice of architecture, implementation approach, or technical dependency. Also use when a new project or workflow has an unclear purpose and no other workflow is leading clarification, including when an earlier question about its purpose received a vague answer. Defer while another workflow is still clarifying the core purpose.
---

# Design research

Before proposing or comparing architecture, use the conversation and existing project material to identify the goal, core function, constraints, pending decisions, and evidence already available. Apply [the routing table](references/routing.md) to the current turn.

If a workflow is already leading clarification, let it finish clarifying. When the answer establishes the core function and external evidence could guide a design choice, run the applicable research in that same turn before presenting approaches. If no workflow is leading clarification and the missing information prevents targeted research, ask at most one focused question. If the reply stays vague, say that research is pending and wait for more detail without asking another research question or requesting materials. Continue any independent work the user requested. When a secondary preference is open and the core function is clear, give the evidence and a conditional design before asking about that preference.

When designing a new system workflow, independently ask which design choices need published research and which need an open-source project, implementation, or reusable component as evidence. If both can change the design, run paper-finding and tool-finding in the same turn and return both findings. If only one applies, give the concrete reason for that scope.

When the paper question calls for a research-tested workflow, include a search in the user's domain for the transformation from input to intended output, without naming a method. If the results cover only adjacent tasks or individual stages, use a remaining query to check the gap with a different formulation. Carry a relevant published comparison into the discussion with its result, scope and source locator when available.

Hand each selected route a concrete question and shared project context. Use the same-package skill exposed by the host or read its instructions from the host's skill listing. Return the design decision each result informs, its supporting sources, tradeoffs or limitations, and what remains to validate. Hand those decisions and gaps back to whoever was leading the design discussion, including when a route returns no results or a source fails. In the visible handoff, pair each paper with its verified publication page or DOI and the full text actually read. Pair each repository homepage with the cited file or design document. Name missing or unverified sources and apply the [handoff checks](references/routing.md#handoff-and-results). Keep external candidates and implementations read-only.

Users can select this workflow by its skill name, `using-dev-research`. Respect narrower scope, explicit specialist selection and requests to skip research.
