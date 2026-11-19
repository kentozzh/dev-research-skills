# Maintaining dev-research-skills

## What a research result should deliver

Start with the decision the developer needs to make. Use the relevant research routes and explain how each finding informs that decision.

| Developer's question | Evidence to deliver |
| --- | --- |
| Which design has research support? | Cite the paper and the section, table, or figure that supports the design. Describe the evaluated alternatives, workload, metric, and result. Explain which assumptions carry over and what the developer still needs to measure. |
| What can we learn from a similar open-source project? | Identify the shared design problem. Link to source code or a design document at a specific revision and explain the module boundary, interface, or tradeoff the developer can borrow. Repository descriptions and star counts can help locate candidates. |
| Which tool or agent skill can we reuse? | Name the workflow step, link to the component entry point or specific `SKILL.md`, and check prerequisites and reuse terms. State exactly what was verified, such as inspecting files, running a minimal example, or invoking the skill in the target host. |

Use the [routing guide](skills/using-dev-research/references/routing.md) to select specialists and the [evidence contracts](docs/contracts.md) to record findings. The [local document search case](docs/local-search-case.md) shows how all three outcomes informed one project.

## Verify changes to skill behavior

When changing triggers, routing, evidence requirements, or report conclusions, run the same user request before and after the change. Record the expected behavior and the observed difference. Choose a case that can expose the specific mistake. For example, when changing architecture assessment, start with only a repository description and verify that the design remains unconfirmed. Then supply the relevant implementation and check that the report explains what can be borrowed.

## Verify host integrations

For each affected host, follow the documented installation path in a clean project and start a fresh session. Exercise the entry point promised to users. For automatic discovery, try a request without skill names, such as “How should I add local document search to a CPU-only Python app?” For explicit invocation, use the documented command. Record the host version, install method, skill invoked, and evidence returned. When only the package has been checked, describe that check and mark in-host invocation as unverified. See the [installation instructions](README.md#install-and-update-from-github).

## Describe contributions

Keep each change focused on one user problem. Describe what the user experienced, which behavior or hosts the change affects, and how another maintainer can reproduce the result. If a source was unavailable or rate-limited, identify the missing evidence, any alternative source actually checked, and which conclusions remain open.
