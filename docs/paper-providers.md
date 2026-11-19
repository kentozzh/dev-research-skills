# Paper providers and host imports

`finder_core discover` dispatches the request's `queries` to `arxiv`, `openalex`
and `semantic_scholar` (S2). `enrich --ids` uses every compatible registered paper
provider for explicit DOI/arXiv/OpenAlex/S2 identifiers, preserving each source's
facts separately. A title never authenticates a cross-source identity. The
runtime uses the Python standard library and GET requests only.

Author both `recent` and `classic` queries. Recent means the policy's preceding
24 calendar months as of actual retrieval; classic has no date restriction.
Initial actual network attempts, including retries, seed lookups and redirects,
are capped at 60 per lane within the shared 120-call paper budget. Fresh cache
hits are free. All structured calls, including enrichment and GitHub reads in a
paper run, share that same 120; commands/revisions/imports do not reset it.
Legacy `general` paper queries use the classic lane and record a limitation.
Reserved counters `transport_paper_initial_recent` and
`transport_paper_initial_classic` persist with `request_counts`. A spent lane
does not impose a provider cooldown. Host searches use their independent
8-event import ledger; omitted events cannot be observed or controlled by this
package.

Each initial query reads at most 40 entries. Providers return a continuation
hint and a partial-coverage limitation when the page is bounded; they do not
automatically exhaust every page or fetch full text. The canonical initial
candidate capacity remains 80 after identity deduplication. Enrichment consumes
one run-wide deep slot per selected candidate (maximum 12), regardless of how
many compatible sources are consulted.

The following strings are **this project's QuerySpec.query convention**, not
provider-native text search syntax:

| Provider | Incoming citations | Outgoing references |
| --- | --- | --- |
| OpenAlex | `citations:W1001` | `references:W1001` |
| S2 | `citations:ARXIV:2401.01234` | `references:DOI:10.5555/fixture.1` |

OpenAlex also resolves explicit DOI/arXiv seeds through its documented singleton
endpoint before querying `filter=cites:W...` or `filter=cited_by:W...`. S2 accepts
explicit DOI/arXiv identifiers or a 40-character hexadecimal S2 paper ID,
optionally prefixed `semantic_scholar:`; its documented `/paper/{id}/citations`
and `/references` responses contain `citingPaper` and `citedPaper` respectively.
Recent-chain queries apply the corresponding documented date filter. arXiv
returns an explicit unsupported-chain limitation without making a text search.
Chain query evidence retains the direction/seed, and each discovered card links
to query evidence as well as its source record. These are bounded neighborhood
observations, not proof of complete bibliographic coverage.

arXiv retains raw version IDs, same-work identity and observed version relations.
It preserves author-provided DOI/journal-reference strings without inferring
acceptance, venue, track, awards, or citations. Its metadata-only enrichment
cache uses the 30-day static-paper policy. OpenAlex/S2 detail responses contain
changing citation counts and use the 24-hour count policy; searches use 6 hours.
Cached/stale responses preserve their original observation dates and statuses.

OpenAlex `citation_normalized_percentile` is an object. Metrics `percentile`,
`top1`, `top10` use its official value/booleans, preserving the raw object in
evidence and the method marker
`openalex-citation-normalized-percentile-2026-11-10`. Scope records actual corpus,
its evidence basis, type/year/subfield normalization, publication-year-plus-three-year window and
whether that window is provisional at retrieval. Malformed individual metrics
become typed missing/failed observations. Contradictions among the official
percentile/flags, or zero citations with a positive high-citation observation,
remain `conflict`; no favorable correction is made. S2's
`influential_citations` remains a separate supplementary fact. Citation counts
from different databases are never summed, and missing counts are never zero.

OpenAlex corpus is `core`, `expansion`, or `unknown`. A boolean `is_xpac` is
retained in source evidence and sets `corpus_basis=is_xpac` (false means core;
true means expansion). An absent flag on a default works-list response uses
the documented list semantics with
`corpus_basis=documented_default_core_list` and `query_corpus=core`. A singleton
lookup has no such membership guarantee: absent/null flags use
`corpus_basis=missing_is_xpac`; invalid values use `invalid_is_xpac`, both with
unknown corpus. Invalid explicit list flags also remain unknown. Metadata and
raw source citation counts preserve these scopes and membership caveats.
The default influence policy is core only: expansion `percentile`/`top1`/`top10`
are null/not_applicable; unknown-membership normalized metrics are
null/unavailable. Their scopes retain `influence_policy=core_only` and the
reason, and the complete observed normalized object stays in Evidence. This
prevents singleton expansion records from entering a core comparison under a
false label. See the [official corpus documentation](https://help.openalex.org/data/works/corpus/)
and [is_xpac definition](https://help.openalex.org/data/works/attributes/#is_xpac).

ACL/HF/venue pages are read by the host and passed as a self-contained
ObservationBatch to `import --input`. Retain URL, actual reading time,
`scope.reading_depth`, source category, check method, explicit identifiers and
supporting excerpts. An ACL `publication_track` claim needs the exact explicitly
observed `publication_track` value in its supporting evidence's `source_object`
or scope. A substring in the Anthology ID does not establish the track. HF
paper-page model/data links do not establish an official implementation; use
separate primary author/repository evidence for that claim. Search summaries,
page popularity and linked artifacts do not establish a venue or award.

Endpoints/fields follow the timestamped source research. Additional citation
neighborhood/date-filter verification used [OpenAlex's official filter
reference](https://github.com/ourresearch/openalex-docs/blob/main/api-entities/works/filter-works.md),
[OpenAlex API recipes](https://help.openalex.org/how-to/api-recipes/), and
[S2's official Graph API reference](https://api.semanticscholar.org/api-docs/)
on 2026-11-17.
