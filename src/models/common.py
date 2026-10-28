"""Shared wire conventions: camelCase, decimal strings and UTC timestamps."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, Generic, Literal, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, WithJsonSchema
from pydantic.alias_generators import to_camel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


def money_string(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")


Money = Annotated[
    Decimal,
    Field(max_digits=18, decimal_places=2),
    PlainSerializer(money_string, return_type=str, when_used="json"),
    WithJsonSchema(
        {"type": "string", "pattern": r"^-?[0-9]+\.[0-9]{2}$"},
        mode="serialization",
    ),
]


class WireModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        allow_inf_nan=False,
    )


T = TypeVar("T")


class ApiResponse(WireModel, Generic[T]):
    data: T


class ValidationIssue(WireModel):
    field: str
    code: str


class ErrorDetail(WireModel):
    code: str
    message: str
    correlation_id: str
    issues: list[ValidationIssue] | None = None


class ErrorResponse(WireModel):
    error: ErrorDetail


class Health(WireModel):
    status: Literal["ok", "degraded"]
    mode: Literal["synthetic-demo"] = "synthetic-demo"
    persistence: Literal["local-sqlite"] = "local-sqlite"
    dependencies: dict[str, str]


class LogoutResult(WireModel):
    signed_out: bool = True


class ResetResult(WireModel):
    cleared: bool = True