"""Data models and configurations for synthetic banking document generation."""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import List, Optional


class DocumentVisualMode(str, Enum):
    SCANNED = "scanned"
    PHOTO = "photo"
    PHOTO_DIAGONAL = "photo_diagonal"


@dataclass
class SalaryMonth:
    month_name: str
    year: int
    gross_ron: float
    cas_ron: float
    cass_ron: float
    tax_ron: float
    meal_tickets_ron: float
    net_ron: float


@dataclass
class TransactionRow:
    date_str: str
    tx_type: str
    description: str
    amount_ron: float
    balance_after_ron: float


@dataclass
class ExistingLoanInfo:
    loan_type: str
    lender: str
    original_amount_ron: float
    current_balance_ron: float
    monthly_installment_ron: float
    remaining_months: int


@dataclass
class CustomerDocumentProfile:
    customer_id: str
    first_name: str
    last_name: str
    cnp: str
    birth_date: str
    gender: str  # "M" or "F"
    address: str
    phone: str = "+40 721 000 000"
    email: str = "client.demo@example.test"
    persona_tag: Optional[str] = None
    visual_mode: DocumentVisualMode = DocumentVisualMode.SCANNED

    # Identity card details
    id_series: str = "RX"
    id_number: str = "123456"
    id_issuer: str = "SPCLEP Sector 1"
    id_issue_date: str = "2024-05-15"
    id_expiry_date: str = "2034-05-15"
    birth_place: str = "Mun. București Sec. 1"
    citizenship: str = "Română / ROU"

    # Employment & income
    employer_name: str = "Northstar Studio S.R.L."
    employer_cui: str = "RO 39281720"
    employer_reg_com: str = "J40/1234/2018"
    employer_address: str = "Str. Calea Victoriei nr. 120, București"
    job_title: str = "Specialist IT / Consultant"
    contract_type: str = "Nedeterminată"
    employment_start_date: str = "2022-03-01"
    monthly_net_income: float = 8500.00
    monthly_gross_income: float = 14530.00

    # Banking & account
    bank_name: str = "RAIFFEISEN BANK S.A."
    bank_swift: str = "RZBRROBU"
    iban: str = "RO49 RZBR 0000 0600 1234 5678"
    account_currency: str = "RON"
    initial_balance: float = 12480.50
    existing_loans: List[ExistingLoanInfo] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def slug(self) -> str:
        tag = self.persona_tag.lower() if self.persona_tag else ""
        name = f"{self.first_name}_{self.last_name}".lower().replace(" ", "_")
        return f"{name}_{tag}".strip("_")
