"""Verified principal and correlation context, supplied by the API dependency."""

from dataclasses import dataclass

from src.models.banking import Actor


@dataclass(frozen=True)
class CallContext:
    actor: Actor
    correlation_id: str