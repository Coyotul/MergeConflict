"""Seeded fictional fixtures plus guaranteed credit-report edge cases.

No external libraries, network data or real identities. The schema stays empty
and reusable; sample inserts are exported separately. Existing populated targets
are refused, and an existing empty target is backed up before loading.
"""

import argparse
import calendar
from contextlib import closing
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import random
import sqlite3

if __package__:
    from .credit_sources_validation import fictional_data_issues
else:
    from credit_sources_validation import fictional_data_issues


ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = ROOT / "data" / "synthetic" / "credit_sources"
SCHEMA_PATH = SAMPLE_DIR / "credit_sources.sql"
AS_OF_DATE = "2026-10-28"
DEFAULT_SEED = 20261028
DEFAULT_RANDOM_PEOPLE = 250
TABLES = (
    "persons", "employers", "lenders", "employments", "income_activity_forms",
    "income_records", "monthly_salary_declarations", "credit_products",
    "product_participants", "payment_history", "credit_events", "bureau_inquiries",
    "fico_scores", "fico_reason_codes", "insolvency_records", "card_fraud_records",
)


def money(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def months_between(first, last):
    year, month = int(first[:4]), int(first[5:7])
    while f"{year:04d}-{month:02d}-01" <= last[:7] + "-01":
        yield f"{year:04d}-{month:02d}-01"
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def new_database():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return db


class FixtureBuilder:
    def __init__(self, db, seed):
        self.db = db
        self.rng = random.Random(seed)
        self.people = {}
        self.sex_by_cnp = {}
        self.scenarios = []
        self.products = {}
        self.amortizers = set()
        self.db.execute("UPDATE report_params SET as_of_date=?", (AS_OF_DATE,))
        for ident, kind in enumerate(("BANK", "IFN", "LEASING", "INSURER", "DEBT_COLLECTOR"), 1):
            self.insert("lenders", id=ident, name=f"FICTIV {kind} {ident}", lender_type=kind)
        for ident in range(1, 7):
            self.insert("employers", id=ident, name=f"FICTIV Employer's Studio {ident}",
                        fiscal_code=f"TEST-EMP-{ident:03d}", address="Adresa fictiva, Romania")

    def insert(self, table, **values):
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        return self.db.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(values.values())).lastrowid

    def person(self, tag, description, birth=None, curated=True):
        number = len(self.people) + 1
        if tag in self.people or number > 99999:
            raise ValueError("Duplicate scenario tag or too many fictional identities")
        sex = self.rng.choice(("M", "F"))
        birth = birth or date(self.rng.randint(1965, 1990), self.rng.randint(1, 12), self.rng.randint(1, 28)).isoformat()
        prefix = (1 if birth[:4] < "2000" else 5) + (sex == "F")
        first_twelve = str(prefix) + birth[2:4] + birth[5:7] + birth[8:10] + f"{number:05d}"
        checksum = sum(int(a) * int(b) for a, b in zip(first_twelve, "279146358279")) % 11
        checksum = 1 if checksum == 10 else checksum
        # Deliberately wrong checksum: date/sex-consistent, NOT an official CNP.
        cnp = first_twelve + str((checksum + 1) % 10)
        first_name = self.rng.choice(("Andrei", "Mihai", "Radu", "Victor") if sex == "M" else ("Ana", "Elena", "Ioana", "Maria"))
        self.insert("persons", cnp=cnp, first_name=first_name, last_name=f"FICTIV_{number:05d}",
                    birth_date=birth, address=f"Strada Exemplului {number}, Localitate Fictiva", phone=None, persona_tag=tag)
        self.people[tag] = cnp
        self.sex_by_cnp[cnp] = sex
        if curated:
            self.scenarios.append({"tag": tag, "cnp": cnp, "description": description})
        return cnp

    def employment(self, cnp, employer=1, start="2020-01-01", end=None, contract="INDEFINITE"):
        return self.insert("employments", cnp=cnp, employer=employer, start_date=start,
                           end_date=end, contract_type=contract)

    def salary(self, cnp, year, net, employer=1):
        jobs = self.db.execute("SELECT start_date,end_date FROM employments WHERE cnp=? AND employer=?", (cnp, employer)).fetchall()
        if not jobs:
            self.employment(cnp, employer, start=f"{min(year, 2020)}-01-01")
            jobs = self.db.execute("SELECT start_date,end_date FROM employments WHERE cnp=? AND employer=?", (cnp, employer)).fetchall()
        periods = []
        for month in months_between(f"{year}-01-01", f"{year}-12-01"):
            end = f"{year}-{month[5:7]}-{calendar.monthrange(year, int(month[5:7]))[1]}"
            if any(start <= end and (closed is None or closed >= month) for start, closed in jobs):
                periods.append(month)
        if not periods:
            raise ValueError("Salary year does not overlap employment")
        name, fiscal_code = self.db.execute("SELECT name,fiscal_code FROM employers WHERE id=?", (employer,)).fetchone()
        cents = int(Decimal(str(net)) * 100)
        base, extra = divmod(cents, len(periods))
        gross_total = 0.0
        for index, month in enumerate(periods):
            monthly_net = (base + (index < extra)) / 100.0
            gross = money(monthly_net / 0.65)
            gross_total += gross
            self.insert("monthly_salary_declarations", cnp=cnp, employer=employer, month=month,
                        gross_ron=gross, net_ron=monthly_net, contributions_ron=money(gross - monthly_net))
        self.insert("income_records", cnp=cnp, fiscal_year=year, income_type="SALARY", source_name=name,
                    source_fiscal_code=fiscal_code, gross_amount_ron=money(gross_total), net_amount_ron=money(net))

    def income(self, cnp, kind="RENTAL", net=60000, year=2025, source=None):
        self.insert("income_records", cnp=cnp, fiscal_year=year, income_type=kind,
                    source_name=source or f"FICTIV {kind} source", source_fiscal_code=None,
                    gross_amount_ron=money(net * 1.2), net_amount_ron=money(net))

    def product(self, cnp, label, amount=25000, kind="CONSUMER_LOAN", currency="RON", original=None,
                opened="2024-01-15", closed=None, status="ACTIVE", lender=1, rate_type="FIXED", rate=8.0):
        term = None if kind in ("CREDIT_CARD", "OVERDRAFT") else (360 if kind == "MORTGAGE" else 120)
        exchange = {"RON": 1.0, "EUR": 5.0, "USD": 4.6, "CHF": 5.2}[currency]
        ident = self.insert("credit_products", lender=lender, product_type=kind, currency=currency,
                            opened_on=opened, term_months=term,
                            amount_granted=money(original if original is not None else amount / exchange),
                            amount_granted_ron=money(amount), interest_rate=rate, rate_type=rate_type,
                            status="CLOSED" if closed else status, closed_on=closed)
        self.insert("product_participants", product=ident, cnp=cnp, role="DEBTOR")
        self.products[label] = ident
        return ident

    def history(self, product, month, owed=20000, instalment=500, dpd=0, paid=None):
        instalment = money(instalment)
        overdue_count = (dpd + 29) // 30
        overdue = money(min(owed, max(0.01, instalment * overdue_count))) if dpd else 0.0
        paid = money(instalment * (0.25 if dpd else 1.0)) if paid is None else money(paid)
        self.insert("payment_history", product=product, month=month, amount_owed=money(owed),
                    instalment_due=instalment, amount_paid=paid, overdue_amount=overdue,
                    overdue_instalments=overdue_count, days_past_due=dpd)

    def timeline(self, product, end="2026-10-01", delinquent=False):
        p = self.db.execute("SELECT * FROM credit_products WHERE id=?", (product,)).fetchone()
        end = min(end, p["closed_on"][:7] + "-01") if p["closed_on"] else end
        periods = list(months_between(p["opened_on"], end))
        owed = p["amount_granted_ron"]
        revolving = p["product_type"] in ("CREDIT_CARD", "OVERDRAFT")
        payment = money(owed / (p["term_months"] or 36) + owed * (p["interest_rate"] or 0) / 1200)
        for index, month in enumerate(periods):
            dpd = min(181, (index - len(periods) + 7) * 30 + 1) if delinquent and index >= len(periods) - 6 else 0
            paid = money(payment * (0.25 if dpd else 1.0))
            if revolving:
                owed = money(p["amount_granted_ron"] * self.rng.uniform(0.15, 0.9))
            else:
                interest = money(owed * (p["interest_rate"] or 0) / 1200)
                paid = min(paid, money(owed + interest))
                owed = max(0.0, money(owed + interest - paid))
            closing = p["closed_on"] and month == p["closed_on"][:7] + "-01"
            if closing:
                paid, owed, dpd = money(paid + owed), 0.0, 0
            self.history(product, month, owed, 0 if closing else payment, dpd, paid)
        if not delinquent and not revolving and p["currency"] == "RON" and p["rate_type"] == "FIXED" and p["product_type"] in ("CONSUMER_LOAN", "MORTGAGE", "LEASING"):
            self.amortizers.add(product)

    def score(self, cnp, value=700, day="2026-10-01", reasons=True):
        ident = self.insert("fico_scores", cnp=cnp, calculated_on=day, score=value, status="SCORED" if value is not None else "NO_SCORE")
        if reasons and value is not None:
            for rank in (5, 1, 3, 2, 4):
                self.insert("fico_reason_codes", score=ident, rank=rank, code=f"TEST-{rank}",
                            description=f"Fictional explanation rank {rank}; not an official FICO reason")
        return ident

    def event(self, product, kind="RESTRUCTURING", day="2026-09-15"):
        return self.insert("credit_events", product=product, event_date=day, event_type=kind,
                           details=f"Fictional {kind.lower()} scenario; no actual contract")

    def curated_cases(self):
        self.person("NO_HISTORY", "No income, loans, inquiries, scores or insolvency; zero debt and NULL DSTI.")
        c = self.person("INCOME_NO_DEBT", "Positive salary, no credit products: DSTI 0.0%.")
        self.salary(c, 2025, 72000)
        c = self.person("DSTI_39", "2025 net income 71,955 RON; instalment 2,340 RON; DSTI exactly 39.0%.")
        self.salary(c, 2025, 71955)
        p = self.product(c, "DSTI_39", amount=80000, opened="2026-06-15")
        for index, month in enumerate(months_between("2026-06-01", "2027-01-01")):
            self.history(p, month, owed=80000 - index * 1800, instalment=2340)
        self.amortizers.add(p)
        self.score(c, 850)

        for tag, description, income in (
                ("ZERO_INCOME", "Active debt and declared zero 2025 income: NULL DSTI.", 0),
                ("MISSING_INCOME", "Active debt without ANAF income: NULL DSTI.", None),
                ("OLD_INCOME_ONLY", "Income only in 2022, outside the default window: NULL DSTI.", 50000),
                ("OLDER_ELIGIBLE_YEAR", "Income only in 2024: use that year, not a missing 2025.", 60000),
                ("DSTI_OVER_100", "2025 income 12,000 RON and 1,500 RON instalment: 150.0% DSTI.", 12000)):
            c = self.person(tag, description)
            if income is not None:
                self.income(c, net=income, year=2022 if tag == "OLD_INCOME_ONLY" else 2024 if tag == "OLDER_ELIGIBLE_YEAR" else 2025)
            p = self.product(c, tag)
            self.history(p, "2026-09-01", instalment=1500 if tag == "DSTI_OVER_100" else 500)

        c = self.person("MULTI_SOURCE_MULTI_LOAN", "Two employers and rental income; two debts total 300 RON/month; net income 60,000 gives DSTI 6.0%.")
        self.salary(c, 2025, 30000, employer=1)
        self.salary(c, 2025, 18000, employer=2)
        self.income(c, net=12000)
        for index, instalment in enumerate((100, 200), 1):
            p = self.product(c, f"MULTI_SOURCE_LOAN_{index}")
            self.history(p, "2026-09-01", instalment=instalment)
        c = self.person("FRACTIONAL_ROUNDING", "Fractional annual income and instalments exercise REAL/one-decimal DSTI rounding.")
        self.income(c, net=12345.67, source="FICTIV source A")
        self.income(c, net=23456.78, source="FICTIV source B")
        p = self.product(c, "FRACTIONAL_ROUNDING")
        self.history(p, "2026-09-01", instalment=199.51)

        borrower = self.person("SHARED_DEBTOR", "Debtor on shared mortgage; receives the entire 1,000 RON obligation.")
        codebtor = self.person("SHARED_CODEBTOR", "Co-debtor receives the full shared mortgage obligation, not a split.")
        guarantor = self.person("GUARANTOR_ONLY", "Mortgage visible in bureau and CRC; zero debt instalments and one guarantee.")
        p = self.product(borrower, "SHARED_MORTGAGE", kind="MORTGAGE", amount=250000)
        self.history(p, "2026-09-01", owed=240000, instalment=1000, dpd=30)
        self.insert("product_participants", product=p, cnp=codebtor, role="CODEBTOR")
        self.insert("product_participants", product=p, cnp=guarantor, role="GUARANTOR")
        for c in (borrower, codebtor, guarantor):
            self.salary(c, 2025, 60000)
        mixed = self.person("MIXED_ROLES", "Own 200 RON debt plus a guarantee on the 1,000 RON mortgage: count only own debt.")
        self.salary(mixed, 2025, 48000)
        self.insert("product_participants", product=p, cnp=mixed, role="GUARANTOR")
        own = self.product(mixed, "MIXED_OWN")
        self.history(own, "2026-09-01", instalment=200)

        for tag, amount, currency, kind in (
                ("CRC_BELOW", 19999.99, "RON", "CONSUMER_LOAN"),
                ("CRC_EXACT", 20000, "RON", "CONSUMER_LOAN"),
                ("CRC_ABOVE", 20000.01, "RON", "CONSUMER_LOAN"),
                ("CRC_EUR", 25000, "EUR", "CONSUMER_LOAN"),
                ("SMALL_CARD", 8000, "RON", "CREDIT_CARD"),
                ("USD_PRODUCT", 30000, "USD", "OTHER"),
                ("CHF_PRODUCT", 40000, "CHF", "LEASING")):
            c = self.person(tag, f"CRC threshold on granted RON equivalent {amount}; original currency {currency}, low outstanding balance.")
            p = self.product(c, tag, amount=amount, currency=currency, kind=kind)
            self.history(p, "2026-09-01", owed=1000, instalment=100)

        closures = (("BUREAU_4Y_EXACT", "2022-10-28"), ("BUREAU_4Y_OLDER", "2022-10-27"),
                    ("CRC_7Y_EXACT", "2019-10-28"), ("CRC_7Y_OLDER", "2019-10-27"),
                    ("CLOSED_2018", "2018-01-01"), ("RECENT_CLOSED", "2026-09-30"),
                    ("FUTURE_CLOSURE", "2026-12-01"))
        for tag, closed in closures:
            c = self.person(tag, f"Closure {closed}; checks inclusive retention and closure visibility relative to D.")
            opened = f"{int(closed[:4])-3}-01-15"
            p = self.product(c, tag, opened=opened, closed=closed)
            self.timeline(p, end="2027-01-01")

        for tag, opened in (("OPENED_ON_D", AS_OF_DATE), ("OPENED_AFTER_D", "2026-10-29"),
                             ("FUTURE_PRODUCT", "2027-01-05")):
            c = self.person(tag, f"Opened {opened}; never visible before opening; CRC excludes openings after its snapshot.")
            p = self.product(c, tag, opened=opened)
            self.timeline(p, end="2027-02-01")

        for dpd in (0, 1, 30, 31, 60, 61, 90, 91, 180, 181):
            c = self.person(f"DELAY_{dpd:03d}", f"Current days past due {dpd}; positive overdue money whenever delinquent.")
            p = self.product(c, f"DELAY_{dpd:03d}", opened="2025-01-01")
            self.history(p, "2026-09-01", dpd=dpd)
            self.history(p, "2026-10-01", dpd=dpd, owed=19500)
        c = self.person("WORST_24M", "DPD 181 in Oct 2024 excluded, 90 in Nov 2024 included; current DPD 0; future DPD ignored.")
        p = self.product(c, "WORST_24M", opened="2020-01-01")
        for month, dpd, owed in (("2024-10-01", 181, 22000), ("2024-11-01", 90, 21500),
                                  ("2026-09-01", 0, 15000), ("2026-11-01", 181, 14500)):
            self.history(p, month, owed=owed, dpd=dpd)

        c = self.person("INQUIRY_BOUNDARIES", "HARD at Apr 28 and Oct 28 included; Apr 27, old/future HARD, and all SOFT hidden. Count 2.")
        for day, kind in (("2026-04-28", "HARD"), ("2026-04-27", "HARD"), (AS_OF_DATE, "HARD"),
                           ("2025-01-01", "HARD"), ("2026-10-29", "HARD"), ("2026-10-20", "SOFT")):
            self.insert("bureau_inquiries", cnp=c, lender=1, inquiry_date=day, inquiry_type=kind)
        c = self.person("SCORE_TIME_TRAVEL", "Scores 300/700/850 on Jul 1/Oct 28/Oct 29; sorted ranks 1-5; future score ignored.")
        for value, day in ((300, "2026-07-01"), (700, AS_OF_DATE), (850, "2026-10-29")):
            self.score(c, value, day)
        c = self.person("EXPLICIT_NO_SCORE", "Latest score is explicitly NO_SCORE rather than missing.")
        self.score(c, 650, "2026-01-01")
        self.score(c, None)
        c = self.person("SCORE_NO_REASONS", "Valid minimum score 300 with no explanations.")
        self.score(c, 300, reasons=False)

        c = self.person("NO_PAYMENT_HISTORY", "Active exposure with no monthly history: product NULLs, summary zero (unknown, not proof of no debt).")
        self.product(c, "NO_PAYMENT_HISTORY")
        c = self.person("FUTURE_ONLY_HISTORY", "Only Nov 2026 history: bureau/CRC payment figures NULL at default D.")
        p = self.product(c, "FUTURE_ONLY_HISTORY")
        self.history(p, "2026-11-01")
        c = self.person("PARTIAL_HISTORY", "Two active debts, only one has history: total 500 RON is incomplete.")
        self.product(c, "PARTIAL_MISSING")
        p = self.product(c, "PARTIAL_AVAILABLE")
        self.history(p, "2026-09-01")
        c = self.person("CRC_MISSING_MONTH", "August history but no September: bureau falls back, CRC does not.")
        p = self.product(c, "CRC_MISSING_MONTH")
        self.history(p, "2026-08-01")
        c = self.person("CALENDAR_TIME_TRAVEL", "Full 2024-Jan 2027 history; leap-Feb snapshot, latest-history selection and January rollover.")
        p = self.product(c, "CALENDAR_TIME_TRAVEL", kind="MORTGAGE", amount=350000, opened="2024-01-15")
        self.timeline(p, end="2027-01-01")
        for year in range(2022, 2028):
            self.salary(c, year, 60000 + year - 2022)

        for tag, opened, closed, kind in (
                ("INSOLVENCY_OPEN", "2025-01-01", None, "DEBT_REPAYMENT_PLAN"),
                ("INSOLVENCY_4Y_EXACT", "2020-01-01", "2022-10-28", "ASSET_LIQUIDATION"),
                ("INSOLVENCY_4Y_OLDER", "2020-01-01", "2022-10-27", "SIMPLIFIED"),
                ("INSOLVENCY_FUTURE", "2026-10-29", None, "SIMPLIFIED")):
            c = self.person(tag, f"Insolvency opened {opened}, closed {closed}; retained cases determine has_insolvency.")
            self.insert("insolvency_records", cnp=c, procedure_type=kind, opened_on=opened,
                        closed_on=closed, source="FICTIV registry for prototype only")
            if tag == "INSOLVENCY_OPEN":
                p = self.product(c, tag, status="IN_INSOLVENCY_PROCEDURE")
                self.history(p, "2026-09-01", dpd=181)
        c = self.person("FRAUD_7Y_BOUNDARIES", "Fraud at Oct 28 2019 and Oct 28 2026 included; older/future records hidden; nullable lender.")
        for day in ("2019-10-28", "2019-10-27", AS_OF_DATE, "2026-10-29"):
            self.insert("card_fraud_records", cnp=c, lender=None if day == "2019-10-28" else 1,
                        recorded_on=day, fraud_type="FICTIV disputed card use")

        for index, (tag, start, end, form) in enumerate((
                ("ACTIVITY_ACTIVE", "2022-01-15", None, "PFA"),
                ("ACTIVITY_3Y_EXACT", "2020-01-01", "2023-10-28", "II"),
                ("ACTIVITY_3Y_OLDER", "2020-01-01", "2023-10-27", "IF"),
                ("ACTIVITY_FUTURE", "2026-10-29", None, "LIBERAL_PROFESSION")), 1):
            c = self.person(tag, f"{form} activity started {start}, ended {end}; ANAF three-year retention.")
            self.insert("income_activity_forms", cnp=c, form_type=form, name=f"FICTIV activity {index}",
                        fiscal_code=f"TEST-ACT-{index}", address="Adresa fictiva", start_date=start, end_date=end)
            if tag == "ACTIVITY_ACTIVE":
                self.income(c, kind="INDEPENDENT_ACTIVITY", net=90000, source=f"FICTIV activity {index}")
        c = self.person("ALL_INCOME_TYPES", "All seven ANAF income types, including two distinct salary employers.")
        self.salary(c, 2025, 24000)
        self.salary(c, 2025, 12000, employer=2)
        for kind in ("INDEPENDENT_ACTIVITY", "PENSION", "SOCIAL_INSURANCE", "RENTAL", "INVESTMENT", "OTHER"):
            self.income(c, kind=kind, net=6000)
        self.insert("income_activity_forms", cnp=c, form_type="LIBERAL_PROFESSION", name="FICTIV consulting",
                    fiscal_code="TEST-CONSULT", address=None, start_date="2020-01-01", end_date=None)
        c = self.person("PARTIAL_EMPLOYMENT", "Jan 15-Mar 15 fixed-term job plus later part-time job; salary months overlap employment.")
        self.employment(c, start="2025-01-15", end="2025-03-15", contract="FIXED_TERM")
        self.salary(c, 2025, 7500)
        self.employment(c, employer=2, start="2025-06-15", contract="PART_TIME")
        self.salary(c, 2025, 18000, employer=2)

        for status in ("ASSIGNED", "WRITTEN_OFF"):
            c = self.person(f"STATUS_{status}", f"{status} product not closed; remains an obligation under the documented policy.")
            p = self.product(c, f"STATUS_{status}", status=status, lender=5)
            self.history(p, "2026-09-01", dpd=181 if status == "WRITTEN_OFF" else 31)
            self.event(p, "DEBT_ASSIGNMENT" if status == "ASSIGNED" else "PAYMENT_SUSPENSION")
        c = self.person("EVENT_4Y_BOUNDARIES", "Events exactly four years ago and on D retained; day older and future excluded.")
        p = self.product(c, "EVENT_4Y_BOUNDARIES", kind="MORTGAGE", opened="2020-01-01")
        self.history(p, "2026-09-01")
        for day in ("2022-10-28", "2022-10-27", AS_OF_DATE, "2026-10-29"):
            self.event(p, day=day)
        for event in ("RESTRUCTURING", "REFINANCING", "DATION_IN_PAYMENT", "CONTRACT_ASSIGNMENT", "DEBT_ASSIGNMENT", "PAYMENT_SUSPENSION"):
            c = self.person(f"EVENT_{event}", f"Fictional {event.lower()} event; explained balance increase for refinancing/restructuring only.")
            p = self.product(c, f"EVENT_{event}")
            self.history(p, "2026-08-01", owed=20000)
            self.history(p, "2026-09-01", owed=22000 if event in ("RESTRUCTURING", "REFINANCING") else 19500)
            self.event(p, event)
            self.amortizers.add(p)
        c = self.person("REVOLVING_DRAWDOWN", "Revolving balance rises from new drawdowns without restructuring; this is allowed.")
        p = self.product(c, "REVOLVING_DRAWDOWN", kind="OVERDRAFT", amount=30000, rate_type="VARIABLE", rate=None)
        self.history(p, "2026-08-01", owed=5000, instalment=200)
        self.history(p, "2026-09-01", owed=10000, instalment=400)
        c = self.person("YOUNG_ADULT", "Post-2000 CNP century prefix and leap-day birth; credit opens after adulthood.", birth="2004-02-29")
        self.salary(c, 2025, 36000)
        p = self.product(c, "YOUNG_ADULT", opened="2026-01-15", amount=15000)
        self.timeline(p)

    def random_cases(self, count):
        population = [self.person(f"RANDOM_{i:04d}", "Seeded-random fictional background person.", curated=False)
                      for i in range(1, count + 1)]
        kinds = ("CONSUMER_LOAN", "MORTGAGE", "CREDIT_CARD", "OVERDRAFT", "LEASING", "OTHER")
        for index, cnp in enumerate(population):
            income_mode = index % 8
            if income_mode in (0, 1, 2, 3, 4):
                employer = index % 6 + 1
                self.employment(cnp, employer=employer, contract=("INDEFINITE", "FIXED_TERM", "PART_TIME")[index % 3])
                for year in (2023, 2024, 2025):
                    self.salary(cnp, year, self.rng.randrange(3000000, 16000000) / 100, employer)
                if income_mode == 4:
                    self.income(cnp, kind="INVESTMENT", net=self.rng.randrange(1000, 20000))
            elif income_mode == 5:
                self.income(cnp, kind="PENSION", net=self.rng.randrange(18000, 80000))
            elif income_mode == 6:
                self.income(cnp, net=0)
            self.score(cnp, None if index % 11 == 0 else self.rng.randint(300, 850), reasons=index % 4 != 0)
            for _ in range(self.rng.randint(0, 3)):
                self.insert("bureau_inquiries", cnp=cnp, lender=self.rng.randint(1, 5),
                            inquiry_date=f"2026-{self.rng.randint(1, 10):02d}-{self.rng.randint(1, 28):02d}",
                            inquiry_type=self.rng.choice(("HARD", "SOFT")))
            for number in range(self.rng.randint(0, 3)):
                kind = kinds[(index + number) % len(kinds)]
                amount = self.rng.randrange(2500000, 60000000) / 100 if kind == "MORTGAGE" else self.rng.randrange(500000, 10000000) / 100
                opened = f"2024-{self.rng.randint(1, 12):02d}-{self.rng.randint(1, 28):02d}"
                closed = "2026-06-15" if (index + number) % 9 == 0 else None
                currency = self.rng.choices(("RON", "EUR", "USD", "CHF"), (7, 2, 1, 1))[0]
                p = self.product(cnp, f"RANDOM_{index+1:04d}_LOAN_{number+1}", amount=amount, kind=kind,
                                 currency=currency, opened=opened, closed=closed, lender=index % 5 + 1,
                                 rate_type=self.rng.choice(("FIXED", "VARIABLE")), rate=self.rng.choice((0.0, 5.5, 8.0, 12.0)))
                self.timeline(p, delinquent=not closed and (index + number) % 7 == 0)
                if len(population) > 1 and (index + number) % 5 == 0:
                    other = population[(index + 1) % len(population)]
                    self.insert("product_participants", product=p, cnp=other, role="CODEBTOR" if index % 2 else "GUARANTOR")


