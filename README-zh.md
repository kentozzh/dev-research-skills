# dev-research-skills

[English edition](README.md)

这四个 Agent 技能用于软件设计阶段的技术调研。你可以用它们比较开源组件、寻找适合当前工作流的 Agent 技能，或核对一篇论文的实验能否支持你的设计。三个专业检索技能均输出中文报告，列出候选排序、各项要求的证据和原始来源。

| 技能 | 适用场景 |
| --- | --- |
| `using-dev-research` | 项目目标已经明确，需要判断哪些设计问题值得调研。 |
| `tool-finding` | 寻找可以采用或借鉴的库、组件和开源项目。 |
| `skill-finding` | 寻找适合指定宿主和工作流的 Agent 技能。 |
| `paper-finding` | 核对方法或架构的实验证据，了解适用条件和局限。 |

## 在项目中安装

根据目标项目使用的编程助手选择安装包。每个包都包含调研路由、三个检索技能及其 Python 脚本和参考文件。

| 宿主及官方技能指南 | `--host` 参数值 | 解压后的目录 |
| --- | --- | --- |
| [Codex](https://developers.openai.com/codex/skills/) | `codex` | `.agents/skills/` |
| [Claude Code](https://code.claude.com/docs/en/skills) | `claude-code` | `.claude/skills/` |
| [Cursor](https://cursor.com/docs/skills) | `cursor` | `.cursor/skills/` |
| [Kimi Code](https://moonshotai.github.io/kimi-cli/en/customization/skills.html) | `kimi-code` | `.kimi/skills/` |
| [OpenCode](https://opencode.ai/docs/skills/) | `opencode` | `.opencode/skills/` |
| [Pi](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/skills.md) | `pi` | `.pi/skills/` |
| [Qwen Code](https://qwenlm.github.io/qwen-code-docs/en/users/features/skills/) | `qwen-code` | `.qwen/skills/` |
| [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.md) | `deepseek-harness` | `.dsh/skills/` |

使用 Python 3.11 或更高版本，在本仓库根目录构建。以下 PowerShell 示例选择 Claude Code。要为其他宿主构建，把 `$agent` 改为表中对应的值。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python scripts/build_plugin.py --output dist
$agent = "claude-code"
python scripts/build_project_skills.py --host $agent --output "dist/$agent.zip"
python -m zipfile -e "dist/$agent.zip" "C:\path\to\target-project"
```

在 macOS 或 Linux 上，用 `source .venv/bin/activate` 激活环境，再把宿主参数值和目标路径代入相同的 Python 命令。将 ZIP 解压到运行编程助手的项目根目录。在该项目中新开会话，试试下面的请求。

```text
请使用 tool-finding 技能，比较可在 Windows 离线提取 PDF 文本的 Python 库，并说明各自的许可条款和对扫描页的支持。
```

如果需要助手判断调研方向，可以点名 `using-dev-research`。在 Codex 中也可以用 `$dev-research-skill:tool-finding` 显式选择技能。省略 `--host` 会构建原有的 Codex 项目包。

## 其他安装方式

**作为 Codex 插件安装。** 将整个 `dist/dev-research-skill/` 复制到目标 Git 项目的 `plugins/dev-research-skill/`，再将插件登记到 `.agents/plugins/marketplace.json`。如果项目已有 marketplace，保留其名称，向 `plugins` 数组追加此条目。

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

重启 Codex，在 **Plugins** 中从项目的本地 marketplace 安装插件，然后在新的项目对话中选择技能。

**独立安装一个检索技能。** 如果宿主支持技能目录，可以构建并校验三个独立分发包。

```powershell
.\.venv\Scripts\python.exe scripts/build_skills.py --output dist
.\.venv\Scripts\python.exe scripts/validate_skills.py dist
```

将所需的整个 `dist/<skill-name>/` 复制到宿主的技能目录。包内的 `scripts/finder.py` 入口只需 Python 3.11 或更高版本及其标准库。

## 推荐结果如何生成

Agent 记录需求约束、阅读来源并引用证据作出评价。Python 核心单独保存来源事实，依据请求校验评价，并对符合条件的候选排序。调研过程只读，报告会区分证据缺失、观察冲突和来源访问失败。

要试用离线流程，先将以下内容保存为 UTF-8 编码的 `request.json`。

```json
{
  "skill": "tool-finding",
  "raw_request": "为 Windows 选择 PDF 文本提取工具",
  "hard_constraints": { "offline": "文档必须保留在本机" }
}
```

```powershell
.\.venv\Scripts\python.exe -m finder_core prepare --request request.json --run-dir .runs/pdf
.\.venv\Scripts\python.exe -m finder_core rank --run-dir .runs/pdf
.\.venv\Scripts\python.exe -m finder_core report --run-dir .runs/pdf --format markdown
```

此示例从空候选池开始。要给自己的候选排序，请在 `rank` 前用 `import` 导入观察批次，再用 `assess` 提交评价。需要补充在线资料时可使用 `discover` 和 `enrich`。输入格式和来源覆盖范围见[数据契约](docs/contracts.md)及[论文来源指南](docs/paper-providers.md)。

## 数据来源和限制

GitHub、arXiv、OpenAlex 和 Semantic Scholar 各有不同的覆盖范围和请求额度。工具可从进程环境读取 `GITHUB_TOKEN`、`OPENALEX_API_KEY` 和 `SEMANTIC_SCHOLAR_API_KEY`。请将凭据保存在请求文件之外。匿名访问 GitHub 时，请求预算较低，检索会回退到仓库发现和具体文件核读。

内置会议数据仅覆盖部分会议及届次。引用数保留提供方标记，核实实验结论需要论文中的证据。运行快照保存在 `--run-dir` 指定的目录。报告默认输出到标准输出，也可用 `--output` 指定文件。
