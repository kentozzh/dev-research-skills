"""Documented arXiv Atom metadata and versions; arXiv supplies no citations."""
from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from ..contracts import Candidate, IdentityRelation
from ._paper import PaperProvider, arxiv, chain_query, date_range, doi

API = "https://export.arxiv.org/api/query"
NS = {"a":"http://www.w3.org/2005/Atom", "x":"http://arxiv.org/schemas/atom", "o":"http://a9.com/-/spec/opensearch/1.1/"}


class ArxivProvider(PaperProvider):
    name = "arxiv"
    method = "arxiv-atom-v1"

    def _parse(self, result, raw):
        try:
            feed = ET.fromstring(raw)
        except (ET.ParseError, TypeError):
            self._limit("arXiv Atom unavailable or malformed")
            return None, None
        if feed.tag != "{" + NS["a"] + "}feed":
            self._limit("arXiv Atom search envelope invalid")
            return None, None
        cards = []
        for entry in feed.findall("a:entry", NS):
            text = lambda field: entry.findtext(field, default="", namespaces=NS).strip() or None
            if (text("a:id") or "").startswith(("https://arxiv.org/api/errors", "http://arxiv.org/api/errors")):
                self._limit("arXiv error Atom entry; query did not produce a valid search response")
                return None, None
            version = arxiv(text("a:id"))
            if not version:
                self._limit("arXiv result missing stable identity or error entry")
                continue
            base = re.sub(r"v\d+$", "", version)
            subject = "arxiv:" + version
            data = {"arxiv":base,"version":version,"title":text("a:title"),"abstract":text("a:summary"),
                "published":text("a:published"),"updated":text("a:updated"),"doi":text("x:doi"),
                "journal_ref":text("x:journal_ref"),"authors":[a.findtext("a:name",namespaces=NS) for a in entry.findall("a:author",NS)]}
            ev = self._evidence(result, subject, data)
            ids = {"arxiv":base}
            if value := doi(data["doi"]):
                ids["doi"] = value
            card = Candidate(subject,"paper",ids,versions=[version],discovery_evidence_ids=[ev.evidence_id])
            card.urls["paper"] = "https://arxiv.org/abs/" + version
            for link in entry.findall("a:link",NS):
                url = link.get("href", "")
                if not url.startswith(("https://","http://")):
                    continue
                if link.get("type") == "application/pdf" or link.get("title") == "pdf":
                    card.urls["pdf"] = url
                elif link.get("rel") == "alternate" and link.get("type") == "text/html":
                    card.urls["paper"] = url
            for key,value in (("title",data["title"]),("abstract",data["abstract"]),("journal_reference",data["journal_ref"]),
                              ("venue",None),("publication_track",None)):
                card.metrics[key] = self._metric(value,"text",result,subject,ev)
            # Journal reference is the raw author-provided bibliographic string;
            # it does not authenticate a venue, acceptance, or publication track.
            cards.append(card)
        by_base = {}
        for card in cards:
            by_base.setdefault(card.identifiers["arxiv"],[]).append(card)
        for versions in by_base.values():
            versions.sort(key=lambda c:int(re.search(r"v(\d+)$",c.versions[0]).group(1)) if re.search(r"v(\d+)$",c.versions[0]) else 0)
            for old,new in zip(versions,versions[1:]):
                new.relations.append(IdentityRelation(new.candidate_id,old.candidate_id,"version_of",new.discovery_evidence_ids))
        total = feed.findtext("o:totalResults",namespaces=NS)
        return cards, int(total) if total and total.isdigit() else len(cards)

    def search(self, query):
        start = len(self.evidence)
        if chain_query(query.query)[0]:
            self._limit("arXiv citation chain unsupported; use OpenAlex or Semantic Scholar")
            return self._batch([],start,partial=True)
        text = query.query
        if query.route == "recent":
            lower,upper = date_range(self.client)
            text = "(" + text + ") AND submittedDate:[" + lower.replace("-","") + "0000 TO " + upper.replace("-","") + "2359]"
        cap = self.client.policy.capacity.paper_initial // 2
        result,raw = self._get(API,{"search_query":text,"start":0,"max_results":cap},query=True,xml=True)
        cards,total = self._parse(result,raw)
        if cards is None:
            return self._batch([],start,partial=True)
        query_evidence = self._query_evidence(result,query,len(cards))
        for card in cards:
            card.discovery_evidence_ids.append(query_evidence.evidence_id)
        more = total > len(cards)
        if more:
            self._limit("arXiv initial page bounded; unvisited matches remain")
        return self._batch(cards,start,partial=result.partial or more,cursor="start="+str(cap) if more else None,query_subject=query.query_id)

    def enrich(self, candidates):
        start = len(self.evidence)
        ids = [arxiv(c.identifiers.get("arxiv")) for c in candidates]
        ids = [value for value in ids if value]
        if not ids:
            self._limit("arXiv enrich needs an explicit arXiv identity")
            return self._batch([],start,partial=True)
        result,raw = self._get(API,{"id_list":",".join(ids)},xml=True,static=True)
        cards,_ = self._parse(result,raw)
        allowed = {re.sub(r"v\d+$","",value) for value in ids}
        matched = [c for c in cards or [] if c.identifiers["arxiv"] in allowed]
        if {c.identifiers["arxiv"] for c in matched} != allowed:
            self._limit("arXiv explicit identity lookup incomplete or mismatched")
        return self._batch(matched,start,partial=result.partial or cards is None)
