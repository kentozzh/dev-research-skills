"""OpenAlex work metadata and official source-specific normalized observations."""
from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

from ..contracts import Candidate
from ._paper import PaperProvider, arxiv, chain_query, checked_link_metadata, date_range, doi, doi_url, normalized_identity

API = "https://api.openalex.org/works"
PERCENTILE_METHOD = "openalex-citation-normalized-percentile-2026-11-10"


def work_id(value):
    if not isinstance(value,str):
        return None
    value = value.removeprefix("https://openalex.org/")
    return value.upper() if re.fullmatch(r"[wW]\d+",value) else None


def _locations(data):
    listed = data.get("locations")
    if not isinstance(listed, list):
        listed = []
    return [row for row in (data.get("primary_location"), data.get("best_oa_location"), *listed)
            if isinstance(row, dict)]


def _provider_links(data, index_url, identifiers):
    links = {"paper": index_url, "discovery": index_url}
    if "doi" in identifiers:
        links["doi"] = doi_url(identifiers["doi"])
    for location in _locations(data):
        source = location.get("source")
        if "publisher" not in links and isinstance(source, dict) and source.get("type") in (
            "journal", "conference", "ebook platform", "book series",
        ):
            landing = location.get("landing_page_url")
            host = urlsplit(landing).hostname.removeprefix("www.") if landing else None
            if host and host not in {
                "openalex.org", "api.openalex.org", "semanticscholar.org", "api.semanticscholar.org",
                "doi.org", "dx.doi.org", "arxiv.org", "export.arxiv.org", "huggingface.co",
            }:
                links["publisher"] = landing
        if "pdf" not in links and location.get("is_oa") is True:
            if pdf := location.get("pdf_url"):
                links["pdf"] = pdf
    return links


