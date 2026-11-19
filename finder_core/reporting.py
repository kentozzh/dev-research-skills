"""Structured result and a concise Chinese Markdown projection."""
from __future__ import annotations

import json
import re
from datetime import timedelta, timezone
from importlib.resources import files

from .contracts import Candidate, CohortSummary, Evidence, RankedReport, VenueRecord
from .evidence import content_hash, get_metric, metric_name
from .scoring import metric_value, parse_timestamp
from .source_links import build_source_index, markdown_link, source_appendix, source_line
from .skill_inventory import candidate_skill_path
from .validation import ARCHITECTURE_CONDITION, ContractError


def render_report(report: RankedReport, format: str) -> str:
    p = report.provenance
    if p.get("venue_config_hash") is not None and p["venue_config_hash"] != content_hash({
            "records": p.get("venue_records", []), "evidence": p.get("venue_evidence", {})}):
        raise ContractError("report.venue_config_hash", "saved venue evidence snapshot changed; rerank current facts")
    rows = build_source_index(report)
    if format == "json":
        payload = report.to_dict()
        payload["provenance"]["source_index"] = rows
        return json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2)
    if format != "markdown":
        raise ContractError("report.format", "requires markdown or json")
    if report.provenance.get("request", {}).get("skill") in {"tool-finding", "skill-finding"}:
        return _render_tool_report(report, rows)
    return _render_paper_report(report, rows)



