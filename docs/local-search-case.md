# Designing local document search

This case records a run from v1.1.1. Starting with v1.1.2, tool and skill recommendations require at least 10,000 verified GitHub stars on the source repository.

A developer has a collection of text files and a CPU-only Python application. A query should return document IDs in relevance order, and documents must stay on the machine. Three design decisions follow from that brief.

## 1. Start with a measured retrieval design

In BEIR, one design ranks documents with BM25. A second passes the top 100 BM25 hits to a cross-encoder for reranking. On SciFact, Table 2 reports nDCG@10 of **0.665** and **0.688** respectively. Table 3 measures a different workload: mean CPU latency on one million DBpedia documents using eight Xeon cores. The corresponding results were **20 ms** and **6,100 ms**. Both figures are the authors’ measurements. [Publication](https://datasets-benchmarks-proceedings.neurips.cc/paper_files/paper/2021/hash/65b9eea6e1cc6bb9f0cd2a47751a186f-Abstract-round2.html) · [Full text, sections 4–5.1 and Tables 2–3](https://arxiv.org/pdf/2104.08663v4)

For this project, start with lexical retrieval and keep reranking optional. To decide whether to add it, label representative queries from the actual collection, then measure both nDCG@10 and latency on the deployment CPU. The paper used Anserini for BM25. Its timing cannot be assumed for SQLite.

## 2. Borrow a project’s module boundary

Pyserini takes records with an `id` and `contents`, builds a Lucene index, and opens that index in a separate query step. The guide exposes document IDs and scores. In the source, `LuceneSearcher` takes an index directory and constructs the underlying Java searcher. A useful boundary to borrow is therefore **document ingestion → stored index → ranked query results**. The application can rebuild the index separately and keep the same query interface if it later adds a reranker. This observation comes from source inspection. [Repository](https://github.com/castorini/pyserini) · [Indexing guide](https://github.com/castorini/pyserini/blob/f3e502b496e0cf631e7780ff31f502dc5ac0ed0f/docs/usage-index.md) · [Query implementation](https://github.com/castorini/pyserini/blob/f3e502b496e0cf631e7780ff31f502dc5ac0ed0f/pyserini/search/lucene/_searcher.py)

## 3. Reuse the search component and the testing workflow

**Search component.** SQLite FTS5 implements local indexing, matching and BM25 ranking. Python can call it through `sqlite3` when the linked SQLite build includes FTS5. SQLite documents the public-domain dedication for its original code. For this prototype the integration work is creating the table, inserting documents and querying by rank. [FTS5 manual](https://www.sqlite.org/fts5.html) · [SQLite terms](https://www.sqlite.org/copyright.html)

**Agent skill.** For a regression such as returning matches in insertion order, the Superpowers `test-driven-development` skill tells the agent to first observe a failing test for the desired behavior, make it pass, then run the project suite. It requires a way to edit the project and run its tests. The pinned skill links a companion testing guide, and the repository's MIT terms require retaining the notices when copying it. This check covered the files and prerequisites. Installation and invocation in individual hosts were outside the run. [Skill file](https://github.com/obra/superpowers/blob/22f0b463e7a5e579904dd6211a520321035526f7/skills/test-driven-development/SKILL.md) · [Required guide](https://github.com/obra/superpowers/blob/22f0b463e7a5e579904dd6211a520321035526f7/skills/test-driven-development/writing-good-tests.md) · [License](https://github.com/obra/superpowers/blob/22f0b463e7a5e579904dd6211a520321035526f7/LICENSE)

### Reproduce the component check

Run this in Python with FTS5 enabled. The stronger match is inserted second so that an implementation returning insertion order fails the assertion.

```python
import sqlite3

db = sqlite3.connect(":memory:")
db.execute("CREATE VIRTUAL TABLE docs USING fts5(body)")
db.executemany("INSERT INTO docs VALUES (?)", [
    ("cache disk sync",), ("cache cache cache",), ("disk only",)
])

def lookup(term):
    return [row[0] for row in db.execute(
        "SELECT rowid FROM docs WHERE docs MATCH ? ORDER BY rank", (term,)
    )]

assert lookup("cache") == [2, 1]
assert lookup("absent") == []
print(sqlite3.sqlite_version, lookup("cache"), lookup("absent"))
```

The local check returned `3.53.1 [2, 1] []`. It exercised index creation, matching, ranking and a query with no matches. Corpus-scale performance, tokenization for the target language and the benefit of reranking remain open.

## How the skills were verified

On 2026-11-19 the three specialist entry points processed four separate requests. The architecture and component requests used separate runs because they ask different questions of a repository. Host search supplied leads, then structured discovery used the following terms to resolve them. This was a targeted case study with one assessed result per request.

| Specialist and request | Live lookup | Result from the generated report |
| --- | --- | --- |
| `paper-finding` / `framework_discovery` | An arXiv title search for BEIR and a separate query containing only the terms “zero-shot”, “retrieval” and “evaluation” | Both searches returned the BEIR study. The merged pool held 16 papers. BEIR was the one assessed against the full text and entered the formal reading list. [Repeat the topic query](https://export.arxiv.org/api/query?search_query=ti%3A%22zero-shot%22%20AND%20ti%3A%22retrieval%22%20AND%20ti%3A%22evaluation%22&start=0&max_results=40) |
| `tool-finding` / `architecture_reference` | GitHub `repo:castorini/pyserini` | Module boundary supported by the indexing guide and query source. Target resource use was left open. |
| `tool-finding` / `component_reuse` | GitHub `repo:sqlite/sqlite` | Local use and reuse terms supported. The separate Python check above exercised the interface. |
| `skill-finding` for a Codex project with a test runner | GitHub `repo:obra/superpowers` | The concrete skill, its companion file and license were checked at a fixed commit. Host installation remained unverified. |

Each run used `prepare`, `discover`, `enrich`, `import`, `assess`, `rank` and `report` through the specialist's `scripts/finder.py`. GitHub search returned the repositories, but its API quota blocked later enrichment and skill-file inspection. The agent read the public primary sources separately and imported its checked observations. The three GitHub-based reports retained qualitative findings with no composite score. As a negative control, submitting the repository search result alone to pass the architecture condition failed validation. [Request and evidence formats](contracts.md) · [Routing and handoff](../skills/using-dev-research/references/routing.md)
