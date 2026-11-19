# dev-research-skills

[English edition](README.md)

## dev-research-skills 是什么？

dev-research-skills 帮你在动手开发前回答三个问题，用已有研究、成熟项目和可复用工具，设计一套可行、高效的系统。

| 开发时的问题 | 技能交付什么 |
| --- | --- |
| **哪些设计框架已经过研究验证？** | `paper-finding` 查找在相近任务上做过实验的方案，指出论文验证了哪些环节、与什么基线比较、测得什么结果，以及你的项目需要复测哪些条件。 |
| **哪些开源项目和我的设计思路相近？** | `tool-finding` 找到可供借鉴的项目，从源码或设计文档梳理模块边界、输入输出和取舍，让你判断哪些设计适合自己的约束。 |
| **哪些环节已有工具或 Agent 技能可用？** | `tool-finding` 核对组件接口、依赖和许可；`skill-finding` 核读具体技能文件，检查宿主和工具要求，说明哪些可以直接用、哪些要适配，避免重复开发。 |

安装后，在项目对话中把目标、输入、预期输出和约束告诉 `using-dev-research`，也可以直接点名一个检索技能。

> 我要在 CPU 上做本地文档搜索。输入一句查询，输出按相关性排序的文档 ID。哪种检索流程有实验依据？相近项目怎样拆分建索引和查询？有没有可直接接入的搜索组件，以及能帮我写回归测试的 Agent 技能？

检索技能会给出中文报告，附上原始来源、方案比较和待验证项。在这个案例中，BEIR 论文给出了检索质量与延迟的对照，Pyserini 提供了索引模块的设计参考，SQLite FTS5 通过了本地排序验证。测试技能则核对到了具体文件、依赖和许可。[查看验证案例与可复跑示例](docs/local-search-case.md)

## 从 GitHub 安装与更新

选择你实际使用的编程助手。除 Kimi 的会话命令和 Cursor 的界面操作外，下面的命令都在终端执行。含 `&&` 的一行适用于 Bash、zsh 或 PowerShell 7。安装后在项目中新开会话，试试上面的请求。三个检索技能需要 Python 3.11 或更高版本。

