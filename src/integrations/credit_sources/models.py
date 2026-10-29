"""Report models returned by the simulated credit-source adapters."""
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel


class CustomerBinding(BaseModel):
    """Trusted server-side link from a customer ID to a dataset CNP."""
    customer_id: str
    cnp: str
    persona_tag: str


def load_bindings(path: Path) -> dict[str, CustomerBinding]:
    """Load `bindings:` as a list of records or a mapping keyed by customer ID."""
    raw = (yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}).get("bindings") or []
    if isinstance(raw, dict):
        raw = [{"customer_id": key, **value} for key, value in raw.items()]
    bindings = [CustomerBinding(**{**item, "cnp": str(item["cnp"])}) for item in raw]
    return {b.customer_id: b for b in bindings}


class PersonRecord(BaseModel):
    customer_id: str
    full_name: str
    birth_date: date
    as_of: date
    simulated: bool = True


class AnafReport(BaseModel):
    status: Literal["found", "not_found"]
    net_monthly_income: Decimal | None = None
    income_basis: Literal["monthly_salary", "annual_average"] | None = None
    income_kinds: list[str] = []
    self_employed: bool = False
    employment_start: date | None = None
    as_of: date
    simulated: bool = True


class BureauReport(BaseModel):
    status: Literal["found", "not_found"]
    active_products: int = 0
    monthly_instalments: Decimal = Decimal("0.00")
    current_max_dpd: int = 0
    max_dpd_12m: int = 0
    written_off_or_assigned: bool = False
    open_insolvency: bool = False
    events_12m: list[str] = []
    fraud_records: int = 0
    score: int | None = None
    score_status: Literal["SCORED", "NO_SCORE", "NONE"] = "NONE"
    as_of: date
    simulated: bool = True
