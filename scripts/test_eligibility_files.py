"""Automated test runner and demonstration for eligibility document & engine verification.

Usage:
    python -m scripts.test_eligibility_files
"""

import sys
from pathlib import Path
from decimal import Decimal

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.models.document_processing import DocumentKind, DocumentProcessingStatus
from src.parsers.ocr.pdf_extractor import PdfExtractor
from src.parsers.extraction.income_certificate_extractor import IncomeCertificateExtractor
from src.parsers.validation.document_validator import DocumentValidator
from src.services.document_processing.service import DocumentProcessingService


def run_document_tests() -> bool:
    print("=" * 78)
    print("TESTARE COMPATIBILITATE DOCUMENTE ELIGIBILITATE (OCR & VALIDATOR REGLEMENTAR)")
    print("=" * 78)

    service = DocumentProcessingService()
    base_dir = Path("data/test_samples_eligibility")

    test_cases = [
        {
            "name": "Adeverință ANAF cu Venit Zero (Victor Nistor)",
            "file": base_dir / "01_RESPINS_Venit_Zero" / "adeverinta_anaf_zero_venit.pdf",
            "expected_status": DocumentProcessingStatus.REJECTED,
            "expected_income": 0.0,
            "description": "Venit 0,00 RON la ANAF -> Nu poate aplica pentru credit (Respins)",
        },
        {
            "name": "Adeverință Salariu Angajator cu Venit Zero (Victor Nistor)",
            "file": base_dir / "01_RESPINS_Venit_Zero" / "adeverinta_venit_zero_venituri.pdf",
            "expected_status": DocumentProcessingStatus.REJECTED,
            "expected_income": 0.0,
            "description": "Contract suspendat / 0 ore lucrate -> Respins conform politicii de venit minim",
        },
        {
            "name": "Adeverință ANAF cu Venituri Salariale Optime (Alex Morgan)",
            "file": base_dir / "02_ELIGIBIL_Venit_Optim" / "adeverinta_anaf_venit_ok.pdf",
            "expected_status": DocumentProcessingStatus.VALIDATED,
            "expected_income": 8500.0,
            "description": "Venit net 8.500 RON/lună confirmat ANAF -> Eligibil pentru creditare",
        },
        {
            "name": "Adeverință Salariu Angajator Venituri Optime (Alex Morgan)",
            "file": base_dir / "02_ELIGIBIL_Venit_Optim" / "adeverinta_venit_ok_8500_ron.pdf",
            "expected_status": DocumentProcessingStatus.VALIDATED,
            "expected_income": 8500.0,
            "description": "Contract nedeterminat, salariu 8.500 RON -> Eligibil",
        },
        {
            "name": "Adeverință Venit Sub Salariul Minim Legal (Maria Popescu)",
            "file": base_dir / "03_RESPINS_Venit_Sub_Minim" / "adeverinta_venit_sub_minim_1500_ron.pdf",
            "expected_status": DocumentProcessingStatus.REJECTED,
            "expected_income": 1500.0,
            "description": "Salariu 1.500 RON < salariul minim net legal (2.363 RON) -> Respins",
        },
    ]

    all_passed = True

    for idx, tc in enumerate(test_cases, 1):
        path = tc["file"]
        if not path.exists():
            print(f"[FAIL] Fișierul nu există: {path}")
            all_passed = False
            continue

        result = service.process_and_store(
            content=path,
            filename=path.name,
            mime_type="application/pdf",
            customer_id=f"test-cust-{idx}",
            declared_kind=DocumentKind.INCOME,
        )

        extracted_income = result.extracted_data.get("monthly_net_income") or result.extracted_data.get("average_net_income", 0.0)
        status_match = result.status == tc["expected_status"]
        income_match = abs(extracted_income - tc["expected_income"]) < 1.0

        if status_match and income_match:
            mark = "[PASS]"
        else:
            mark = "[FAIL]"
            all_passed = False

        print(f"\n{mark} Test #{idx}: {tc['name']}")
        print(f"       Fișier: {path.name}")
        print(f"       Scenariu: {tc['description']}")
        print(f"       Venit extras: {extracted_income:,.2f} RON (Așteptat: {tc['expected_income']:,.2f} RON)")
        print(f"       Status validare: {result.status.value} (Așteptat: {tc['expected_status'].value})")

        if result.validation.reasons:
            print("       Motive / Reguli declanșate:")
            for reason in result.validation.reasons:
                print(f"        * {reason}")

    print("\n" + "=" * 78)
    if all_passed:
        print("[SUCCESS] Toate fișierele de testare a eligibilității au trecut verificările cu brio!")
    else:
        print("[WARNING] Unele teste nu au produs rezultatul așteptat.")
    print("=" * 78)
    return all_passed


if __name__ == "__main__":
    success = run_document_tests()
    sys.exit(0 if success else 1)