def build_fixture(db, seed=DEFAULT_SEED, random_people=DEFAULT_RANDOM_PEOPLE):
    if not 0 <= random_people <= 5000:
        raise ValueError("random_people must be between 0 and 5000")
    for table in TABLES:
        if db.execute(f"SELECT EXISTS(SELECT 1 FROM {table})").fetchone()[0]:
            raise ValueError("Fixture generation requires an empty schema; existing data is never erased")
    with db:
        builder = FixtureBuilder(db, seed)
        builder.curated_cases()
        builder.random_cases(random_people)
    return {
        "seed": seed, "as_of_date": AS_OF_DATE, "random_people": random_people,
        "fictional_only": True, "cnp_policy": "Synthetic date/sex-consistent digits with deliberately invalid checksums; never official IDs",
        "sex_by_cnp": builder.sex_by_cnp, "amortizing_products": sorted(builder.amortizers),
        "scenarios": builder.scenarios, "products": builder.products,
        "table_counts": {"report_params": 1, **{t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}},
    }


def validate_fixture(db, manifest):
    """Check structural/data quality and key report expectations without writes."""
    def require(condition, message):
        if not condition:
            raise ValueError(message)

    require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "Database integrity check failed")
    require(not db.execute("PRAGMA foreign_key_check").fetchall(), "Foreign-key violations")
    require(db.execute("SELECT as_of_date FROM report_params WHERE id=1").fetchone()[0] == AS_OF_DATE,
            "Scenario validation expects the fixed default reference date")
    issues = fictional_data_issues(db, manifest["sex_by_cnp"], manifest["amortizing_products"])
    require(not issues, f"Fictional-data quality findings: {issues[:20]}")
    for table, expected in manifest["table_counts"].items():
        require(table in TABLES or table == "report_params", "Unexpected manifest table")
        require(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == expected, f"Row count mismatch: {table}")
    cnps = {item["tag"]: item["cnp"] for item in manifest["scenarios"]}
    def value(view, column, tag):
        row = db.execute(f"SELECT {column} FROM {view} WHERE cnp=?", (cnps[tag],)).fetchone()
        return None if row is None else row[0]

    for tag, expected in (("DSTI_39", 39.0), ("INCOME_NO_DEBT", 0.0), ("DSTI_OVER_100", 150.0),
                          ("MULTI_SOURCE_MULTI_LOAN", 6.0), ("MIXED_ROLES", 5.0),
                          ("ZERO_INCOME", None), ("MISSING_INCOME", None), ("OLD_INCOME_ONLY", None), ("NO_HISTORY", None)):
        require(value("v_dsti_inputs", "current_dsti_pct", tag) == expected, f"Unexpected DSTI for {tag}")
    for tag, view, column, expected in (
            ("GUARANTOR_ONLY", "v_bureau_summary", "active_guarantees", 1),
            ("GUARANTOR_ONLY", "v_bureau_summary", "total_monthly_instalments_ron", 0.0),
            ("SHARED_CODEBTOR", "v_bureau_summary", "total_monthly_instalments_ron", 1000.0),
            ("INQUIRY_BOUNDARIES", "v_bureau_summary", "inquiry_count_6m", 2),
            ("WORST_24M", "v_bureau_summary", "worst_days_past_due_24m", 90),
            ("SCORE_TIME_TRAVEL", "v_bureau_latest_score", "score", 700),
            ("EXPLICIT_NO_SCORE", "v_bureau_summary", "latest_score_status", "NO_SCORE"),
            ("CRC_MISSING_MONTH", "v_bureau_products", "payment_month", "2026-08-01"),
            ("CRC_MISSING_MONTH", "v_crc_exposures", "payment_month", None),
            ("FUTURE_ONLY_HISTORY", "v_bureau_products", "payment_month", None),
            ("RECENT_CLOSED", "v_bureau_summary", "total_monthly_instalments_ron", 0.0)):
        require(value(view, column, tag) == expected, f"Unexpected {view}.{column} for {tag}")
    for view, expected in (
            ("v_bureau_products", {"BUREAU_4Y_EXACT": True, "BUREAU_4Y_OLDER": False, "CLOSED_2018": False,
                                   "OPENED_AFTER_D": False, "OPENED_ON_D": True}),
            ("v_crc_exposures", {"CRC_BELOW": False, "CRC_EXACT": True, "CRC_ABOVE": True, "CRC_EUR": True,
                                 "CRC_7Y_EXACT": True, "CRC_7Y_OLDER": False, "SMALL_CARD": False, "OPENED_ON_D": False})):
        for tag, visible in expected.items():
            require((value(view, "product", tag) is not None) == visible, f"Wrong retention/threshold visibility: {tag}")
    # Stronger generator-specific salary reconciliation, beyond schema checks.
    bad_salary = db.execute("""SELECT i.id FROM income_records i WHERE i.income_type='SALARY'
        AND (ABS(i.net_amount_ron - COALESCE((SELECT SUM(s.net_ron) FROM monthly_salary_declarations s
            JOIN employers e ON e.id=s.employer WHERE s.cnp=i.cnp AND e.fiscal_code=i.source_fiscal_code
            AND CAST(substr(s.month,1,4) AS INTEGER)=i.fiscal_year), -1)) > 0.005
         OR ABS(i.gross_amount_ron - COALESCE((SELECT SUM(s.gross_ron) FROM monthly_salary_declarations s
            JOIN employers e ON e.id=s.employer WHERE s.cnp=i.cnp AND e.fiscal_code=i.source_fiscal_code
            AND CAST(substr(s.month,1,4) AS INTEGER)=i.fiscal_year), -1)) > 0.005)""").fetchall()
    require(not bad_salary, "Annual salary does not reconcile with monthly declarations")
    view_counts = {}
    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='view' ORDER BY name").fetchall():
        rows = db.execute(f"SELECT * FROM {name}").fetchall()
        require(bool(rows), f"No visible fixture in view {name}")
        view_counts[name] = len(rows)
    return view_counts