class OpenAlexProvider(PaperProvider):
    name = "openalex"
    method = "openalex-works-v1"

    def _work(self,data,result, *, query_corpus=None):
        if not isinstance(data,dict) or not (wid := work_id(data.get("id"))):
            self._limit("OpenAlex work missing valid explicit work ID")
            return None
        subject = "openalex:" + wid
        ids = {"openalex":wid}
        external = data.get("ids") if isinstance(data.get("ids"),dict) else {}
        if value := doi(data.get("doi") or external.get("doi")):
            ids["doi"] = value
        if value := arxiv(external.get("arxiv")):
            ids["arxiv"] = re.sub(r"v\d+$","",value)
        membership = data.get("is_xpac")
        if type(membership) is bool:
            corpus_scope = {"corpus":"expansion" if membership else "core", "corpus_basis":"is_xpac"}
        elif "is_xpac" not in data and query_corpus == "core":
            # Only a works list has documented default-core membership. An
            # explicit-ID singleton can return expansion despite that default.
            corpus_scope = {"corpus":"core", "corpus_basis":"documented_default_core_list"}
        else:
            corpus_scope = {"corpus":"unknown", "corpus_basis":
                "missing_is_xpac" if membership is None else "invalid_is_xpac"}
        if query_corpus is not None:
            corpus_scope["query_corpus"] = query_corpus
        selected = {key:data[key] for key in ("id","ids","doi","title","publication_year","publication_date","type","is_xpac",
            "cited_by_count","citation_normalized_percentile","primary_location","best_oa_location","locations",
            "abstract_inverted_index","referenced_works","updated_date") if key in data}
        for name in ("primary_location", "best_oa_location", "locations"):
            if name in selected:
                selected[name] = checked_link_metadata(selected[name])
        ev = self._evidence(result,subject,selected,corpus_scope)
        urls = _provider_links(selected, "https://openalex.org/" + wid, ids)
        card = Candidate(subject,"paper",ids,urls=urls,discovery_evidence_ids=[ev.evidence_id])
        location = data.get("primary_location")
        location = location if isinstance(location,dict) else {}
        source = location.get("source") if isinstance(location.get("source"),dict) else {}
        for key,value,unit in (("citations",data.get("cited_by_count"),"count"),
            ("publication_year",data.get("publication_year"),"year"),("publication_type",data.get("type"),"text"),
            ("title",data.get("title"),"text"),("venue",source.get("display_name"),"text"),("publication_track",None,"text")):
            card.metrics[key] = self._metric(value,unit,result,subject,ev,scope=corpus_scope)
        index = data.get("abstract_inverted_index")
        if isinstance(index,dict):
            words = {}
            valid = True
            for word,positions in index.items():
                if not isinstance(word,str) or not isinstance(positions,list) or any(type(p) is not int or p < 0 for p in positions):
                    valid = False
                    break
                for position in positions:
                    if position in words:
                        valid = False
                    words[position] = word
            abstract = " ".join(words[p] for p in sorted(words)) if valid and words else None
        else:
            abstract = None
        card.metrics["abstract"] = self._metric(abstract,"text",result,subject,ev,scope=corpus_scope)
        normalized = data.get("citation_normalized_percentile")
        normalized = normalized if isinstance(normalized,dict) else {}
        year = data.get("publication_year")
        window = type(year) is int and result.fetched_at.year <= year + 3
        scope = {**corpus_scope, "normalization":"type/publication_year/subfield",
            "citation_window":"publication year plus following three years", "provisional_window":window}
        for key,field,unit in (("percentile","value","percentile"),("top1","is_in_top_1_percent","boolean"),("top10","is_in_top_10_percent","boolean")):
            card.metrics[key] = self._metric(normalized.get(field),unit,result,subject,ev,
                scope={**scope,"field":"citation_normalized_percentile."+field},method=PERCENTILE_METHOD)
        percentile,top1,top10 = (card.metrics[key] for key in ("percentile","top1","top10"))
        count = card.metrics["citations"]
        # Retain contradictions rather than adjusting the observation in favor
        # of a score. A raw count alone never derives a high-citation flag.
        contradictions = []
        if top1.value is True and top10.value is False:
            contradictions.append("top1 implies top10")
        if percentile.status == "verified":
            if (top1.value is True and percentile.value < .99) or (top10.value is True and percentile.value < .9):
                contradictions.append("official percentile and flags disagree")
        if count.status == "verified" and count.value == 0 and (top1.value is True or top10.value is True or (percentile.value is not None and percentile.value != 0)):
            contradictions.append("zero citations contradict normalized high-citation observation")
        if contradictions:
            for metric in (percentile,top1,top10):
                if metric.value is not None:
                    metric.status = "conflict"
                    metric.scope["conflict_reason"] = "; ".join(contradictions)
            self._limit("OpenAlex citation normalization conflict; original fields retained without correction")
        if corpus_scope["corpus"] != "core":
            # Keep source values in evidence, but never let a singleton's
            # expansion/unknown membership enter the default-core influence.
            status = "not_applicable" if corpus_scope["corpus"] == "expansion" else "unavailable"
            reason = "OpenAlex normalized influence requires core corpus; observed membership is " + corpus_scope["corpus"]
            for metric in (percentile,top1,top10):
                metric.value, metric.status = None, status
                metric.scope.update(influence_policy="core_only", reason=reason)
            self._limit(reason)
        return card

    def _lookup(self,identifier):
        if value := work_id(identifier):
            return value
        if value := doi(identifier):
            return "https://doi.org/" + value
        if value := arxiv(identifier):
            return "arxiv:" + re.sub(r"v\d+$","",value)
        return None

    def search(self,query):
        start = len(self.evidence)
        direction,seed = chain_query(query.query)
        params = {"per_page":self.client.policy.capacity.paper_initial // 2,"page":1}
        filters = []
        if direction:
            wid = work_id(seed)
            if not wid:
                lookup = self._lookup(seed)
                if not lookup:
                    self._limit("OpenAlex chain requires an explicit DOI, arXiv or OpenAlex identity")
                    return self._batch([],start,partial=True)
                result,data = self._get(API+"/"+quote(lookup,safe=""))
                wid = work_id(data.get("id")) if isinstance(data,dict) else None
                if not wid:
                    self._limit("OpenAlex chain seed identity lookup unavailable")
                    return self._batch([],start,partial=True)
                self._evidence(result,query.query_id,{"requested_identity":seed,"resolved_openalex":wid},{"operation":"chain_seed"})
            filters.append(("cites:" if direction == "citations" else "cited_by:")+wid)
        else:
            params["search"] = query.query
        if query.route == "recent":
            filters.append("from_publication_date:"+date_range(self.client)[0])
        if filters:
            params["filter"] = ",".join(filters)
        result,data = self._get(API,params,query=True)
        if not isinstance(data,dict) or not isinstance(data.get("results"),list):
            self._limit("OpenAlex search envelope invalid or unavailable")
            return self._batch([],start,partial=True)
        extra = {"chain_direction":direction,"chain_seed":seed} if direction else {}
        query_evidence = self._query_evidence(result,query,len(data["results"]),**extra)
        cap = params["per_page"]
        cards = [card for row in data["results"][:cap] if (card := self._work(row,result,query_corpus="core"))]
        meta = data.get("meta") if isinstance(data.get("meta"),dict) else {}
        more = type(meta.get("count")) is int and meta["count"] > len(cards)
        if more or len(data["results"]) > cap:
            self._limit("OpenAlex initial page bounded; unvisited matches remain")
        for card in cards:
            card.discovery_evidence_ids.append(query_evidence.evidence_id)
        return self._batch(cards,start,partial=result.partial or more,cursor="page=2" if more else None,query_subject=query.query_id)

    def enrich(self,candidates):
        start = len(self.evidence)
        cards = []
        for original in candidates:
            requested_name = next((name for name in ("openalex","doi","arxiv") if self._lookup(original.identifiers.get(name))),None)
            if not requested_name:
                self._limit("OpenAlex enrich needs an explicit supported identity")
                continue
            key = self._lookup(original.identifiers[requested_name])
            result,data = self._get(API+"/"+quote(key,safe=""))
            card = self._work(data,result) if data is not None else None
            if not card:
                continue
            mismatch = any(name in card.identifiers and name in original.identifiers and
                card.identifiers[name] != (work_id(original.identifiers[name]) if name == "openalex" else normalized_identity(name,original.identifiers[name]))
                for name in ("openalex","doi","arxiv"))
            if mismatch:
                self._limit("OpenAlex explicit identity mismatch; returned work not assigned to requested paper")
                continue
            # External-ID singleton lookup itself proves the explicit association,
            # even when the source omits that ID from its serialized ids object.
            if requested_name not in card.identifiers:
                card.identifiers[requested_name] = normalized_identity(requested_name,original.identifiers[requested_name])
                if requested_name == "doi":
                    card.urls["doi"] = doi_url(card.identifiers["doi"])
            cards.append(card)
        return self._batch(cards,start)
