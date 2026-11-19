"""Project frozen candidate identities and observations into reader-facing sources."""
from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

from .contracts import Candidate, Evidence, RankedReport
from .evidence import checked_source, supports_assessment_subject
from .providers._paper import arxiv, doi, doi_url
from .skill_inventory import candidate_skill_path
from .validation import reportable_url


ROLES = {"original": "原页", "full_text": "全文", "repository": "仓库", "skill_file": "技能文件",
         "implementation": "实现证据", "official_resource": "官方资源", "discovery": "发现页"}
STATUS = {"verified": "已核查", "unverified": "已知地址未核查", "failed": "访问失败"}
DISPOSITIONS = {"formal": "正式推荐", "qualitative": "定性补充", "pending": "待核实",
                "excluded": "已排除", "same_repository_supplementary": "同仓补充",
                "eligible_over_limit": "合格但超额", "discovery_only": "仅发现"}


def markdown_link(label, url):
    if not reportable_url(url):
        return ""
    label = re.sub(r"([\\\[\]|])", r"\\\1", str(label)).replace("\n", " ").replace("\r", " ")
    return f"[{label}]({quote(url, safe=':/?#[]@!$&*+,;=%~')})"


def _catalog(url):
    host = urlsplit(url).hostname.lower()
    return any(host == domain or host.endswith("." + domain) for domain in
               ("semanticscholar.org", "openalex.org", "huggingface.co", "paperswithcode.com"))


def _role(key, url, kind):
    key = key.split("@", 1)[0].lower()
    if key in {"discovery", "hf"} or (kind == "paper" and _catalog(url) and key in {"paper", "published", "version"}):
        return "discovery"
    if key in {"doi", "published", "publisher", "arxiv", "version", "paper", "anthology", "original"}:
        return "original"
    if key in {"pdf", "fulltext", "full_text"}:
        return "full_text"
    if key in {"repo", "repository", "github"}:
        return "repository"
    if key in {"skill", "skill_file"}:
        return "skill_file"
    if key.startswith("file:") or key in {"code", "implementation", "source"}:
        return "implementation"
    if key in {"official", "official_resource", "project", "data", "dataset", "resources", "docs"}:
        return "official_resource"
    return "discovery"


def _evidence_role(item, card):
    if item.source_category in {"host_search", "third_party", "agent"} or _catalog(item.source_url):
        return "discovery"
    if item.source_category == "repository" or item.scope.get("level") == "file":
        if item.scope.get("path"):
            return "skill_file" if card.kind == "skill" and item.scope["path"] == candidate_skill_path(card) else "implementation"
        return "official_resource"
    if item.source_category == "paper":
        return "full_text" if urlsplit(item.source_url).path.lower().endswith(".pdf") else "original"
    return "official_resource" if item.source_category == "official" else "discovery"


def _body_sections_read(item):
    depths = [item.scope.get("reading_depth"), item.source_object.get("reading_depth")]
    if any(depth in ("metadata", "abstract") for depth in depths):
        return False
    if "full_text" in depths:
        return True
    # A section locator may describe metadata. An explicit list of sections
    # actually read also supports numbered headings with work-specific titles.
    headings = (r"(?:§|section\s+|table\s+|figure\s+)\d|\b(?:methods?|methodology|results?|experiments?|"
                r"evaluation|limitations?|appendix|discussion|conclusions?|datasets?)\b|方法|实验|结果|评估|局限|附录|表\s*\d")
    exclusions = r"abstract|summary|metadata|unread|not read|unavailable|not accessed|摘要|未读|待读|未核实"
    for field, value in (("section", item.scope.get("section")), ("sections_read", item.source_object.get("sections_read"))):
        parts = re.split(r"[,;、，；]", value) if isinstance(value, str) else value
        if not isinstance(parts, list):
            continue
        for section in parts:
            if not isinstance(section, str) or re.search(exclusions, section, re.I):
                continue
            title = section.strip()
            if re.match(headings, title, re.I):
                return True
            if field == "sections_read" and re.match(r"\d+(?:\.\d+)*[.)]?\s+[^\W\d_]", title):
                return True
    return False


def _assessed_read_ids(assessment):
    if assessment.get("reading_depth") != "full_text":
        return set()
    judgments = [assessment.get("relevance", {})]
    for key in ("hard_constraints", "landing"):
        judgments.extend(assessment.get(key, {}).values())
    return {eid for judgment in judgments for eid in judgment.get("evidence_ids", [])}