def export_data_sql(db):
    """Only explicit-column inserts, in FK order; generated columns are omitted."""
    lines = [
        "PRAGMA foreign_keys = ON;",
        "-- FICTIONAL DATA ONLY. Load after the separate schema into an empty database.",
        "-- Synthetic identities; intentionally invalid CNP checksums; not official reports.",
        "-- On any error ROLLBACK; do not continue/commit a partially failed import.",
        "BEGIN IMMEDIATE;",
        "-- Empty-target guard, including tables whose integer IDs might not collide.",
        "CREATE TEMP TABLE fixture_load_guard (empty_target INTEGER NOT NULL CHECK(empty_target=1));",
    ]
    empty = " AND ".join(f"NOT EXISTS(SELECT 1 FROM {table})" for table in TABLES)
    lines += [f"INSERT OR ROLLBACK INTO fixture_load_guard VALUES ({empty});", "DROP TABLE fixture_load_guard;",
              f"UPDATE report_params SET as_of_date='{AS_OF_DATE}' WHERE id=1;"]
    def literal(value):
        if value is None:
            return "NULL"
        if isinstance(value, str):
            return "'" + value.replace("'", "''") + "'"
        return repr(value)
    for table in TABLES:
        info = db.execute(f"PRAGMA table_info({table})").fetchall()
        columns = [row[1] for row in info]
        keys = [row[1] for row in sorted(info, key=lambda r: r[5]) if row[5]]
        select = f"SELECT {', '.join(columns)} FROM {table} ORDER BY {', '.join(keys)}"
        lines.append(f"-- {table}")
        for row in db.execute(select):
            lines.append(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(literal(v) for v in row)});")
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def export_catalogue(manifest):
    lines = ["# Fictional credit-source scenarios", "",
             f"Seed: `{manifest['seed']}`. Default reference date: `{AS_OF_DATE}`.", "",
             f"{len(manifest['scenarios'])} guaranteed labelled cases plus {manifest['random_people']} seeded-random people.",
             "No real records are used. CNPs deliberately fail the checksum; names/addresses/employers are fictional and phones are NULL.",
             "", "## Find a scenario", "", "```sql",
             "SELECT p.persona_tag, p.cnp, d.* FROM persons p JOIN v_dsti_inputs d USING(cnp)",
             "WHERE p.persona_tag = 'DSTI_39';",
             "SELECT p.persona_tag, b.* FROM persons p JOIN v_bureau_summary b USING(cnp)",
             "WHERE p.persona_tag NOT LIKE 'RANDOM_%';", "```", "",
             "For year rollover use D = 2027-01-05; for leap-month CRC use D = 2024-03-01.",
             "Restore D = 2026-10-28 after exploring. Future fixture rows are intentional, not real predictions.", "",
             "Missing-history scenarios are intentional completeness gaps, not zero-debt evidence.",
             "The dataset covers valid states only: bad CNP syntax, invalid scores, duplicate keys, orphan rows,",
             "invalid dates, deletes/cascades and rollback behavior remain in automated tests rather than corrupting fixtures.",
             "No universal monotonic-balance or exact accounting-ledger claim is made. Monthly and annual salaries reconcile;",
             "selected fixed-rate RON amortizer scenarios have nonincreasing balances except event-explained increases.",
             "", "## Guaranteed cases", "", "| persona_tag | CNP (synthetic) | Scenario |", "| --- | --- | --- |"]
    for scenario in manifest["scenarios"]:
        lines.append(f"| {scenario['tag']} | {scenario['cnp']} | {scenario['description']} |")
    lines += ["", "## Table counts", "", "| Table | Rows |", "| --- | ---: |"]
    lines += [f"| {table} | {count} |" for table, count in manifest["table_counts"].items()]
    return "\n".join(lines) + "\n"