| 编程助手 | 安装 | 更新 |
| --- | --- | --- |
| [Codex](https://developers.openai.com/plugins/build/plugins) | `codex plugin marketplace add kentozzh/dev-research-skills && codex plugin add dev-research-skill@dev-research` | `codex plugin marketplace upgrade dev-research && codex plugin add dev-research-skill@dev-research` |
| [Claude Code](https://code.claude.com/docs/en/discover-plugins) | `claude plugin marketplace add kentozzh/dev-research-skills && claude plugin install dev-research-skill@dev-research` | `claude plugin marketplace update dev-research && claude plugin update dev-research-skill@dev-research` |
| [Cursor](https://cursor.com/docs/plugins) | 在支持 GitHub 导入的 Customize 或团队 Marketplace 中选择 **Import from Repo**，粘贴 `https://github.com/kentozzh/dev-research-skills`，安装 **Dev Research Skills**。 | 在 marketplace 设置中选择 **Refresh**，或开启 **Auto Refresh**。 |
| [Kimi Code](https://moonshotai.github.io/kimi-code/en/customization/plugins.html) | `/plugins install https://github.com/kentozzh/dev-research-skills/tree/main` | 在 Kimi 中再次执行安装命令，然后执行 `/reload`。 |
| [OpenCode 2.x](https://opencode.ai/docs/plugins/) | `opencode plugin add github:kentozzh/dev-research-skills` | `opencode plugin update`（更新已配置的插件） |
| [Pi](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/packages.md) | `pi install git:github.com/kentozzh/dev-research-skills` | `pi update --extension git:github.com/kentozzh/dev-research-skills` |
| [Qwen Code](https://qwenlm.github.io/qwen-code-docs/en/users/extension/introduction/) | `qwen extensions install https://github.com/kentozzh/dev-research-skills.git --ref main`，出现选择提示时选 `dev-research-skill`。 | `qwen extensions update dev-research-skill` |
| [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/boot/app-boot) | `dsh plugin --profile headless add github:kentozzh/dev-research-skills#main` | `dsh plugin --profile headless update dev-research-skill` |

**OpenCode 1.x** 使用项目的 `opencode.json`。在已有的 `plugin` 数组中添加 `"dev-research-skill@git+https://github.com/kentozzh/dev-research-skills.git#main"`，然后重启。如果该版本锁定了 Git 修订，重新安装这个插件以刷新缓存。

**DeepSeek Harness** 的安装和更新命令都需要 `pnpm`。将两处 `headless` 换成你实际启动的 profile，例如 `web`。Kimi 插件里的技能带有命名空间，例如 `/skill:dev-research-skill:tool-finding`。

## 下载 ZIP 安装到单个项目

如果当前客户端没有仓库导入入口，也可以用 GitHub CLI 在项目根目录运行一行命令来安装或更新**最新 Release**。以 Cursor 为例，换成下表中的文件名即可用于其他宿主。命令会在当前目录写入或替换下载的 ZIP，并解压技能。

```sh
gh release download --repo kentozzh/dev-research-skills --pattern cursor.zip --clobber && python -m zipfile -e cursor.zip .
```

手动下载步骤如下。

1. 从下表下载你的编程助手对应的 ZIP。每个包都包含四个技能，运行检索脚本需要 Python 3.11 或更高版本。
2. 将 ZIP 直接解压到**使用技能的项目根目录**，保留包内的隐藏目录。例如，Claude Code 解压后应能找到 `你的项目/.claude/skills/tool-finding/SKILL.md`。
3. 在该项目中新开一个助手会话，试试上面的示例请求。

| 宿主及官方指南 | 下载 ZIP | 解压后的项目目录 |
| --- | --- | --- |
| [Codex](https://developers.openai.com/codex/skills/) | [codex.zip](https://github.com/kentozzh/dev-research-skills/releases/latest/download/codex.zip) | `.agents/skills/` |
| [Claude Code](https://code.claude.com/docs/en/skills) | [claude-code.zip](https://github.com/kentozzh/dev-research-skills/releases/latest/download/claude-code.zip) | `.claude/skills/` |
| [Cursor](https://cursor.com/docs/skills) | [cursor.zip](https://github.com/kentozzh/dev-research-skills/releases/latest/download/cursor.zip) | `.cursor/skills/` |
| [Kimi Code](https://moonshotai.github.io/kimi-code/en/customization/skills#skill-locations) | [kimi-code.zip](https://github.com/kentozzh/dev-research-skills/releases/latest/download/kimi-code.zip) | `.kimi/skills/` |
| [OpenCode](https://opencode.ai/docs/skills/) | [opencode.zip](https://github.com/kentozzh/dev-research-skills/releases/latest/download/opencode.zip) | `.opencode/skills/` |
| [Pi](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/skills.md) | [pi.zip](https://github.com/kentozzh/dev-research-skills/releases/latest/download/pi.zip) | `.pi/skills/` |
| [Qwen Code](https://qwenlm.github.io/qwen-code-docs/en/users/features/skills/) | [qwen-code.zip](https://github.com/kentozzh/dev-research-skills/releases/latest/download/qwen-code.zip) | `.qwen/skills/` |
| [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.md) | [deepseek-harness.zip](https://github.com/kentozzh/dev-research-skills/releases/latest/download/deepseek-harness.zip) | `.dsh/skills/` |

**使用 Kimi Code 2.6.3 安装 v1.1.0 ZIP 时**，解压后请在项目根目录运行 `kimi --skills-dir .kimi/skills`。如果希望以后正常启动时自动发现技能，可将解压出的各个技能目录复制到 `.kimi-code/skills/`。

在 Windows 实际会话中，OpenCode、Pi、Qwen Code、DeepSeek Harness，以及按上述步骤启动的 Kimi Code 均成功调用了路由技能。Codex 和 Claude Code 的技能列表均显示了四个技能。Cursor 的会话调用仍待验证。[实测版本与复现步骤](docs/v1.1.0-host-checks.md) · [GitHub Releases](https://github.com/kentozzh/dev-research-skills/releases)

## 技能一览

| 技能 | 适用场景 |
| --- | --- |
| `using-dev-research` | 项目目标已经明确，需要判断哪些设计问题值得调研。 |
| `tool-finding` | 寻找可以采用或借鉴的库、组件和开源项目。 |
| `skill-finding` | 寻找适合指定宿主和工作流的 Agent 技能。 |
| `paper-finding` | 核对方法或架构的实验证据，了解适用条件和局限。 |

在 Codex 中也可以用 `$dev-research-skill:tool-finding` 显式选择技能。

## 从源码构建

以下 PowerShell 命令从本仓库根目录构建 Claude Code 包。要为其他宿主构建，将 `$agent` 设为上表对应的 ZIP 文件名（去掉 `.zip`）。省略 `--host` 时默认构建 Codex 包。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python scripts/build_plugin.py --output dist
$agent = "claude-code"
python scripts/build_project_skills.py --host $agent --output "dist/$agent.zip"
python -m zipfile -e "dist/$agent.zip" "C:\path\to\target-project"
```

在 macOS 或 Linux 上，用 `source .venv/bin/activate` 激活环境，再把宿主参数值和目标路径代入相同的 Python 命令。

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
