# ADR 007: Document Processing, OCR Extraction, Verification and Secure Storage Pipeline

## Status
Accepted (Implemented on `feature/document-processing-pipeline`)

## Context and Regulatory Framework
Under Romanian banking regulations (notably BNR Regulation No. 17/2012 on credit conditions and Regulation No. 12/2018 on debt-to-income limits), credit origination requires strict Know Your Customer (KYC) identity verification, proof of stable recurring income, and indebtedness evaluation.

In retail lending, three primary applicant documents form the cornerstone of the credit dossier:
1. **Actul de Identitate (Carte de Identitate / Buletin)**: Proves customer identity, citizenship/residence, age (minimum 18 years, maximum loan maturity age 65-70 years), and validity period.
2. **Dovada de Venit (Adeverință de Salariu / Adeverință de Venit)**: Proves current employment contract status (perioadă nedeterminată), minimum seniority at current employer (standard BNR/bank requirement: at least 3 months continuous employment, 12 months total work history), absence of salary garnishments (*popriri*), and gross/net salary breakdown with legal deductions (CAS 25%, CASS 10%, Tax 10%).
3. **Extras de Cont Bancar**: Verifies account ownership (matching IBAN and holder), recent incoming salary deposits, existing debt servicing (installments for other active loans), and balance consistency over recent months.

The earlier repository prototype only performed superficial metadata checks (`FORMAT_ACCEPTED` without file parsing or authenticity verification). This ADR implements the complete 4-stage pipeline specified in `ARCHITECTURE.md` (Flow 2):
```text
Document Processing Service -> OCR + Extraction -> Validation & Verification -> Secure Document Storage
```

---

## Architecture & Component Breakdown

### 1. Document Processing Service (`src/services/document_processing/`)
- Acts as the unified orchestrator across the ingestion, extraction, validation, and storage stages.
- Exposes `process_and_store(...)` which accepts file bytes or paths, determines document kinds, delegates to extractors and validators, persists into secure storage, and returns structured `ProcessedDocumentResponse`.
- Exposes `cross_validate_application(...)` which performs cross-document consistency checks across the full applicant dossier (Identity + Income + Statement).

### 2. OCR + Extraction (`src/parsers/ocr/`, `src/parsers/extraction/`)
- **PDF & OCR Extractor (`PdfExtractor`)**: Extracts text streams from vector PDFs via `pypdf`, and reads embedded OCR text layers (`/Subject` metadata) for scanned PDF/A copies.
- **Identity Card Extractor (`IdCardExtractor`)**: Extracts CNP, series, number, first name, last name, address, issuer, validity interval, and Machine Readable Zone (MRZ lines).
- **Income Certificate Extractor (`IncomeCertificateExtractor`)**: Extracts employer name, CUI/CIF, Reg. Com., employee name, employee CNP, job title, contract type (Nedeterminată/Determinată), employment start date, net/gross salary figures, average net income, and issuance date.
- **Bank Statement Extractor (`BankStatementExtractor`)**: Extracts bank name, BIC, account holder, Romanian IBAN, statement currency, period, opening/closing balances, total debits/credits, transaction count, and incoming salary transfers.

### 3. Validation & Verification (`src/parsers/validation/`)
- **CNP Validation (`cnp_validator.py`)**:
  - Implements the official Romanian algorithm: 12-digit dot-product with weight vector `279146358279`, modulo 11 check digit (with remainder 10 mapping to 1).
  - Validates sex and century (`1/2` for 1900-1999, `3/4` for 1800-1899, `5/6` for 2000-2099, `7/8` for residents).
  - Validates calendar birth date (e.g., rejecting invalid dates like Feb 30).
  - Enforces BNR adult age rule ($18 \le \text{age} \le 70$).
  - Supports synthetic test mode where intentionally invalid test CNPs from `credit_sources` are recognized without breaking tests.
- **CUI / CIF Validation (`cui_validator.py`)**:
  - Implements the official Romanian Ministry of Finance key testing algorithm using test constant `753217532` aligned right-to-left.
  - Multiplies body digits, multiplies sum by 10, modulo 11 check (remainder 10 maps to 0).
- **IBAN Validation (`iban_validator.py`)**:
  - Validates Romanian IBAN structure (24 characters, starts with `RO`, 4 letters bank code).
  - Implements ISO 7064 MOD 97-10 check algorithm.
- **Document Rules Engine (`document_validator.py`)**:
  - Document expiration checks: ID card must not be expired at assessment time.
  - Recency rule: Income certificate must not be older than 30 calendar days.
  - Seniority rule: Minimum 90 days (3 months) at current employer.
  - Contract type rule: Contract must be on indefinite term (*perioadă nedeterminată*).
  - Net income threshold: Income must exceed Romanian legal minimum wage threshold (2,363 RON net).
  - Mathematical balance integrity: Statement opening balance + total credits - total debits == closing balance.
  - Cross-Document checks:
    - Name match across ID Card, Income Certificate, and Bank Statement.
    - CNP match between ID Card and Income Certificate.
    - Net salary on Income Certificate aligns with salary deposits on Bank Statement.

### 4. Secure Document Storage (`src/storage/secure_documents/`)
- Isolated file storage under `data/local/secure_documents/<customer_id>/`.
- UUID-based sanitized storage filenames preventing path traversal attacks.
- SHA-256 cryptographic hashing at ingestion time.
- Tamper-detection verification (`verify_integrity(doc_id)`): compares on-disk bytes against registered hash.
- Role/customer-bound access control (`customer_id` check prevents cross-tenant file leakage).
- File size limit (10 MB) and strict MIME type allowlist (`application/pdf`, `image/png`, `image/jpeg`).

---

## Consequences & Benefits
- Replaces mock metadata stubs with authentic document extraction and verification.
- Enforces real Romanian regulatory standards (BNR, ANAF, Min. Finanțe, ISO 7064).
- Provides immediate end-to-end testing with generated synthetic A4 PDF documents.
- Maintains modular isolation: changes are contained on `feature/document-processing-pipeline` and do not disturb `main`.