def _render_paper_report(report: RankedReport, rows: list[dict]) -> str:
    """Render recorded paper facts and judgments without new scientific claims."""
    p = report.provenance
    request, evidence = p.get("request", {}), dict(p.get("evidence", {}))
    evidence.update({key: value for key, value in p.get("venue_evidence", {}).items() if key not in evidence})
    cards = {cid: Candidate.from_dict(value) for cid, value in p.get("candidates", {}).items()}
    assessments, components = p.get("assessments", {}), p.get("components", {})
    from .venues import PUBLICATION_FIELDS, publication_fact, resolve_venue, summarize_awards
    publication_evidence = {key: Evidence.from_dict(item) for key, item in evidence.items()}
    records = [VenueRecord.from_dict(item) for item in p.get("venue_records", [])]

    def safe(value):
        return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    def refs(ids):
        return " ".join(markdown_link(eid, evidence[eid]["source_url"]) for eid in ids if eid in evidence)

    def raw(metric):
        value = json.dumps(metric.value, ensure_ascii=False) if isinstance(metric.value, bool) else safe(metric.value) if metric.value is not None else "未获取"
        return f"{value} [{safe(metric.status)}] · {safe(metric.provider)} · {metric.fetched_at.isoformat()} {refs(metric.evidence_ids)}".rstrip()

    def fact(cid, key):
        if key in PUBLICATION_FIELDS:
            metric = publication_fact(cards[cid], key, publication_evidence)
            return raw(metric) if metric is not None else "未核实（来源冲突或范围缺失） [unavailable]"
        values = [raw(metric) for name, metric in cards[cid].metrics.items() if metric_name(name, metric) == key]
        return "；".join(values) or "未获取 [unavailable]"

    def award_text(cid):
        # Display only: points already came from the shared scoring helper. A
        # redundant candidate award Metric is not required to name its proof.
        shown = []
        if any(metric_name(key, metric) == "award" for key, metric in cards[cid].metrics.items()):
            shown.append(fact(cid, "award"))
        if components.get(cid, {}).get("award_bonus", 0) > 0:
            record = resolve_venue(cards[cid], records, evidence=publication_evidence)
            doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", "", cards[cid].identifiers.get("doi", ""), flags=re.I).lower()
            checked = set(components[cid].get("venue_evidence_ids", []))
            for edition in record.award_scope.get("editions", []) if record else []:
                if edition.get("year") != value(cid, "publication_year"):
                    continue
                for award in edition.get("awards", []):
                    if ("doi:" + doi in award.get("member_ids", []) and award.get("raw_name")
                            and value(cid, "publication_track") in award.get("tracks", [])
                            and value(cid, "publication_type") in award.get("types", [])
                            and set(award.get("evidence_ids", [])).issubset(checked)):
                        shown.append(safe(award["raw_name"]) + "（已核实映射） " + refs(award.get("evidence_ids", [])))
        return "；".join(shown) or "未核实奖项 [unavailable]"

    def value(cid, key):
        metric = publication_fact(cards[cid], key, publication_evidence) if key in PUBLICATION_FIELDS else get_metric(cards[cid], key)
        return metric.value if metric is not None and metric.status == "verified" else None

    def name(cid):
        # Naming is a display projection, not a request to resolve one metric.
        # Preserve provider variants while leaving identity/ambiguity untouched.
        titles = {}
        for key, metric in cards[cid].metrics.items():
            if (metric_name(key, metric) == "title" and metric.status == "verified"
                    and isinstance(metric.value, str) and metric.value.strip()):
                titles.setdefault(metric.value, set()).add(metric.provider)
        if titles:
            shown = "；".join(safe(title) + "（" + ", ".join(safe(provider) for provider in sorted(providers)) + "）"
                for title, providers in sorted(titles.items()))
            return ("标题记录：" if len(titles) > 1 else "") + shown
        return safe(cards[cid].identifiers.get("title") or cid)

    links = {row["candidate_id"]: source_line(row) for row in rows}

    def number(value):
        return f"{value:.2f}" if value is not None else "待核实"

    def judgment(item, score=False):
        if not item:
            return "待核实（未提交当前评估）"
        if score:
            score_value = item.get("value") if item.get("status") == "verified" else None
            label = "待核实" if score_value is None else "满足" if score_value == 100 else "不满足" if score_value == 0 else "部分满足"
            label += "（" + str(score_value if score_value is not None else "null") + "）"
        else:
            label = {"pass": "满足", "fail": "不满足", "pending": "待核实"}.get(item.get("result"), "待核实")
        return f"{label} [{safe(item.get('status'))}]：{safe(item.get('reason', '证据不足'))} {refs(item.get('evidence_ids', []))}".rstrip()

    def scope_key(cid):
        return tuple(str(value(cid, key) or "未核实") for key in ("venue", "publication_year", "publication_track", "publication_type"))

    venue_ids = {key: f"venue-{index}" for index, key in enumerate(dict.fromkeys(scope_key(cid) for cid in cards), 1)}
    summary = f"按本轮契约与正式排序，默认先读 {name(report.formal[0])} {links[report.formal[0]]}。" if report.formal else "暂无可确认符合的候选。"
    constraints = ["- 原始任务：" + safe(request.get("raw_request", ""))]
    constraints.extend(f"- {safe(key)}：{safe(item)}" for key, item in request.get("hard_constraints", {}).items())
    constraints.extend("- 假设：" + safe(item) for item in request.get("assumptions", []))
    if request.get("preferences"):
        constraints.append("- 偏好/评分参考配置：" + safe(request["preferences"]))

    comparison = ["| 阅读顺序 | 论文 / 年份 / 版本 | 方法与任务 | 实际 venue / 状态 / track / type | 累计引用及来源日期 | 官方高被引 / 原奖名 | 落地条件 / L / I / V / 加分 / 指数 |",
        "|---|---|---|---|---|---|---|"]
    for index, cid in enumerate(report.formal, 1):
        a, c = assessments.get(cid, {}), components.get(cid, {})
        flags = "；".join(key + "=" + fact(cid, key) for key in ("top1", "top10"))
        scope = " / ".join(fact(cid, key) for key in ("venue", "publication_status", "publication_track", "publication_type"))
        parts = " / ".join(number(c.get(key)) for key in ("L", "I", "V", "award_bonus"))
        comparison.append(f"| {index} | {name(cid)} · {value(cid, 'publication_year') or '年份待核实'} {links[cid]} | {safe(a.get('relevance', {}).get('level'))}；{safe(a.get('reason'))} | {scope}；[{venue_ids[scope_key(cid)]}](#{venue_ids[scope_key(cid)]}) | {fact(cid, 'citations')} | {flags}；奖项 {award_text(cid)} | {safe(a.get('landing', {}).get('resources', {}).get('reason', '待核实'))}；{parts}；{number(report.scores.get(cid))} |")
    if not report.formal:
        comparison.append("无正式可比较结果；定性或待核实对象另列，不合成建议指数。")

    assessed = [cid for cid in cards if cid in assessments]
    matrix = []
    if assessed:
        matrix = ["| 条件 | " + " | ".join(name(cid) for cid in assessed) + " |", "|---|" + "---|" * len(assessed)]
        for key, description in request.get("hard_constraints", {}).items():
            matrix.append("| " + safe(description) + " | " + " | ".join(judgment(assessments[cid].get("hard_constraints", {}).get(key)) for cid in assessed) + " |")
        for key in ("task_transfer", "artifacts", "resources", "reproducibility"):
            omitted = p.get("omitted_items", {}).get(key)
            cells = ["统一不适用：" + safe(omitted) if omitted else judgment(assessments[cid].get("landing", {}).get(key), True) for cid in assessed]
            matrix.append("| Agent 落地判断：" + key + " | " + " | ".join(cells) + " |")

    decisions = []
    for index, cid in enumerate(report.formal):
        a, c = assessments.get(cid, {}), components.get(cid, {})
        decisions.extend([f"### {name(cid)}", "", f"- {'首选依据' if index == 0 else '备选适用条件'}（Agent 判断）：{safe(a.get('reason', '待核实'))}",
            "- 论文版本与研究产物入口：" + links[cid] + "；已记录版本 " + safe(cards[cid].versions),
            f"- 实际阅读深度：{safe(a.get('reading_depth'))}；相关性：{safe(a.get('relevance', {}).get('level'))}；{refs(a.get('relevance', {}).get('evidence_ids', []))}"])
        for key, item in a.get("landing", {}).items():
            omitted = p.get("omitted_items", {}).get(key)
            decisions.append(f"- Agent 落地判断 {safe(key)}：" + ("统一不适用：" + safe(omitted) if omitted else judgment(item, True)))
        decisions.extend(["- 实现与许可：" + fact(cid, "official_implementation") + "；" + fact(cid, "code_license"),
            "- 原文报告资源以上述已读判断与引用为准；本轮没有实测，目标项目成本仍需验证。",
            "- 最低验证任务（尚未执行）：",
            "  - 目标：" + safe(request.get("raw_request", "")),
            "  - 输入与基线：围绕上述目标任务及已记录的拟迁移组件准备少量代表性输入，保留现有方法或系统作为基线；具体比较方式依已读证据和任务契约确定。",
            "  - 观测与记录：依据适用的已读评估说明选择质量和资源指标，记录输出、测量结果、环境及证据/日志；协议未读或指标未定时先补齐资料。",
            "  - 通过条件：同时满足当前契约的全部硬条件和用户确认的效果/资源阈值；记录失败原因后重新评估。"])
        if c.get("provisional_influence"):
            decisions.append("- 暂定引用观察：官方归一化窗口尚未完整。")
        if c.get("venue_limitations"):
            decisions.extend("- 渠道证据限制：" + safe(item) for item in c["venue_limitations"])
        decisions.append("")

    venues = []
    award_summaries = summarize_awards(records)
    statistics = p.get("venue_statistics", {})
    cohort_summaries = [(label, CohortSummary.from_dict(item)) for label, field in (("逐年", "annual"), ("跨年合并", "combined")) for item in statistics.get(field, [])]

    def ratio(value):
        return f"{value * 100:.2f}%" if value is not None else "不可计算"

    def cohort_lines(label, summary):
        manifests = summary.manifests
        years = ", ".join(str(m.year) for m in manifests)
        scope = manifests[0]
        lines = [f"- {label} cohort：{safe(scope.venue)} / {years} / {safe(scope.track)} / {safe(scope.type)} / {safe(scope.database)}；查询时间 " + ", ".join(m.queried_at.isoformat() for m in manifests)]
        lines.extend("  - 完整母集来源：" + markdown_link("目录", url) + "；排除规则 " + safe(manifest.exclusion_rules) for manifest in manifests for url in manifest.source_urls)
        if not all(m.complete for m in manifests):
            return lines + ["  - 完整母集缺失，未计算引用比例。"]
        lines.extend([
            f"  - 官方 top1 窗口：H/n_h={summary.H}/{summary.n_h}，观察比例 {ratio(summary.high_ratio)}；覆盖 n_h/N={summary.n_h}/{summary.N}（{ratio(summary.high_coverage)}）；未知 {summary.N-summary.n_h}。",
            f"  - 累计零引用：Z/n_c={summary.Z}/{summary.n_c}，观察比例 {ratio(summary.zero_ratio)}；覆盖 n_c/N={summary.n_c}/{summary.N}（{ratio(summary.zero_coverage)}）；未知 {summary.N-summary.n_c}。",
            f"  - 未知项极端范围（非置信区间）：高被引 {ratio(summary.high_lower)}–{ratio(summary.high_upper)}；零引用 {ratio(summary.zero_lower)}–{ratio(summary.zero_upper)}。",
            "  - 高被引窗口/方法：" + safe(summary.high_window) + "；零引用窗口：" + safe(summary.zero_window) + "；计算方法：" + safe(summary.calculation_method),
            "  - 比较资格：" + ("高覆盖观察，仍只描述本数据库及本母集。" if summary.comparable else "探索观察，不用于跨 venue 排名；完整字段覆盖不等于归一化口径可比。")])
        lines.extend("  - 限制：" + safe(item) for item in summary.missing_reasons)
        return lines

    def supplied_acceptance_lines(key, record):
        # A source excerpt is display evidence, never numeric input. The
        # observed unstructured fallback is limited to main-track documents:
        # demo/workshop pages can themselves quote unrelated main statistics.
        if key[2] != "main":
            return []
        names = {key[0].casefold()}
        if record:
            names.update(name.casefold() for name in [record.venue_id, *record.aliases])
        observations = []
        for eid, source in evidence.items():
            scope = source.get("scope", {})
            excerpt = source.get("excerpt", "")
            if (source.get("status") != "verified" or source.get("source_category") != "official"
                    or str(scope.get("venue", "")).casefold() not in names
                    or str(scope.get("year", "")) != key[1] or scope.get("track") != "main"
                    or scope.get("type", key[3]) != key[3]
                    or not any(term in excerpt.casefold() for term in ("accept", "录用", "接收"))):
                continue
            observations.append("  - 原文观测：" + safe(excerpt) + " " + refs([eid]) + "；观察时间 " + safe(source.get("fetched_at")))
        if not observations:
            return []
        return ["- 本轮 main 轨道官方来源摘录（未推算录用率；适用论文类型与分母定义以原文为准）：", *observations]

    for key, vid in venue_ids.items():
        cid = next(cid for cid in cards if scope_key(cid) == key)
        record = resolve_venue(cards[cid], records, evidence=publication_evidence)
        supplied_acceptance = supplied_acceptance_lines(key, record)
        venues.extend([f'<a id="{vid}"></a>', "", "### " + " / ".join(safe(item) for item in key), ""])
        if record is None:
            venues.append("- CCF：当前已核实映射未覆盖此 venue/track/type；不推断不在目录，也不继承主会等级。")
            if not supplied_acceptance:
                venues.append("- 录用率：未核实适用届次和完整口径。")
            venues.append("- 奖项设置：未核实适用届次和完整口径。")
        else:
            ccf = record.ccf
            venues.append("- CCF（按当前目录评价，发表当年等级未核实）：" + (raw(ccf) + "；目录版本/适用范围 " + safe(ccf.scope) if ccf else "未获取") + "；记录版本 " + safe(record.version))
            venues.append(f"- 录用率原始数：{record.acceptance_numerator} / {record.acceptance_denominator}；官方分母/范围：{safe(record.acceptance_scope)} {refs(record.acceptance_evidence_ids)}")
            award = award_summaries.get(record.venue_id)
            if award:
                venues.append(f"- 设奖持续性：{award['setting_numerator']}/{award['setting_denominator']} 已核实届次；证据覆盖 {award['verified_editions']}/{award['target_editions']} 目标届次；{safe(award['scope_note'])} {refs(record.award_evidence_ids)}")
                for rate in award["award_rates"]:
                    venues.append(f"  - {rate['year']} 原奖名 {safe(rate['raw_names'])}；track/type {safe(rate['tracks'])}/{safe(rate['types'])}；获奖论文比例 " + (ratio(rate["ratio"]) if rate["ratio"] is not None else "未计算（名单/分母不完整或范围不一致）") + "；" + safe(rate["limitation"]))
            else:
                venues.append("- 奖项设置与覆盖：未核实；缺页不等于没有奖。")
        venues.extend(supplied_acceptance)
        target_venue = record.venue_id if record else key[0]
        matches = [(label, summary) for label, summary in cohort_summaries if summary.manifests and all(
            m.venue.casefold() == target_venue.casefold() and m.track == key[2] and m.type == key[3] for m in summary.manifests)]
        if matches:
            venues.append("- venue 引用背景（独立完整 cohort，不参与单篇指数）：")
            for label, summary in matches:
                venues.extend(cohort_lines(label, summary))
        else:
            venues.append("- venue 引用背景：完整母集缺失，未计算；不使用本轮搜索样本作为母集。")

    supplementary = []
    for label, ids in (("定性阅读线索（无指数）", report.qualitative), ("待核实（非正式采用推荐）", report.pending)):
        for cid in ids:
            a = assessments.get(cid, {})
            depth = "摘要级判断 / 暂定" if a.get("reading_depth") == "abstract" else "阅读深度 " + str(a.get("reading_depth", "metadata"))
            supplementary.extend([f"- {label}：{name(cid)}；{depth}；{safe(a.get('reason', '未完成评估'))}；{safe(p.get('missing_reasons', {}).get(cid, ''))}", "  - 入口：" + links[cid]])
            supplementary.extend("  - " + safe(key) + "：" + judgment(item) for key, item in a.get("hard_constraints", {}).items() if item.get("result") != "pass")
    excluded = []
    for cid in report.excluded:
        a = assessments.get(cid, {})
        excluded.extend([f"- {name(cid)}：{safe(a.get('reason', '硬条件或相关性不符'))}", "  - 原奖名：" + fact(cid, "award")])
        excluded.extend("  - " + safe(key) + "：" + judgment(item) for key, item in a.get("hard_constraints", {}).items() if item.get("result") == "fail")

    sources = [f"- run/revision/snapshot：{safe(p.get('run_id'))} / {safe(p.get('contract_revision'))} / {safe(p.get('snapshot_id'))}",
        f"- 实际检查数量：{safe(p.get('checked_counts', {}))}；已读全文 {sum(a.get('reading_depth') == 'full_text' for a in assessments.values())}；摘要级 {sum(a.get('reading_depth') == 'abstract' for a in assessments.values())}。",
        f"- 请求台账：{safe(p.get('request_counts', {}))}；宿主搜索 {len(p.get('host_search_events', []))} 次；政策预算 {safe(p.get('policy', {}).get('budgets', {}))}。",
        "- 未覆盖来源/缺失字段按以下限制和原始观测记录；来源服务失败表示覆盖不足，不表示没有论文。"]
    if report.group:
        sources.append(f"- 冻结比较组：{safe(report.group.member_ids)}；模式 {safe(report.group.mode)}；有效权重 {safe(report.group.effective_weights)}；统一省略项 {safe(report.group.omitted_items)}。")
    if p.get("venue_config_hash"):
        sources.append("- 渠道证据快照版本：" + safe(p.get("venue_config_versions", [])) + "；hash " + safe(p["venue_config_hash"]))
    if statistics:
        sources.append("- 完整 cohort 派生快照绑定：" + safe(statistics.get("provenance", {})))
        sources.extend("- cohort 范围/采集限制：" + safe(item) for item in statistics.get("limitations", []))
        sources.extend("- cohort 原始来源/哈希及限制：" + safe(item) for item in statistics.get("source_provenance", []))
    zone = p.get("report_timezone", "Asia/Shanghai")
    tz = timezone(timedelta(hours=8)) if zone == "Asia/Shanghai" else timezone.utc
    if zone not in {"Asia/Shanghai", "UTC"}:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(zone)
    for key, label in (("scoring_reference_at", "评分参考时间（不代表实时检索）"), ("generated_at", "报告生成时间")):
        if p.get(key):
            sources.append(f"- {label}：{parse_timestamp(p[key]).astimezone(tz).isoformat()} [{safe(zone)}]")
    sources.extend("- " + safe(item) for item in report.limitations)
    sources.append("- 偏好敏感性：" + ("首选随影响力/采用条件偏好变化。" if report.sensitivity.get("first_changed") else "首选未变化。" if "lower" in report.sensitivity else safe(report.sensitivity.get("skipped", "未计算"))))
    for label in ("lower", "higher"):
        branch = report.sensitivity.get(label)
        if branch:
            sources.append(f"  - {label}：权重 {safe(branch['weights'])}；首选 {name(branch['first']) if branch['first'] else '无'}；Top 3 {', '.join(name(cid) for cid in branch['top3'])}")
    if p.get("close_pairs"):
        sources.append("- 分差接近（非统计显著性）：" + safe(p["close_pairs"]))
    for event in p.get("host_search_events", []):
        sources.append("- 宿主搜索：" + safe(event))
    for eid, source in evidence.items():
        sources.append(f"- {refs([eid])}：{safe(source.get('source_category'))}；{safe(source.get('status'))}；实际观察时间 {safe(source.get('fetched_at'))}；{safe(source.get('excerpt'))}")
    for cid, card in cards.items():
        for key, metric in card.metrics.items():
            sources.append(f"- {name(cid)} / {safe(key)}：{raw(metric)}；口径 {safe(metric.scope)}；方法版本 {safe(metric.method_version)}")
    template = files("finder_core").joinpath("resources/templates/paper-finding.md").read_text(encoding="utf-8")
    return template.format(summary=summary, constraints="\n".join(constraints), comparison="\n".join(comparison),
        matrix="\n".join(matrix) or "尚无当前逐项评估。", decisions="\n".join(decisions) or "暂无正式候选；未提出可执行的采用结论。",
        venues="\n".join(venues) or "尚无可核实的论文 venue 范围。", supplementary="\n".join(supplementary) or "无。",
        excluded="\n".join(excluded) or "无。", sources="\n".join(sources) + source_appendix(rows))


