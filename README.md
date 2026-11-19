# dev-research-skills

[Chinese edition](README-zh.md)

## Quick install

1. Download the ZIP for your coding agent below. Each ZIP contains all four skills. The bundled finder scripts require Python 3.11 or later.
2. Extract the ZIP directly into **the root of the project where you use the agent**. Keep the hidden directory from the archive. For Claude Code, for example, you should see `your-project/.claude/skills/tool-finding/SKILL.md`.
3. Open a fresh agent session in that project and try the prompt below.

| Host and official guide | Download ZIP | Directory in your project |
| --- | --- | --- |
| [Codex](https://developers.openai.com/codex/skills/) | [codex.zip](https://github.com/kentozzh/dev-research-skills/releases/latest/download/codex.zip) | `.agents/skills/` |
| [Claude Code](https://code.claude.com/docs/en/skills) | [claude-code.zip](https://github.com/kentozzh/dev-research-skills/releases/latest/download/claude-code.zip) | `.claude/skills/` |
| [Cursor](https://cursor.com/docs/skills) | [cursor.zip](https://github.com/kentozzh/dev-research-skills/releases/latest/download/cursor.zip) | `.cursor/skills/` |
| [Kimi Code](https://moonshotai.github.io/kimi-cli/en/customization/skills.html) | [kimi-code.zip](https://github.com/kentozzh/dev-research-skills/releases/latest/download/kimi-code.zip) | `.kimi/skills/` |
| [OpenCode](https://opencode.ai/docs/skills/) | [opencode.zip](https://github.com/kentozzh/dev-research-skills/releases/latest/download/opencode.zip) | `.opencode/skills/` |
| [Pi](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/skills.md) | [pi.zip](https://github.com/kentozzh/dev-research-skills/releases/latest/download/pi.zip) | `.pi/skills/` |
| [Qwen Code](https://qwenlm.github.io/qwen-code-docs/en/users/features/skills/) | [qwen-code.zip](https://github.com/kentozzh/dev-research-skills/releases/latest/download/qwen-code.zip) | `.qwen/skills/` |
| [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.md) | [deepseek-harness.zip](https://github.com/kentozzh/dev-research-skills/releases/latest/download/deepseek-harness.zip) | `.dsh/skills/` |

```text
Use the tool-finding skill to compare Python libraries for offline PDF extraction on Windows. Include license terms and support for scanned pages.
```

Find all packages and release notes on [GitHub Releases](https://github.com/kentozzh/dev-research-skills/releases).

## Included skills

Four agent skills help you research a software design before you commit to it. Use them to compare open-source components, find reusable agent skills, or check what a paper actually demonstrated. Each specialist produces a Chinese report with ranked candidates, evidence for individual requirements, and links to the original sources.

| Skill | When to use it |
| --- | --- |
| `using-dev-research` | Your goal is clear and you need to decide which design questions deserve outside research. |
| `tool-finding` | You need a library, component, or project to adopt or study. |
| `skill-finding` | You want an agent skill that fits a particular host and workflow. |
| `paper-finding` | You want experimental evidence for a method or architecture and need to understand its limits. |

Use `using-dev-research` to choose a research route. In Codex you can also select a skill explicitly with `$dev-research-skill:tool-finding`.

## Build from source

Run these PowerShell commands from the repository root to build the Claude Code package. For another agent, set `$agent` to its ZIP filename without `.zip`. Omitting `--host` selects Codex.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python scripts/build_plugin.py --output dist
$agent = "claude-code"
python scripts/build_project_skills.py --host $agent --output "dist/$agent.zip"
python -m zipfile -e "dist/$agent.zip" "C:\path\to\target-project"
```

On macOS or Linux, activate the environment with `source .venv/bin/activate`, then use the same Python commands with your host value and target path.

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

The bundled venue data covers selected conferences and editions. Citation counts retain their provider labels, and claims about experiments require evidence from the paper. Run snapshots are written under the directory passed to `--run-dir`; reports go to standard output unless you supply `--output`.
