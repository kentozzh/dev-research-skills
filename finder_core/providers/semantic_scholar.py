"""Documented Semantic Scholar Graph GET search/detail/citation neighborhood."""
from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

from ..contracts import Candidate
from ._paper import PaperProvider, arxiv, chain_query, checked_link, checked_link_metadata, date_range, doi, doi_url, normalized_identity

API = "https://api.semanticscholar.org/graph/v1/paper"
FIELDS = "paperId,title,year,abstract,citationCount,influentialCitationCount,url,externalIds,authors,venue,publicationDate,openAccessPdf"


class SemanticScholarProvider(PaperProvider):
    name = "semantic_scholar"
    method = "semantic-scholar-graph-v1"

    def _paper(self,data,result):
        if not isinstance(data,dict) or not isinstance(data.get("paperId"),str) or not re.fullmatch(r"[A-Za-z0-9-]+",data["paperId"]):
            self._limit("Semantic Scholar paper missing explicit paperId")
            return None
        sid = data["paperId"]
        subject = "semantic_scholar:" + sid
        ids = {"semantic_scholar":sid}
        external = data.get("externalIds") if isinstance(data.get("externalIds"),dict) else {}
        if value := doi(external.get("DOI")):
            ids["doi"] = value
        if value := arxiv(external.get("ArXiv")):
            ids["arxiv"] = re.sub(r"v\d+$","",value)
        selected = {key:data[key] for key in FIELDS.split(",") if key in data}
        if "url" in selected:
            selected["url"] = checked_link(selected["url"])
        if "openAccessPdf" in selected:
            selected["openAccessPdf"] = checked_link_metadata(selected["openAccessPdf"])
        ev = self._evidence(result,subject,selected)
        urls = {"paper": "https://www.semanticscholar.org/paper/" + sid}
        if "doi" in ids:
            urls["doi"] = doi_url(ids["doi"])
        if catalog := selected.get("url"):
            page = urlsplit(catalog)
            if page.hostname in ("semanticscholar.org", "www.semanticscholar.org") and page.path.startswith("/paper/"):
                urls["discovery"] = catalog
        access = selected.get("openAccessPdf")
        if isinstance(access, dict) and access.get("status") != "CLOSED":
            if pdf := access.get("url"):
                urls["pdf"] = pdf
        card = Candidate(subject,"paper",ids,urls=urls,discovery_evidence_ids=[ev.evidence_id])
        for key,field,unit in (("citations","citationCount","count"),("influential_citations","influentialCitationCount","count"),
            ("publication_year","year","year"),("title","title","text"),("abstract","abstract","text"),("venue","venue","text")):
            card.metrics[key] = self._metric(data.get(field),unit,result,subject,ev)
        card.metrics["publication_track"] = self._metric(None,"text",result,subject,ev)
        return card

    def _lookup(self,identifiers):
        if value := identifiers.get("semantic_scholar"):
            return value if re.fullmatch(r"[A-Za-z0-9-]+",value) else None
        if value := doi(identifiers.get("doi")):
            return "DOI:"+value
        if value := arxiv(identifiers.get("arxiv")):
            return "ARXIV:"+re.sub(r"v\d+$","",value)
        return None

    def search(self,query):
        start = len(self.evidence)
        direction,seed = chain_query(query.query)
        params = {"fields":FIELDS,"limit":self.client.policy.capacity.paper_initial // 2,"offset":0}
        if direction:
            raw = seed
            if seed.startswith("semantic_scholar:"):
                raw = seed.split(":",1)[1]
            if seed.upper().startswith("DOI:"):
                raw = self._lookup({"doi":seed[4:]})
            elif seed.upper().startswith("ARXIV:"):
                raw = self._lookup({"arxiv":seed[6:]})
            elif doi(seed):
                raw = self._lookup({"doi":seed})
            elif arxiv(seed):
                raw = self._lookup({"arxiv":seed})
            if not raw or not (raw.startswith(("DOI:","ARXIV:")) or re.fullmatch(r"[0-9a-fA-F]{40}",raw)):
                self._limit("Semantic Scholar chain requires explicit DOI, arXiv or Semantic Scholar identity")
                return self._batch([],start,partial=True)
            url = API+"/"+quote(raw,safe="")+"/"+direction
        else:
            params["query"] = query.query
            url = API+"/search"
        if query.route == "recent":
            params["publicationDateOrYear"] = ":".join(date_range(self.client))
        result,data = self._get(url,params,query=True)
        if not isinstance(data,dict) or not isinstance(data.get("data"),list):
            self._limit("Semantic Scholar search envelope invalid or unavailable")
            return self._batch([],start,partial=True)
        extra = {"chain_direction":direction,"chain_seed":seed} if direction else {}
        query_ev = self._query_evidence(result,query,len(data["data"]),**extra)
        cards = []
        for row in data["data"][:params["limit"]]:
            if direction:
                row = row.get("citingPaper" if direction == "citations" else "citedPaper") if isinstance(row,dict) else None
            card = self._paper(row,result)
            if card:
                card.discovery_evidence_ids.append(query_ev.evidence_id)
                cards.append(card)
        more = data.get("next") is not None or (type(data.get("total")) is int and data["total"] > len(cards))
        if more or len(data["data"]) > params["limit"]:
            self._limit("Semantic Scholar initial page bounded; unvisited matches remain")
        return self._batch(cards,start,partial=result.partial or more,cursor="offset="+str(params["limit"]) if more else None,query_subject=query.query_id)

    def enrich(self,candidates):
        start = len(self.evidence)
        cards = []
        for original in candidates:
            key = self._lookup(original.identifiers)
            if not key:
                self._limit("Semantic Scholar enrich needs an explicit supported identity")
                continue
            result,data = self._get(API+"/"+quote(key,safe=""),{"fields":FIELDS})
            card = self._paper(data,result) if data is not None else None
            if not card:
                continue
            if any(name in original.identifiers and name in card.identifiers and
                normalized_identity(name,original.identifiers[name]) != card.identifiers[name] for name in ("doi","arxiv","semantic_scholar")):
                self._limit("Semantic Scholar explicit identity mismatch; returned work not assigned")
                continue
            requested_name = "doi" if key.startswith("DOI:") else "arxiv" if key.startswith("ARXIV:") else "semantic_scholar"
            if requested_name not in card.identifiers:
                card.identifiers[requested_name] = normalized_identity(requested_name,original.identifiers[requested_name])
                if requested_name == "doi":
                    card.urls["doi"] = doi_url(card.identifiers["doi"])
            cards.append(card)
        return self._batch(cards,start)