def load_empty_target(target, sql, manifest):
    """Transactional, refuse-populated loader with a persistent empty backup."""
    target = Path(target).resolve()
    if not target.is_file():
        raise ValueError("Create the empty database from the schema first; target does not exist")
    backup_path = target.with_name(f"{target.stem}.before_sample_data_{datetime.now():%Y%m%d_%H%M%S_%f}{target.suffix}")
    with closing(sqlite3.connect(target.as_uri() + "?mode=rw", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        if any(db.execute(f"SELECT EXISTS(SELECT 1 FROM {table})").fetchone()[0] for table in TABLES):
            raise ValueError("Refusing to overwrite a populated database; use a separate empty target")
        with closing(new_database()) as expected:
            query = "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
            if [tuple(r) for r in db.execute(query)] != [tuple(r) for r in expected.execute(query)]:
                raise ValueError("Target schema differs from the current SQL script")
        with backup_path.open("xb"):
            pass
        with closing(sqlite3.connect(backup_path)) as backup:
            db.backup(backup)
        try:
            # Keep the transaction open through validation; validate BEFORE commit.
            db.executescript(sql.rsplit("COMMIT;", 1)[0])
            validate_fixture(db, manifest)
            db.commit()
        except Exception:
            db.rollback()
            raise
    with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as persisted:
        persisted.row_factory = sqlite3.Row
        validate_fixture(persisted, manifest)
    return backup_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--random-people", type=int, default=DEFAULT_RANDOM_PEOPLE)
    parser.add_argument("--output-dir", type=Path, default=SAMPLE_DIR, help="Existing directory; generated files are never overwritten")
    parser.add_argument("--load", type=Path, help="Optional existing EMPTY database to populate after validation and backup")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    names = ("credit_sources_sample_data.sql", "sample_data_manifest.json", "SAMPLE_DATA.md")
    if not output.is_dir() or any((output / name).exists() for name in names):
        parser.error("Output directory must exist and sample output files must not already exist; use another directory")
    with closing(new_database()) as db:
        manifest = build_fixture(db, args.seed, args.random_people)
        manifest["view_counts_at_default_date"] = validate_fixture(db, manifest)
        sql = export_data_sql(db)
        # Validate the actual exported SQL in a second empty database, not just the builder.
        with closing(new_database()) as replay:
            replay.executescript(sql)
            validate_fixture(replay, manifest)
        payloads = (sql, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", export_catalogue(manifest))
        for name, payload in zip(names, payloads):
            with (output / name).open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
    if args.load:
        backup = load_empty_target(args.load, sql, manifest)
        print(f"Populated and verified: {args.load.resolve()}")
        print(f"Original empty database backup: {backup}")
    print(f"Validated {len(manifest['scenarios'])} labelled cases + {args.random_people} random people; seed {args.seed}")
    print(json.dumps(manifest["table_counts"], indent=2))
    for name in names:
        print(output / name)


if __name__ == "__main__":
    main()