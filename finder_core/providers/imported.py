"""Strict host-observation boundary. Imported text is data, never executable."""
from urllib.parse import urlsplit

from ..contracts import ObservationBatch
from ..evidence import metric_name, validate_batch_evidence
from ..validation import ContractError


def validate_observations(payload: dict) -> ObservationBatch:
    """Parse a self-contained batch without upgrading source categories/statuses."""
    batch = ObservationBatch.from_dict(payload)
    validate_batch_evidence(batch)
    evidence = {item.evidence_id:item for item in batch.evidence}
    for card in batch.candidates:
        for name,metric in card.metrics.items():
            if metric.status != "verified":
                continue
            refs = [evidence[eid] for eid in metric.evidence_ids]
            logical = metric_name(name,metric)
            if logical == "official_implementation" and metric.value:
                if refs and all(urlsplit(item.source_url).hostname == "huggingface.co" for item in refs):
                    raise ContractError("ObservationBatch.candidates.metrics.official_implementation", "HF paper-page association does not establish an official implementation; import primary author/repository evidence")
            if logical == "publication_track":
                for item in refs:
                    if urlsplit(item.source_url).hostname == "aclanthology.org":
                        actual = item.source_object.get("publication_track", item.scope.get("publication_track"))
                        if actual != metric.value:
                            raise ContractError("ObservationBatch.candidates.metrics.publication_track", "ACL track requires an explicitly read proceedings/track observation")
    return batch