def _render_tool_report(report: RankedReport, rows: list[dict]) -> str:
    """Project recorded facts and Agent judgments without inventing new judgments."""
    p = report.provenance
    request = p.get("request", {})
    links = {row["candidate_id"]: source_line(row) for row in rows}
    is_skill = request.get("skill") == "skill-finding"
    architecture = not is_skill and request.get("preferences", {}).get("tool_intent") == "architecture_reference"
    architecture_key = next((key for key, description in request.get("hard_constraints", {}).items()
                             if description == ARCHITECTURE_CONDITION), None)
    usability_keys = ("host_tools", "dependencies_permissions", "installation", "io_examples") if is_skill else ("functionality", "stack", "resources", "documentation")
    cards = {cid: Candidate.from_dict(card) for cid, card in p.get("candidates", {}).items()}
    assessments, components = p.get("assessments", {}), p.get("components", {})
    evidence = p.get("evidence", {})

    def safe(value):
        return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    def name(cid):
        if cid not in cards:
            return safe(cid)
        identifiers = cards[cid].identifiers
        value = identifiers.get("full_name", cid)
        if is_skill and cards[cid].kind == "skill":
            value += " · " + (candidate_skill_path(cards[cid]) or "路径待核实")
        return safe(value)

    def refs(ids):
        return " ".join(markdown_link(eid, evidence[eid]["source_url"]) for eid in ids if eid in evidence)

    def judgment(item, *, score=False):
        if not item:
            return "待核实（未提交当前评估）"
        if score:
            value = item.get("value") if item.get("status") == "verified" else None
            status = "待核实" if value is None else "满足" if value == 100 else "不满足" if value == 0 else "部分满足"
            shown = f"{status}（{value if value is not None else 'null'}）"
        else:
            shown = {"pass": "满足", "fail": "不满足", "pending": "待核实"}.get(item.get("result"), "待核实")
        return f"{shown}：{safe(item.get('reason', '证据不足'))} {refs(item.get('evidence_ids', []))}".rstrip()

    def fact(cid, key):
        metric = get_metric(cards[cid], key)
        if metric is None:
            return "未获取或来源冲突"
        value = safe(metric.value) if metric.value is not None else "未获取"
        return f"{value} [{safe(metric.status)}] {refs(metric.evidence_ids)}".rstrip()

    def number(value):
        return f"{value:.2f}" if value is not None else "待核实"

    def skill_versions(cid):
        identifiers = cards[cid].identifiers
        versions = set(cards[cid].versions) | {value for key,value in identifiers.items() if key.split("@", 1)[0] == "commit_sha"}
        return "、".join(safe(value) for value in sorted(versions) if re.fullmatch(r"[0-9a-fA-F]{40}", value)) or "未核实"

    def skill_license(cid):
        metric = get_metric(cards[cid], "license")
        scope = metric.scope if metric else {}
        label = "仓库许可" if scope.get("level") == "repository" else "许可观测（范围 " + safe(scope or "未标明") + "）"
        conditions = assessments.get(cid, {}).get("hard_constraints", {})
        keys = [key for key in conditions if key == "license" or key.endswith("_license") or
                request.get("hard_constraints", {}).get(key) == "License explicitly covers the intended reuse"]
        # Display the recorded judgment, never infer an SPDX value from prose.
        applicable = "；".join(judgment(conditions[key]) for key in keys) or "待核实（未提交目录复用评估）"
        return label + " " + fact(cid, "license") + "；目录复用判断：" + applicable

    summary = f"建议优先检查 {name(report.formal[0])} {links[report.formal[0]]}。" if report.formal else "暂无可确认符合的候选。"
    if architecture:
        summary = (f"架构借鉴正式第 1 名为 {name(report.formal[0])} {links[report.formal[0]]}。"
                   if report.formal else "暂无可确认符合本轮架构借鉴条件的候选。")
    constraints = [f"- 原始任务：{safe(request.get('raw_request', ''))}"]
    if not is_skill:
        constraints.append(f"- 调研用途：{'架构借鉴' if architecture else '组件复用'}")
    constraints.extend(f"- {safe(key)}：{safe(value)}" for key, value in request.get("hard_constraints", {}).items())
    if request.get("preferences"):
        constraints.append(f"- 偏好/评分参考配置：{safe(request['preferences'])}")
    constraints.extend(f"- 假设：{safe(value)}" for value in request.get("assumptions", []))

    comparison = ["| 顺序 | " + ("技能路径" if is_skill else "工具") + " | 需求覆盖 / Agent 判断 | " + ("仓库级 Star / Fork / Watch" if is_skill else "Star / Fork / Watch") + " | 维护/版本/许可 | U / P / M | 建议指数 |",
                  "|---|---|---|---|---|---|---|"]
    for index, cid in enumerate(report.formal, 1):
        a, c = assessments.get(cid, {}), components.get(cid, {})
        values = " / ".join(number(c.get(key)) for key in ("U", "P", "M"))
        counts = " / ".join(fact(cid, key) for key in ("stars", "forks", "watchers"))
        version = "；已核实版本 SHA " + skill_versions(cid) if is_skill else ""
        license_text = skill_license(cid) if is_skill else "许可 " + fact(cid, "license")
        comparison.append(f"| {index} | {name(cid)} {links[cid]} | 必须项通过；{safe(a.get('relevance', {}).get('level'))}；{safe(a.get('reason', ''))} | {counts} | {fact(cid, 'pushed_at')}；release {fact(cid, 'released_at')}；{license_text}{version} | {values} | {number(report.scores.get(cid))} |")
    if not report.formal:
        comparison.append("暂无正式可比较结果；以下定性/待核实对象没有合成建议指数。")

    # Deeply assessed candidates, not all metadata discovery cards, form the matrix.
    assessed = [cid for cid in cards if cid in assessments]
    matrix = []
    if assessed:
        matrix.extend(["| 条件 | " + " | ".join(name(cid) for cid in assessed) + " |",
                       "|---|" + "---|" * len(assessed)])
        for key, description in request.get("hard_constraints", {}).items():
            cells = [judgment(assessments[cid].get("hard_constraints", {}).get(key)) for cid in assessed]
            matrix.append(f"| {safe(description)} | " + " | ".join(cells) + " |")
        for key in usability_keys:
            if key in p.get("omitted_items", {}):
                cells = [f"统一不适用：{safe(p['omitted_items'][key])}"] * len(assessed)
            else:
                cells = [judgment(assessments[cid].get("usability", {}).get(key), score=True) for cid in assessed]
            matrix.append(f"| Agent 采用判断：{key} | " + " | ".join(cells) + " |")
    else:
        matrix.append("尚无当前契约下的逐项评估。")

    decisions = []
    for index, cid in enumerate(report.formal):
        a, c = assessments.get(cid, {}), components.get(cid, {})
        label = "首选依据" if index == 0 else "备选适用条件"
        decisions.extend([f"### {name(cid)}", "", links[cid], "", f"- {label}（Agent 判断）：{safe(a.get('reason', '待核实'))}",
                          f"- 相关性：{safe(a.get('relevance', {}).get('level'))}；{safe(a.get('relevance', {}).get('reason', ''))} {refs(a.get('relevance', {}).get('evidence_ids', []))}"])
        if architecture:
            design = a.get("hard_constraints", {}).get(architecture_key)
            decisions.append(f"- 架构借鉴正式第 {index + 1} 名。架构证据：{judgment(design)}")
        if index == 0 and len(report.formal) > 1:
            other = report.formal[1]
            decisions.append(f"- 与第二名 {name(other)} {links[other]} 对照：相关性 {safe(a.get('relevance', {}).get('level'))} / {safe(assessments[other].get('relevance', {}).get('level'))}；同层按公开指数排序。备选情形：{safe(assessments[other].get('reason', '待核实'))}")
        elif index == 0:
            decisions.append("- 当前只有一个正式合格候选，尚无已确认的正式备选。")
        for key, item in a.get("usability", {}).items():
            value = f"统一不适用：{safe(p['omitted_items'][key])}" if key in p.get("omitted_items", {}) else judgment(item, score=True)
            decisions.append(f"- Agent 采用判断 {safe(key)}：{value}")
        source = "仓库推送代理信号" if c.get("maintenance_proxy") else safe(c.get("maintenance_source", "待核实"))
        if is_skill:
            if c.get("maintenance_source") == "path_updated_at":
                observed_path = c.get("maintenance_scope", {}).get("path")
                source = ("技能目录更新代理（" + safe(observed_path) + "）；不证明 SKILL.md 单文件更新"
                          if observed_path and observed_path != candidate_skill_path(cards[cid])
                          else "路径更新证据（" + safe(observed_path or candidate_skill_path(cards[cid])) + "）")
            else:
                source = "仓库代理（" + safe(c.get("maintenance_source", "待核实")) + "；不证明技能路径更新）"
            identifiers = cards[cid].identifiers
            decisions.extend(["- 复用部分与适配点（Agent 判断）：" + safe(a.get("reason", "待核实")),
                "- 已核实版本 SHA：" + skill_versions(cid) + "；读取 ref " + safe(identifiers.get("source_ref", "未记录")) + "；" + refs(cards[cid].discovery_evidence_ids),
                "- 许可范围：仓库许可记录不自动证明子路径许可、共享文件或第三方材料覆盖；以逐条件评估为准。"])
        decisions.append(f"- 阅读深度：{safe(a.get('reading_depth', 'metadata'))}；维护依据：{source}；距评分参考时间 {safe(c.get('maintenance_days'))} 天。")
        if architecture:
            decisions.append("- 归档、更新与版本观测用于说明设计的背景和迁移条件。")
        elif not is_skill and metric_value(cards[cid], "released_at") is None:
            decisions.append("- 无已核实 release；这不等于已归档或不可用，应结合已读安装/源码使用路径判断。")
        license_text = skill_license(cid) if is_skill else "许可 " + fact(cid, "license")
        decisions.append(f"- 观测事实：{license_text}；归档 {fact(cid, 'archived')}。")
        if index == 0 and architecture:
            decisions.append("- 最低验证任务（尚未执行）：选取本项目的最小样例，走查拟借鉴模块的输入、输出和边界情况，记录仍需验证的迁移条件。")
        elif index == 0:
            items = [(key, item) for key, item in a.get("usability", {}).items()
                     if key not in p.get("omitted_items", {})]
            weakest = min(items, key=lambda pair: pair[1].get("value") if pair[1].get("value") is not None else -1) if items else None
            decisions.extend(["- 最低验证任务（尚未执行）：", f"  - 目标：{safe(request.get('raw_request', ''))}",
                              "  - 输入：按已读官方示例准备一份最小正常输入及一份边界/无效输入；在目标环境检查该接口的实际输出。",
                              f"  - 文档依据：{judgment(a.get('usability', {}).get('io_examples' if is_skill else 'documentation'), score=True)}"])
            if weakest:
                decisions.append(f"  - 优先核对 {safe(weakest[0])}：{judgment(weakest[1], score=True)}")
            required = "；".join(safe(value) for value in request.get("hard_constraints", {}).values())
            decisions.extend([f"  - 预期：输出符合上述官方接口/示例，且同时满足 {required or '当前契约'}。",
                              "  - 判定：记录输出差异、环境/资源条件和失败原因；任一硬条件失败则重新选型。此处仅提出任务，未运行候选。"])
        decisions.append("")

    supplementary = []
    for label, ids in (("定性补充（无建议指数）", report.qualitative), ("同仓补充", report.same_repository_supplementary), ("待核实（非正式推荐）", report.pending)):
        for cid in ids:
            a = assessments.get(cid, {})
            supplementary.append(f"- {label}：{name(cid)} {links[cid]}；{safe(a.get('reason', '尚未完成证据评估'))}；{safe(p.get('missing_reasons', {}).get(cid, ''))}")
            for key, item in a.get("hard_constraints", {}).items():
                if item.get("result") != "pass":
                    supplementary.append(f"  - {safe(key)}：{judgment(item)}")
    excluded = []
    for cid in report.excluded:
        a = assessments.get(cid, {})
        label = "历史/受限方案；" if metric_value(cards[cid], "archived") is True else ""
        excluded.append(f"- {name(cid)}：{label}{safe(a.get('reason', '条件或相关性不符'))}")
        excluded.extend(f"  - {safe(key)}：{judgment(item)}" for key, item in a.get("hard_constraints", {}).items() if item.get("result") == "fail")

    sources = [f"- run/revision/snapshot：{safe(p.get('run_id'))} / {safe(p.get('contract_revision'))} / {safe(p.get('snapshot_id'))}",
               f"- 实际检查数量：{safe(p.get('checked_counts', {}))}；已记录深入阅读 {sum(a.get('reading_depth', 'metadata') != 'metadata' for a in assessments.values())} 项。",
               f"- 请求台账：{safe(p.get('request_counts', {}))}；宿主搜索 {len(p.get('host_search_events', []))} 次。"]
    if report.group:
        sources.append(f"- 冻结比较组：{len(report.group.member_ids)} 项；权重 {safe(report.group.effective_weights)}；互动规模权重 {safe(p.get('popularity_weights'))}；统一省略项 {safe(report.group.omitted_items)}。")
    zone = p.get("report_timezone", "Asia/Shanghai")
    tz = timezone(timedelta(hours=8)) if zone == "Asia/Shanghai" else timezone.utc
    if zone not in {"Asia/Shanghai", "UTC"}:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(zone)
    for key, label in (("scoring_reference_at", "评分参考时间（不代表实时检索）"), ("generated_at", "报告生成时间")):
        if p.get(key):
            sources.append(f"- {label}：{parse_timestamp(p[key]).astimezone(tz).isoformat()} [{safe(zone)}]")
    sources.extend(f"- {safe(item)}" for item in report.limitations)
    if p.get("close_pairs"):
        sources.append("- 分差接近（非统计显著性）：" + "；".join(f"{name(a)} / {name(b)}" for a, b in p["close_pairs"]))
    sources.append("- 偏好敏感性：" + ("首选随热度/采用条件偏好变化。" if report.sensitivity.get("first_changed") else "首选未变化。" if report.group else "无完整比较组，跳过。"))
    for label in ("lower", "higher"):
        branch = report.sensitivity.get(label)
        if branch:
            sources.append(f"  - {label}：权重 {safe(branch['weights'])}；首选 {name(branch['first'])}；Top 3 {', '.join(name(cid) for cid in branch['top3'])}")
    for event in p.get("host_search_events", []):
        sources.append(f"- 宿主搜索：{safe(event.get('query'))}；{safe(event.get('searched_at'))}")
    for eid, source in evidence.items():
        sources.append(f"- {refs([eid])}：{safe(source.get('source_category'))}；{safe(source.get('status'))}；观察时间 {safe(source.get('fetched_at'))}；{safe(source.get('excerpt'))}")
        if is_skill and source.get("scope", {}).get("reference_kind"):
            sources.append("  - 引用路径：" + safe(source.get("source_object", {}).get("reference", {})) + "；仅资料核读，未执行。")
    # Preserve every raw observation, including conflicting or provider-qualified facts.
    for cid, card in cards.items():
        for key, metric in card.metrics.items():
            scope = "；范围 " + safe(metric.scope) if is_skill else ""
            sources.append(f"- {name(cid)} / {safe(key)}：{safe(metric.value) if metric.value is not None else '未获取'}；{safe(metric.status)}；{safe(metric.provider)}{scope}；{metric.fetched_at.isoformat()} {refs(metric.evidence_ids)}")
    template_name = "skill-finding" if is_skill else "tool-finding"
    template = files("finder_core").joinpath("resources/templates/" + template_name + ".md").read_text(encoding="utf-8")
    return template.format(summary=summary, constraints="\n".join(constraints), comparison="\n".join(comparison),
                           matrix="\n".join(matrix), decisions="\n".join(decisions) or "暂无正式候选。",
                           supplementary="\n".join(supplementary) or "无。", excluded="\n".join(excluded) or "无。",
                           sources="\n".join(sources) + source_appendix(rows))
