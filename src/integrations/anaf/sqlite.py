"""Offline ANAF adapter over the supplied credit-source SQLite fixture.

No HTTP/real ANAF calls, SQL writes or implicit database creation. Customer/CNP
bindings are trusted server configuration, never tool/request parameters. Annual
averages remain historical evidence rather than current recurring salary.
"""

import asyncio
import calendar
import hashlib
import json
import sqlite3
import threading
import time
from contextlib import closing
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path
from typing import Annotated

from pydantic import Field, ValidationError, model_validator

from src.models.eligibility import (
    ContractModel, EvidenceReference, EvidenceSource, EvidenceStatus, Identifier,
    IncomeBasis, IncomeKind, IncomeVerificationData, ProviderQuery, SyntheticFlag,
    VerificationResult, VerificationStatus,
)
from src.rules.eligibility.calendar import add_months


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE = ROOT / "data" / "local" / "credit_sources.db"
DEFAULT_BINDINGS = ROOT / "config" / "rules" / "eligibility_anaf_bindings.json"
DEFAULT_MANIFEST = ROOT / "data" / "synthetic" / "credit_sources" / "sample_data_manifest.json"
CENT = Decimal("0.01")
MAX_MONEY = Decimal("999999999999.99")


class AnafIdentityBinding(ContractModel):
    customer_id: Identifier
    cnp: Annotated[str, Field(pattern=r"^[0-9]{13}$", repr=False)]
    scenario_tag: Identifier


class AnafIdentityBindings(ContractModel):
    version: Identifier
    simulated: SyntheticFlag
    bindings: tuple[AnafIdentityBinding, ...]

    @model_validator(mode="after")
    def unique_customers(self) -> "AnafIdentityBindings":
        ids = [binding.customer_id for binding in self.bindings]
        if len(ids) != len(set(ids)):
            raise ValueError("ANAF identity bindings must have unique customer IDs.")
        return self


def load_identity_bindings(path: Path = DEFAULT_BINDINGS) -> AnafIdentityBindings:
    return AnafIdentityBindings.model_validate_json(path.read_text(encoding="utf-8"))


def _decimal_amount(value: str) -> Decimal:
    """Convert SQLite TEXT deliberately; never feed binary floats into Money."""
    if not isinstance(value, str):
        raise ValueError("The SQL boundary must serialize money as text.")
    amount = Decimal(value)
    if not amount.is_finite() or not Decimal("0") <= amount <= MAX_MONEY:
        raise ValueError("ANAF amount is outside the supported finite monetary range.")
    return amount


def _total_money(values: list[str], divisor: int = 1) -> Decimal:
    with localcontext() as context:
        context.prec = 40
        total = sum((_decimal_amount(value) for value in values), Decimal("0"))
        total = (total / Decimal(divisor)).quantize(CENT, rounding=ROUND_HALF_UP)
        if total > MAX_MONEY:
            raise ValueError("Combined ANAF income exceeds the supported monetary range.")
        return total


def _month_end(month: date) -> date:
    return date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])


