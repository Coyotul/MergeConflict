"""Typed data models for applicant document processing, OCR extraction and verification."""

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DocumentKind(str, Enum):
    IDENTITY = "identity"
    INCOME = "income"
    STATEMENT = "statement"


class DocumentProcessingStatus(str, Enum):
    UPLOADED = "UPLOADED"
    EXTRACTED = "EXTRACTED"
    VALIDATED = "VALIDATED"
    FLAGGED_FOR_HUMAN_REVIEW = "FLAGGED_FOR_HUMAN_REVIEW"
    REJECTED = "REJECTED"


class ExtractedIdentity(BaseModel):
    cnp: str = ""
    series: str = ""
    number: str = ""
    last_name: str = ""
    first_name: str = ""
    gender: str = ""
    birth_date: Optional[date] = None
    birth_place: str = ""
    address: str = ""
    citizenship: str = "Română / ROU"
    issuer: str = ""
    issue_date: Optional[date] = None
    expiry_date: Optional[date] = None
    mrz_line1: str = ""
    mrz_line2: str = ""
    confidence_score: float = Field(default=1.0, ge=0, le=1)
    raw_text: str = ""


class ExtractedIncome(BaseModel):
    employer_name: str = ""
    employer_cui: str = ""
    employer_reg_com: str = ""
    employee_name: str = ""
    employee_cnp: str = ""
    job_title: str = ""
    contract_type: str = ""
    employment_start_date: Optional[date] = None
    monthly_net_income: float = 0.0
    monthly_gross_income: float = 0.0
    average_net_income: float = 0.0
    salary_breakdown: List[Dict[str, Any]] = Field(default_factory=list)
    issue_date: Optional[date] = None
    confidence_score: float = Field(default=1.0, ge=0, le=1)
    raw_text: str = ""


class ExtractedStatement(BaseModel):
    bank_name: str = ""
    account_holder: str = ""
    iban: str = ""
    currency: str = "RON"
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    initial_balance: float = 0.0
    closing_balance: float = 0.0
    total_credits: float = 0.0
    total_debits: float = 0.0
    balance_fields_complete: bool = True
    transactions_count: int = 0
    detected_salary_deposit: Optional[float] = None
    existing_monthly_obligations: Optional[float] = None
    confidence_score: float = Field(default=1.0, ge=0, le=1)
    raw_text: str = ""


class RuleEvaluation(BaseModel):
    code: str
    description: str
    passed: bool
    severity: str = "ERROR"  # "ERROR", "WARNING", "INFO"
    detail: str = ""


class DocumentValidationSummary(BaseModel):
    valid: bool
    status: DocumentProcessingStatus
    rules_evaluated: List[RuleEvaluation] = Field(default_factory=list)
    passed_rules_count: int = 0
    failed_rules_count: int = 0
    warnings_count: int = 0
    human_review_required: bool = False
    reasons: List[str] = Field(default_factory=list)


class CrossDocumentValidationSummary(BaseModel):
    consistent: bool
    human_review_required: bool = False
    name_matched: bool = False
    cnp_matched: bool = False
    salary_verified_in_statement: bool = False
    checks_performed: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)


class ProcessedDocumentResponse(BaseModel):
    document_id: str
    customer_id: str
    kind: DocumentKind
    original_filename: str
    mime_type: str
    file_size_bytes: int
    sha256_hash: str
    storage_path: str
    uploaded_at: datetime
    processed_at: datetime
    status: DocumentProcessingStatus
    extracted_data: Optional[Dict[str, Any]] = None
    validation: DocumentValidationSummary
