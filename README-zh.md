# dev-research-skills

[English edition](README.md)

这四个 Codex 技能用于软件设计阶段的技术调研。你可以用它们比较开源组件、寻找适合当前工作流的 Agent 技能，或核对一篇论文的实验能否支持你的设计。三个专业检索技能均输出中文报告，列出候选排序、各项要求的证据和原始来源。

| 技能 | 适用场景 |
| --- | --- |
| `using-dev-research` | 项目目标已经明确，需要判断哪些设计问题值得调研。 |
| `tool-finding` | 寻找可以采用或借鉴的库、组件和开源项目。 |
| `skill-finding` | 寻找适合指定宿主和工作流的 Agent 技能。 |
| `paper-finding` | 核对方法或架构的实验证据，了解适用条件和局限。 |

## 在 Windows 上快速开始

准备好 Codex 和 Python 3.11 或更高版本。在仓库根目录打开 PowerShell，构建项目级技能包。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/build_plugin.py --output dist
.\.venv\Scripts\python.exe scripts/build_plugin.py --check dist/dev-research-skill
.\.venv\Scripts\python.exe scripts/build_project_skills.py --plugin dist/dev-research-skill --output dist/dev-research-skill-project.zip
```

将 ZIP 解压到需要使用技能的项目根目录，使 `.agents/skills/` 直接位于该目录下。在目标项目中新开 Codex 对话，试试这个请求。

```text
$dev-research-skill:tool-finding 为 Windows 选择能离线提取 PDF 文本的 Python 库，比较其许可条款和对扫描页的处理能力。
```

把 `tool-finding` 替换为表中的其他技能名，即可显式选择对应入口。如果还没确定调研方向，可以从 `$dev-research-skill:using-dev-research` 开始，描述当前要做的设计决定。

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

当前为面向 Windows 和 Codex 的预览版。内置会议数据仅覆盖部分会议及届次。引用数保留提供方标记，核实实验结论需要论文中的证据。运行快照保存在 `--run-dir` 指定的目录。报告默认输出到标准输出，也可用 `--output` 指定文件。