class SqliteAnafProvider:
    source = EvidenceSource.ANAF

    def __init__(
        self, database_path: Path = DEFAULT_DATABASE,
        bindings: AnafIdentityBindings | None = None, *,
        manifest_path: Path = DEFAULT_MANIFEST,
    ) -> None:
        self.database_path = database_path.resolve()
        self._bindings = bindings or load_identity_bindings()
        self._bindings = AnafIdentityBindings.model_validate_json(self._bindings.model_dump_json())
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        if manifest.get("fictional_only") is not True:
            raise ValueError("Only the explicitly fictional credit-source fixture is allowed.")
        known_cnps = manifest.get("sex_by_cnp", {})
        scenarios = {item["tag"]: item["cnp"] for item in manifest.get("scenarios", [])}
        for binding in self._bindings.bindings:
            if binding.cnp not in known_cnps:
                raise ValueError("An ANAF binding must reference a known fictional fixture identity.")
            if not (
                scenarios.get(binding.scenario_tag) == binding.cnp
                or binding.scenario_tag.startswith("RANDOM_")
            ):
                raise ValueError("Binding scenario and fictional identity disagree.")
        self._identities = {b.customer_id: b for b in self._bindings.bindings}
        self._version = hashlib.sha256(
            manifest_bytes + self._bindings.model_dump_json().encode("utf-8")
        ).hexdigest()[:16]
        self.calls = 0
        self.queries: list[ProviderQuery] = []

    def _failure(self, query: ProviderQuery, status: VerificationStatus) -> VerificationResult[IncomeVerificationData]:
        return VerificationResult[IncomeVerificationData](
            provider=self.source, customer_id=query.customer_id, status=status, simulated=True,
        )

    async def verify(self, query: ProviderQuery) -> VerificationResult[IncomeVerificationData]:
        query = ProviderQuery.model_validate(query)
        self.calls += 1
        self.queries.append(query)
        binding = self._identities.get(query.customer_id)
        if binding is None:
            return self._failure(query, VerificationStatus.NOT_FOUND)
        cancelled = threading.Event()
        try:
            return await asyncio.to_thread(self._read, query, binding, cancelled)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    def _read(
        self, query: ProviderQuery, binding: AnafIdentityBinding, cancelled: threading.Event,
    ) -> VerificationResult[IncomeVerificationData]:
        try:
            # mode=ro refuses missing paths; no creation, fallback or reset.
            uri = self.database_path.as_uri() + "?mode=ro&cache=private"
            with closing(sqlite3.connect(uri, uri=True, timeout=1)) as database:
                database.row_factory = sqlite3.Row
                database.execute("PRAGMA query_only = ON")
                deadline = time.monotonic() + 1
                database.set_progress_handler(
                    lambda: int(cancelled.is_set() or time.monotonic() > deadline), 1000,
                )
                database.execute("BEGIN")  # One consistent, read-only reporting snapshot.
                rows = database.execute("SELECT as_of_date FROM report_params WHERE id = 1").fetchall()
                if len(rows) != 1:
                    raise ValueError("ANAF source requires one reporting date.")
                reference = date.fromisoformat(rows[0]["as_of_date"])
                person = database.execute(
                    "SELECT persona_tag FROM persons WHERE cnp = ?", (binding.cnp,),
                ).fetchone()
                if person is None:
                    return self._failure(query, VerificationStatus.NOT_FOUND)
                if person["persona_tag"] != binding.scenario_tag:
                    raise ValueError("The source identity does not match its trusted binding.")
                annual = database.execute(
                    "SELECT fiscal_year, income_type, CAST(net_amount_ron AS TEXT) AS net "
                    "FROM v_anaf_income WHERE cnp = ? ORDER BY fiscal_year DESC, id",
                    (binding.cnp,),
                ).fetchall()
                # Only completed salary months. Intentional future/current rows stay hidden.
                month_row = database.execute(
                    "SELECT MAX(month) AS month FROM monthly_salary_declarations "
                    "WHERE cnp = ? AND month < ?",
                    (binding.cnp, reference.replace(day=1).isoformat()),
                ).fetchone()
                if month_row["month"] is not None:
                    data = self._monthly_data(database, binding, reference, month_row["month"], annual)
                elif annual:
                    data = self._annual_data(query.customer_id, reference, annual)
                else:
                    return self._failure(query, VerificationStatus.NOT_FOUND)
                encoded = json.dumps(data.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
                digest = hashlib.sha256((self._version + encoded).encode("utf-8")).hexdigest()[:24]
                return VerificationResult[IncomeVerificationData](
                    provider=self.source, customer_id=query.customer_id,
                    status=VerificationStatus.SUCCESS, data=data,
                    evidence=EvidenceReference(
                        evidence_id=f"anaf-sqlite-{digest}", source=self.source,
                        # Source snapshot time, not artificial 'now' refreshed per inquiry.
                        recorded_at=datetime.combine(reference, datetime.min.time(), timezone.utc),
                        status=EvidenceStatus.VERIFIED, source_version=f"anaf-sqlite-v1-{self._version}",
                        simulated=True,
                    ), simulated=True,
                )
        except sqlite3.OperationalError:
            return self._failure(query, VerificationStatus.UNAVAILABLE)
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError, ValidationError, InvalidOperation, OverflowError):
            return self._failure(query, VerificationStatus.INVALID_RESPONSE)

    def _monthly_data(
        self, database: sqlite3.Connection, binding: AnafIdentityBinding,
        reference: date, month_text: str, annual: list[sqlite3.Row],
    ) -> IncomeVerificationData:
        month = date.fromisoformat(month_text)
        if month.day != 1:
            raise ValueError("Salary periods must be first-of-month dates.")
        periods = tuple(add_months(month, offset) for offset in (-2, -1, 0))
        salary = database.execute(
            "SELECT month, employer, CAST(net_ron AS TEXT) AS net "
            "FROM monthly_salary_declarations WHERE cnp = ? AND month BETWEEN ? AND ? "
            "ORDER BY month, employer",
            (binding.cnp, periods[0].isoformat(), month.isoformat()),
        ).fetchall()
        jobs = database.execute(
            "SELECT employer, start_date, end_date FROM employments WHERE cnp = ?",
            (binding.cnp,),
        ).fetchall()
        employers_by_month = {
            period: {row["employer"] for row in salary if row["month"] == period.isoformat()}
            for period in periods
        }
        latest_employers = employers_by_month[month]
        current_employers = {
            job["employer"] for job in jobs
            if date.fromisoformat(job["start_date"]) <= reference
            and (job["end_date"] is None or date.fromisoformat(job["end_date"]) >= reference)
        }
        recurring = bool(latest_employers) and all(
            employers_by_month[period] == latest_employers for period in periods
        ) and latest_employers == current_employers
        for row in salary:
            salary_month = date.fromisoformat(row["month"])
            covered = any(
                job["employer"] == row["employer"]
                and date.fromisoformat(job["start_date"]) <= _month_end(salary_month)
                and (job["end_date"] is None or date.fromisoformat(job["end_date"]) >= salary_month)
                for job in jobs
            )
            recurring = recurring and covered
        latest_values = [row["net"] for row in salary if row["month"] == month.isoformat()]
        if not latest_values:
            raise ValueError("The latest salary month has no declarations.")
        reported_types = {"SALARY"}
        if annual:
            latest_year = annual[0]["fiscal_year"]
            reported_types.update(row["income_type"] for row in annual if row["fiscal_year"] == latest_year)
        return IncomeVerificationData(
            customer_id=binding.customer_id, income_kind=IncomeKind.SALARY,
            net_monthly_income_ron=_total_money(latest_values), period_end=_month_end(month),
            recurring=recurring, income_basis=IncomeBasis.MONTHLY_SALARY,
            reference_date=reference, reported_income_types=tuple(sorted(reported_types)),
            observed_salary_months=tuple(period for period in periods if employers_by_month[period]),
        )

    @staticmethod
    def _annual_data(
        customer_id: str, reference: date, annual: list[sqlite3.Row],
    ) -> IncomeVerificationData:
        year = annual[0]["fiscal_year"]
        rows = [row for row in annual if row["fiscal_year"] == year]
        kinds = tuple(sorted({row["income_type"] for row in rows}))
        mapping = {
            "SALARY": IncomeKind.SALARY, "PENSION": IncomeKind.PENSION,
            "INDEPENDENT_ACTIVITY": IncomeKind.SELF_EMPLOYED, "RENTAL": IncomeKind.RENTAL,
        }
        kind = mapping.get(kinds[0], IncomeKind.OTHER) if len(kinds) == 1 else IncomeKind.OTHER
        return IncomeVerificationData(
            customer_id=customer_id, income_kind=kind,
            net_monthly_income_ron=_total_money([row["net"] for row in rows], divisor=12),
            period_end=date(year, 12, 31), recurring=False,
            income_basis=IncomeBasis.ANNUAL_AVERAGE, reference_date=reference,
            fiscal_year=year, reported_income_types=kinds,
        )