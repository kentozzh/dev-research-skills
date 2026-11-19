# dev-research-skills

[Chinese edition](README-zh.md)

Four Codex skills help you research a software design before you commit to it. Use them to compare open-source components, find reusable agent skills, or check what a paper actually demonstrated. Each specialist produces a Chinese report with ranked candidates, evidence for individual requirements, and links to the original sources.

| Skill | When to use it |
| --- | --- |
| `using-dev-research` | Your goal is clear and you need to decide which design questions deserve outside research. |
| `tool-finding` | You need a library, component, or project to adopt or study. |
| `skill-finding` | You want an agent skill that fits a particular host and workflow. |
| `paper-finding` | You want experimental evidence for a method or architecture and need to understand its limits. |

## Quick start on Windows

You need Codex and Python 3.11 or later. From the repository root in PowerShell, build the project-local skills archive:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/build_plugin.py --output dist
.\.venv\Scripts\python.exe scripts/build_plugin.py --check dist/dev-research-skill
.\.venv\Scripts\python.exe scripts/build_project_skills.py --plugin dist/dev-research-skill --output dist/dev-research-skill-project.zip
```

Extract the ZIP at the root of the project where you want to use the skills. Its `.agents/skills/` directory belongs directly under that root. Open a new Codex chat in the target project and try:

```text
$dev-research-skill:tool-finding Find a Python library for offline PDF text extraction on Windows. Compare license terms and handling of scanned pages.
```

Replace `tool-finding` with any skill in the table to select it explicitly. You can also start with `$dev-research-skill:using-dev-research` and describe a design decision.

## Other installation options

**Codex plugin.** Copy the complete `dist/dev-research-skill/` directory to `plugins/dev-research-skill/` in the target Git project. Register it in `.agents/plugins/marketplace.json`. For an existing marketplace, append the plugin entry to its `plugins` array and keep its name.

```json
{
  "name": "local-repo",
  "plugins": [
    {
      "name": "dev-research-skill",
      "source": { "source": "local", "path": "./plugins/dev-research-skill" },
      "policy": { "installation": "AVAILABLE", "authentication": "ON_INSTALL" },
      "category": "Productivity"
    }
  ]
}
```

Restart Codex, install the plugin from the project's local marketplace in **Plugins**, then select a skill in a new chat.

**Standalone specialist.** To install just one finder in a host that supports skill directories, build and validate the three standalone bundles:

```powershell
.\.venv\Scripts\python.exe scripts/build_skills.py --output dist
.\.venv\Scripts\python.exe scripts/validate_skills.py dist
```

Copy the entire generated `dist/<skill-name>/` directory into your host's skills directory. Its `scripts/finder.py` entry point runs with Python 3.11+ and the standard library.

## How a recommendation is produced

The agent records your constraints, reads sources, and cites evidence for its assessments. The Python core stores the observations separately, checks them against the request, and ranks eligible candidates. Research is read-only. A report distinguishes missing evidence, conflicting observations, and provider failures.

For an offline run, save this as a UTF-8 `request.json`:

```json
{
  "skill": "tool-finding",
  "raw_request": "Choose a PDF text extractor for Windows",
  "hard_constraints": { "offline": "Documents must stay on the device" }
}
```

```powershell
.\.venv\Scripts\python.exe -m finder_core prepare --request request.json --run-dir .runs/pdf
.\.venv\Scripts\python.exe -m finder_core rank --run-dir .runs/pdf
.\.venv\Scripts\python.exe -m finder_core report --run-dir .runs/pdf --format markdown
```

This example starts with an empty candidate pool. To rank your own candidates, run `import` with an observation batch and `assess` with assessments before `rank`. Use `discover` and `enrich` when you need online sources. See the [data contracts](docs/contracts.md) and [paper provider guide](docs/paper-providers.md) for input formats and source coverage.

## Sources and limitations

GitHub, arXiv, OpenAlex, and Semantic Scholar have different coverage and quotas. When available, the tools read `GITHUB_TOKEN`, `OPENALEX_API_KEY`, and `SEMANTIC_SCHOLAR_API_KEY` from the process environment. Keep credentials out of request files. Anonymous GitHub discovery has a smaller request budget and falls back to repository discovery and file inspection.

This is a preview for Windows and Codex. The bundled venue data covers selected conferences and editions. Citation counts retain their provider labels, and claims about experiments require evidence from the paper. Run snapshots are written under the directory passed to `--run-dir`; reports go to standard output unless you supply `--output`.
