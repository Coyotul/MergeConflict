"""Offline verification base: no sockets, credentials or real banking inquiries."""

import asyncio
from copy import deepcopy
from typing import Any

from src.models.eligibility import EvidenceSource, ProviderQuery, VerificationStatus


class SyntheticVerificationProvider:
    source: EvidenceSource

    def __init__(
        self, records: dict[str, dict[str, Any]], *, delay_seconds: float = 0,
        transient_failures: int = 0,
    ) -> None:
        if delay_seconds < 0 or transient_failures < 0:
            raise ValueError("Synthetic delays and failure counts cannot be negative.")
        self._records = deepcopy(records)
        self.delay_seconds = delay_seconds
        self.transient_failures = transient_failures
        self.calls = 0
        self.queries: list[ProviderQuery] = []

    async def verify(self, query: ProviderQuery) -> dict[str, Any]:
        query = ProviderQuery.model_validate(query)
        self.calls += 1
        self.queries.append(query)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.calls <= self.transient_failures:
            raise ConnectionError("Synthetic temporary unavailability.")
        record = self._records.get(query.customer_id)
        if record is None:
            return {
                "provider": self.source.value,
                "customer_id": query.customer_id,
                "status": VerificationStatus.NOT_FOUND.value,
                "simulated": True,
            }
        # The service independently validates this untrusted provider boundary.
        return deepcopy(record)