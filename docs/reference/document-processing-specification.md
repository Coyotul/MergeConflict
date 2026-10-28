# Document Processing & Verification Technical Specification

This reference specification documents the business rules, algorithms, and validation checks implemented in the Document Processing Pipeline.

## 1. Document Requirements & Regulatory Basis

| Document Kind | Romanian Equivalent | Legal / Regulatory Purpose | Mandatory Fields |
| :--- | :--- | :--- | :--- |
| `IDENTITY` | Carte de Identitate / Buletin | KYC, vârstă legală, rezidență, termen de valabilitate | CNP, Nume, Prenume, Serie, Număr, Domiciliu, Data nașterii, Data expirării |
| `INCOME` | Adeverință de Venit / Salariu | Stabilitate financiară, vechime minimă (3 luni), lipsă popriri, calcul DSTI | Nume angajator, CUI/CIF, Nume salariat, CNP, Funcție, Tip contract, Vechime, Venit net, Data emiterii |
| `STATEMENT` | Extras de Cont Curent | Verificare cont activ, virament salariu, alte rate/obligații lunare | Bancă, Titular, IBAN (RO), Perioadă, Sold inițial, Sold final, Total rulaj debitor/creditor, Tranzacții |

---

## 2. Validation Rules & Codes

### Identity Rules (`ID_*`)
- `ID_CNP_FORMAT`: 13-digit numeric structure; valid sex/century prefix (1–8); valid calendar birth date.
- `ID_CNP_CHECKSUM`: Modulo 11 checksum calculation using key vector `279146358279`. (Synthetic test fixtures are recognized via `allow_synthetic_cnp`).
- `ID_AGE_POLICY`: Applicant must be an adult ($18 \le \text{age} \le 70$).
- `ID_NOT_EXPIRED`: `expiry_date >= as_of_date`.
- `ID_COMPLETENESS`: First name, last name, series, and number must be populated.
- `ID_MRZ_CONSISTENCY`: If MRZ line 1 is present, VIZ last name must match MRZ name field.

### Income Certificate Rules (`INC_*`)
- `INC_CUI_VALID`: Employer CUI/CIF must pass the Ministry of Finance key `753217532` algorithm.
- `INC_RECENCY`: Certificate issue date must be within 30 calendar days of loan application.
- `INC_SENIORITY`: Continuous seniority at current employer must be at least 90 days (~3 months).
- `INC_CONTRACT_TYPE`: Contract must be `NEDETERMINATĂ`. If fixed term, flags warning for reviewer inspection.
- `INC_MIN_INCOME`: Net salary must be $\ge 2,363$ RON (Romanian statutory minimum net wage).

### Bank Statement Rules (`STMT_*`)
- `STMT_IBAN_VALID`: Starts with `RO`, length 24, valid bank code, passes ISO 7064 MOD 97-10 check.
- `STMT_BALANCE_INTEGRITY`: `initial_balance + total_credits - total_debits == closing_balance` (tolerance $\pm 1$ RON).
- `STMT_RECENCY`: Statement period must be within the last 90 calendar days.
- `STMT_SALARY_INFLOW`: Identifies recurring salary credit transfers from employer.

### Cross-Document Reconciliation (`CROSS_*`)
- `CROSS_NAME_MATCH`: ID Card name reconciles with Income Certificate employee name and Statement account holder.
- `CROSS_CNP_MATCH`: ID Card CNP equals Income Certificate employee CNP.
- `CROSS_SALARY_MATCH`: Statement salary inflow deposit corresponds to declared income certificate net income (within $\pm 25\%$).

---

## 3. Secure Storage Specification

- **Root Location**: `data/local/secure_documents/`
- **Customer Directory**: `data/local/secure_documents/<customer_id>/`
- **File Naming**: `doc_<16_hex_uuid>.<ext>`
- **Cryptographic Fingerprint**: SHA-256 computed on binary stream.
- **Integrity Verification**: `store.verify_integrity(doc_id)` computes live hash from disk and matches against registered hash.
- **Access Boundary**: Customer ID bound; unauthorized access raises `PermissionError`.
- **MIME & Size Restrictions**: `.pdf`, `.png`, `.jpg`, `.jpeg` up to $10\text{ MB}$.

---

## 4. Usage Example

```python
from pathlib import Path
from src.services.document_processing import DocumentProcessingService
from src.models.document_processing import DocumentKind

service = DocumentProcessingService()

# Ingest and validate an identity document PDF
response = service.process_and_store(
    content=Path("data/synthetic/documents/alex_morgan_demo_customer/buletin_alex_morgan_demo_customer.pdf"),
    filename="buletin.pdf",
    mime_type="application/pdf",
    customer_id="alex_morgan",
    declared_kind=DocumentKind.IDENTITY,
)

print(response.status)              # DocumentProcessingStatus.VALIDATED
print(response.extracted_data)      # {'cnp': '1920515410012', 'last_name': 'MORGAN', ...}
print(response.validation.valid)    # True
```
