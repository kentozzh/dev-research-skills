# Stage and routing

Use observable facts from the current conversation and existing project documents. A domain name alone does not establish a design decision. Apply the rows in order. Once a row settles the current turn, stop evaluating later rows. Where a row applies only to some decisions, evaluate later rows for the remaining decisions.

| Priority | Current turn | Action |
|---|---|---|
| 1 | User skips research | Start zero routes and continue the requested work. |
| 2 | User names a specialist | Honor the named route and its scope. A single named specialist runs on its own. |
| 3 | A workflow is actively clarifying the audience, purpose, or core function | Let it lead without adding a question or starting research. Recheck when discussion moves to proposing or comparing approaches, even within that workflow. |
| 4 | Existing evidence answers a decision, or the change only affects local details | Reuse the evidence and cite the original sources. Reuse also applies to method follow-ups. Copy-only and unrelated changes start zero routes. |
| 5 | A new constraint changes a decision | Carry forward unaffected evidence. Apply the readiness check to the affected evidence gaps only. |
| 6 | A decision still needs evidence and the core function and design question are clear | When the current turn approaches proposing or comparing architecture, modules, or flows, research the uncovered decision in this turn before presenting approaches. Use the current turn or supplied material. Unresolved secondary preferences need not delay research. |
| 7 | No workflow is leading clarification and a missing core fact blocks targeted research | Ask one question about the missing decision-driving fact. If the reply remains vague, leave research pending and wait for the user to provide more detail naturally. |
| 8 | No applicable design decision | Continue the requested work. |


## Selecting routes

Use one shared design question for multi-route work, with a concrete subquestion for each route. Select by what would resolve the decision.

| Evidence needed | Same-package skill | Question to pass |
|---|---|---|
| Research framework or an empirical comparison of methods | paper-finding | Which published frameworks or tested methods address this input, output, and constraint? What can the evidence support here? |
| Open-source architecture to learn from | tool-finding | Which projects implement this workflow, and which source files or design documents support the architectural lessons? |
| Component to integrate | tool-finding | Which components satisfy the interface, stack, deployment, maintenance, and licensing requirements? |
| Reusable Agent workflow | skill-finding | Which concrete skills fit the task, target host, and allowed dependencies and adaptation? |

Tell tool-finding whether the intent is architecture reference, component integration, or both. Pass both subquestions when both apply and assess the two uses separately, even for the same repository. A library or framework mention alone does not require Agent skill research.

The specialist selector names are $dev-research-skill:paper-finding, $dev-research-skill:tool-finding, and $dev-research-skill:skill-finding. Inside the package, use the short names in the table to identify host-visible skills. If the needed skill cannot be loaded or read through the host, record that route as unavailable and keep working with accessible routes and existing evidence.

## Handoff and results

Send the project goal, known constraints, pending design decision, and relevant evidence already available along with the question. Retain the specialist's formal order, search and report budgets, snapshots, revision handling, and missing-source rules. A project-specific preference can be explained with its conditions.

For each result, state the design decision it informs, the tradeoffs, and what the project still needs to validate. Put clickable evidence beside each recommendation, citation, or alternative. Use the specialist report’s source index when available. Apply the same checks when the host search supplies the evidence directly.

- For a retained paper, include the verified publication page or DOI and the full text actually read. When an experiment bears on a pending choice, carry its comparison, metric and observed outcome into the handoff with the dataset or conditions and a section or table locator. For a method follow-up, check that observation first and cite it again if it answers the question. Reopen the same source for a missing detail before widening the search. Label an unread or inaccessible full text accordingly.
- For a retained repository, include its homepage and the specific source file or design document used. A claim about a component’s suitability for integration needs its runtime and license conditions or an explicit pending status. Architecture evidence supports the described design.
- Resolve a missing publication page or repository homepage from a verified DOI, publisher record, or repository identity when feasible. If a required link or fact remains unavailable, name the gap next to the result. Mark discovery leads as unverified. Add a deduplicated source list for the other entries in the candidate pool for this round, including filtered-out, ineligible, and unassessed entries.

A completed search with zero qualifying results should say what was searched and which conditions removed the candidates. A failed source should be identified with the evidence it prevented from being verified. Continue with usable evidence and other available routes. Keep unsupported decisions provisional and state what evidence would resolve them. Return the informed decisions and unresolved evidence gaps to the Agent or workflow that was leading the design discussion, including when research is empty or a source fails. If no other workflow is leading, use the handoff to continue the requested design work.

Group the handoff by pending design decision. For each decision, give the supported conclusion or open question, its conditions, and original evidence. When combining specialist appendices, retain the paper, repository, and concrete skill identities and each link’s evidence role, even when several entries share a URL.
