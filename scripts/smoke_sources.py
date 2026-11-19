"""Run explicitly requested, read-only source probes and save honest receipts."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from finder_core.cache import FileCache
from finder_core.scoring import default_policy
from finder_core.transport import HttpClient, _request

# One object per source; none of these probes searches or executes candidate code.
PROBES = (
    ("github", "https://api.github.com/repos/python/cpython", {}, "GITHUB_TOKEN"),
    ("arxiv", "https://export.arxiv.org/api/query", {"id_list": "1706.03762", "max_results": 1}, None),
    ("openalex", "https://api.openalex.org/works/W2741809807", {}, "OPENALEX_API_KEY"),
    ("semantic_scholar", "https://api.semanticscholar.org/graph/v1/paper/arXiv:1706.03762",
     {"fields": "paperId,title"}, "SEMANTIC_SCHOLAR_API_KEY"),
)


def _valid_payload(provider, body):
    try:
        if provider == "arxiv":
            feed = ElementTree.fromstring(body)
            return feed.tag == "{http://www.w3.org/2005/Atom}feed" and bool(
                feed.findall("{http://www.w3.org/2005/Atom}entry/{http://www.w3.org/2005/Atom}id"))
        payload = json.loads(body)
        if not isinstance(payload, dict):
            return False
        field = {"github": "full_name", "openalex": "id", "semantic_scholar": "paperId"}[provider]
        return isinstance(payload.get(field), str) and bool(payload[field])
    except (ValueError, ElementTree.ParseError):
        return False


def probe_sources(*, environ=None, request=None):
    """Probe actual sources, or explicitly label a dependency-injected fixture."""
    env = dict(os.environ if environ is None else environ)
    records = []
    with tempfile.TemporaryDirectory(prefix="finder-source-smoke-") as temporary:
        for provider, endpoint, params, credential_name in PROBES:
            modes = ("configured", "anonymous") if credential_name and env.get(credential_name) else ("anonymous",)
            for mode in modes:
                credentials = env if mode == "configured" else {}
                policy = default_policy()
                policy.transport.max_retries = 0
                policy.transport.timeout_seconds = min(10, policy.transport.timeout_seconds)
                http = HttpClient(FileCache(Path(temporary) / provider / mode), policy=policy,
                                  skill="paper-finding", environ=credentials, request=request or _request)
                started = datetime.now(timezone.utc)
                clock = time.monotonic()
                result = http.get(provider, endpoint, params, 0)
                valid = result.status == 200 and _valid_payload(provider, result.body)
                outcome = ("success" if result.state == "verified" and not result.from_cache else "degraded") if valid else "failed"
                records.append({"provider": provider, "endpoint": endpoint, "mode": mode,
                    "credential_present": bool(credential_name and credentials.get(credential_name)),
                    "started_at": started.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(),
                    "elapsed_seconds": round(time.monotonic() - clock, 4), "outcome": outcome,
                    "http_status": result.status, "retrieval_state": result.state, "from_cache": result.from_cache,
                    "valid_payload": valid, "request_counts": dict(http.request_counts),
                    "limits": [limit.to_dict() for limit in result.limits]})
    return {"verification": "injected_fixture" if request is not None else "live",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "all_sources_successful": all(row["outcome"] == "success" for row in records),
            "host_acl_hf": "not_checked_by_this_script; requires host page reading and import verification",
            "probes": records}


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Authorize real read-only source requests")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("--live is required; no requests were issued")
    receipt = probe_sources()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "all_sources_successful": receipt["all_sources_successful"]}, ensure_ascii=False))
    return 0 if receipt["all_sources_successful"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