def _candidate_targets(card):
    yield from card.urls.items()
    for key, identifier in card.identifiers.items():
        if key.split("@", 1)[0] == "doi" and (canonical := doi(identifier)):
            yield "doi", doi_url(canonical)
        if key.split("@", 1)[0] == "arxiv" and (canonical := arxiv(identifier)):
            yield "arxiv", "https://arxiv.org/abs/" + canonical
    if card.kind == "paper":
        for version in card.versions:
            if canonical := arxiv(version):
                yield "arxiv", "https://arxiv.org/abs/" + canonical
    repo = card.identifiers.get("full_name", "")
    if card.identifiers.get("github_repository_id") and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        yield "repository", "https://github.com/" + repo


def build_source_index(report: RankedReport) -> list[dict]:
    p = report.provenance
    evidence = {eid: Evidence.from_dict(raw) for eid, raw in p.get("evidence", {}).items()}
    dispositions = {cid: "eligible_over_limit" for cid in set(report.scores) | set(p.get("components", {}))}
    for name in ("formal", "qualitative", "same_repository_supplementary", "pending", "excluded"):
        dispositions.update(dict.fromkeys(getattr(report, name), name))
    rows = []
    for cid, raw in p.get("candidates", {}).items():
        card = Candidate.from_dict(raw)
        roles = {}
        for key, url in _candidate_targets(card):
            if reportable_url(url):
                roles.setdefault(url, set()).add(_role(key, url, card.kind))
        read_ids = _assessed_read_ids(p.get("assessments", {}).get(cid, {}))
        observations = {}
        for item in evidence.values():
            url = item.source_url
            if not reportable_url(url) or not supports_assessment_subject(item, card, evidence):
                continue
            purposes = roles.setdefault(url, set())
            observed_role = _evidence_role(item, card)
            if not purposes or observed_role in {"implementation", "skill_file", "full_text"}:
                purposes.add(observed_role)
            if (item.evidence_id in read_ids and item.source_category == "paper" and checked_source(item)
                    and not _catalog(url) and _body_sections_read(item)):
                roles[url].add("full_text")
            if checked_source(item) or item.status in {"failed", "stale"}:
                status = {"verified": "verified", "failed": "failed", "stale": "unverified"}[item.status]
                # For simultaneous conflicting records, show the conservative status.
                observation = (item.fetched_at, {"verified": 1, "unverified": 2, "failed": 3}[status], status)
                if url not in observations or observation > observations[url]:
                    observations[url] = observation
        links = [{"role": role, "url": url, "access_status": observations[url][2] if url in observations else "unverified"}
                 for url, purposes in roles.items() for role in sorted(purposes)]
        links.sort(key=lambda link: (list(ROLES).index(link["role"]),
                   not bool(re.search(r"(?:/|ref=)[a-fA-F0-9]{40}(?:[/?&#]|$)", link["url"])), link["url"]))
        title = card.identifiers.get("title") or card.identifiers.get("full_name") or cid
        if card.kind == "paper":
            title = next((m.value for key, m in card.metrics.items() if key.split("@")[0].split(".")[-1] == "title"
                          and m.status == "verified" and isinstance(m.value, str)), title)
        if card.kind == "skill" and candidate_skill_path(card):
            title += " · " + candidate_skill_path(card)
        rows.append({"candidate_id": cid, "kind": card.kind, "name": title,
                     "disposition": dispositions.get(cid, "discovery_only"), "links": links})
    return rows


def source_line(row):
    links = row["links"]
    parts = [markdown_link(ROLES[x["role"]], x["url"]) + "（" + STATUS[x["access_status"]] + "）" for x in links]
    if not links or all(x["role"] == "discovery" for x in links):
        parts.append("原链待核实")
    return " ".join(parts)


def source_appendix(rows):
    lines = ["", "### 全候选来源", ""]
    for row in rows:
        title = re.sub(r"([\\\[\]*_`<>|])", r"\\\1", row["name"]).replace("\n", " ").replace("\r", " ")
        lines.append(f"- {title}（{DISPOSITIONS[row['disposition']]}） {source_line(row)}")
    if not rows:
        lines.append("本轮检索范围及限制见上文，候选池为空。")
    return "\n".join(lines)
