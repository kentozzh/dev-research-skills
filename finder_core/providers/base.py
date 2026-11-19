"""Provider interface; batches may retain candidates alongside source limits."""
from typing import Protocol, Sequence

from ..contracts import Candidate, ProviderBatch, QuerySpec


class Provider(Protocol):
    def search(self, query: QuerySpec) -> ProviderBatch: ...

    def enrich(self, candidates: Sequence[Candidate]) -> ProviderBatch: ...
