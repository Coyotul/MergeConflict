#!/usr/bin/env python3
"""CLI tool for manually testing and verifying the Romanian Document Processing Pipeline.

Allows testing individual documents (PDF/PNG) or full customer dossiers (ID card,
Income certificate, Bank statement) through the 4-stage processing pipeline:
  1. Secure Storage & Tamper Check (SHA-256)
  2. OCR & Structured Extraction
  3. Regulatory Validation (BNR 17/2012, 12/2018, CNP, CUI, IBAN)
  4. Cross-Document Reconciliation

Examples:
  # Test the full dossier for Alex Morgan:
  python scripts/verify_documents.py

  # Test a specific synthetic customer:
  python scripts/verify_documents.py --customer dan_ionescu_dsti_39

  # Test a single custom PDF file:
  python scripts/verify_documents.py --file data/synthetic/documents/alex_morgan_demo_customer/buletin_alex_morgan_demo_customer.pdf --type identity

  # List all available synthetic customer folders:
  python scripts/verify_documents.py --list
"""

import argparse
import json
from pathlib import Path
import sys

# Windows terminal UTF-8 output protection
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure repository root is in sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models.document_processing import DocumentKind, DocumentProcessingStatus
from src.parsers.extraction.bank_statement_extractor import BankStatementExtractor
from src.parsers.extraction.id_card_extractor import IdCardExtractor
from src.parsers.extraction.income_certificate_extractor import IncomeCertificateExtractor
from src.parsers.validation.cnp_validator import parse_cnp
from src.parsers.validation.cui_validator import validate_cui
from src.parsers.validation.iban_validator import validate_iban
from src.services.document_processing.service import DocumentProcessingService
from src.storage.secure_documents.store import SecureDocumentStore

DOCS_DIR = ROOT / "data" / "synthetic" / "documents"


def print_banner(text: str) -> None:
    sep = "=" * 70
    print(f"\n{sep}\n  {text}\n{sep}")


def print_section(title: str) -> None:
    print(f"\n--- {title} ---")


def format_status(status: DocumentProcessingStatus) -> str:
    if status == DocumentProcessingStatus.VALIDATED:
        return "[VALIDAT / CONFORM]"
    elif status == DocumentProcessingStatus.FLAGGED_FOR_HUMAN_REVIEW:
        return "[NECESITA REVIZIE UMANA]"
    elif status == DocumentProcessingStatus.REJECTED:
        return "[RESPINS / NECONFORM]"
    return f"[{status.value}]"


def verify_single_file(
    service: DocumentProcessingService,
    file_path: Path,
    declared_kind: DocumentKind,
    customer_id: str = "manual_test_customer",
) -> None:
    if not file_path.exists():
        print(f"[ERROR] File not found: {file_path}")
        return

    print_banner(f"VERIFICARE FIȘIER: {file_path.name} ({declared_kind.value})")
    print(f"Dimensiune fișier: {file_path.stat().st_size:,} bytes")
    print(f"Tip MIME: application/pdf")

    # Run processing
    result = service.process_and_store(
        content=file_path,
        filename=file_path.name,
        mime_type="application/pdf",
        customer_id=customer_id,
        declared_kind=declared_kind,
    )

    # 1. Secure Storage
    print_section("ETAPA 1: Secure Document Storage & Integritate")
    print(f"Document ID:   {result.document_id}")
    print(f"Cale Stocare:  {result.storage_path}")
    print(f"Hash SHA-256:  {result.sha256_hash}")
    integrity_ok = service.storage.verify_integrity(result.document_id)
    print(f"Tamper Check:  {'[OK] Integritate confirmată (SHA-256 identic)' if integrity_ok else '[FAIL] Hash mismatch!'}")

    # 2. OCR & Extraction
    print_section("ETAPA 2: OCR & Extracție Date Structurate")
    from src.parsers.ocr.pdf_extractor import PdfExtractor
    raw_ocr = PdfExtractor.extract_text(file_path) if file_path.suffix.lower() == ".pdf" else PdfExtractor.extract_image_text(file_path)
    if raw_ocr:
        preview = raw_ocr.strip().replace("\r\n", " ").replace("\n", " ")
        if len(preview) > 350:
            preview = preview[:350] + " ... [trunchiat]"
        print(f"  [Text Extras prin OCR ({len(raw_ocr)} caractere)]:")
        print(f"  \"{preview}\"\n")
    else:
        print("  [Atenție]: Nu s-a putut extrage text prin OCR.\n")

    if result.extracted_data:
        for key, value in result.extracted_data.items():
            if value is not None and value != "" and value != [] and key != "raw_text":
                print(f"  * {key:26}: {value}")

    # 3. Validation Rules
    print_section(f"ETAPA 3: Reguli de Validare & Conformitate -> {format_status(result.status)}")
    for rule in result.validation.rules_evaluated:
        tag = "[PASS]" if rule.passed else ("[WARN]" if rule.severity == "WARNING" else "[FAIL]")
        print(f"  {tag:7} [{rule.code:22}] {rule.description}")
        if rule.detail:
            print(f"          Detalii: {rule.detail}")

    if result.validation.reasons:
        print("\n  Motive / Observații:")
        for r in result.validation.reasons:
            print(f"    - {r}")


def verify_customer_dossier(service: DocumentProcessingService, customer_folder: Path) -> None:
    customer_id = customer_folder.name
    print_banner(f"DOSAR COMPLET CLIENT: {customer_id}")

    buletin_pdf = next(customer_folder.glob("buletin_*.pdf"), None)
    adeverinta_pdf = next(customer_folder.glob("adeverinta_venit_*.pdf"), None)
    extras_pdf = next(customer_folder.glob("extras_cont_*.pdf"), None)

    typed_id = None
    typed_inc = None
    typed_stmt = None

    if buletin_pdf:
        res = service.process_and_store(
            content=buletin_pdf,
            filename=buletin_pdf.name,
            mime_type="application/pdf",
            customer_id=customer_id,
            declared_kind=DocumentKind.IDENTITY,
        )
        print(f"\n[1/3] BULETIN ({buletin_pdf.name}): {format_status(res.status)}")
        ext = res.extracted_data or {}
        cnp_meta = parse_cnp(ext.get("cnp", ""))
        print(f"      Titular: {ext.get('last_name')} {ext.get('first_name')} | CNP: {ext.get('cnp')} | Varsta: {cnp_meta.age_years} ani")
        for r in res.validation.rules_evaluated:
            tag = "[OK]" if r.passed else "[FAIL]"
            print(f"        {tag} [{r.code:18}] {r.description}")

    if adeverinta_pdf:
        res = service.process_and_store(
            content=adeverinta_pdf,
            filename=adeverinta_pdf.name,
            mime_type="application/pdf",
            customer_id=customer_id,
            declared_kind=DocumentKind.INCOME,
        )
        print(f"\n[2/3] ADEVERINTA VENIT ({adeverinta_pdf.name}): {format_status(res.status)}")
        ext = res.extracted_data or {}
        print(f"      Angajator: {ext.get('employer_name')} (CUI {ext.get('employer_cui')})")
        print(f"      Venit Net: {ext.get('monthly_net_income')} RON | Start CIM: {ext.get('employment_start_date')} | Contract: {ext.get('contract_type')}")
        for r in res.validation.rules_evaluated:
            tag = "[OK]" if r.passed else "[FAIL]"
            print(f"        {tag} [{r.code:18}] {r.description}")

    if extras_pdf:
        res = service.process_and_store(
            content=extras_pdf,
            filename=extras_pdf.name,
            mime_type="application/pdf",
            customer_id=customer_id,
            declared_kind=DocumentKind.STATEMENT,
        )
        print(f"\n[3/3] EXTRAS DE CONT ({extras_pdf.name}): {format_status(res.status)}")
        ext = res.extracted_data or {}
        print(f"      Banca: {ext.get('bank_name')} | IBAN: {ext.get('iban')}")
        print(f"      Sold Initial: {ext.get('initial_balance')} {ext.get('currency')} -> Sold Final: {ext.get('closing_balance')} {ext.get('currency')}")
        print(f"      Salariu virat detectat: {ext.get('detected_salary_deposit')} {ext.get('currency')}")
        for r in res.validation.rules_evaluated:
            tag = "[OK]" if r.passed else "[FAIL]"
            print(f"        {tag} [{r.code:18}] {r.description}")

    # Stage 4: Cross-document validation
    print_section("ETAPA 4: Verificare Incrucisata Dosar (Cross-Document)")
    from src.parsers.ocr.pdf_extractor import PdfExtractor
    if buletin_pdf:
        typed_id = IdCardExtractor.extract(PdfExtractor.extract_text(buletin_pdf.read_bytes()))
    if adeverinta_pdf:
        typed_inc = IncomeCertificateExtractor.extract(PdfExtractor.extract_text(adeverinta_pdf.read_bytes()))
    if extras_pdf:
        typed_stmt = BankStatementExtractor.extract(PdfExtractor.extract_text(extras_pdf.read_bytes()))

    cross_res = service.cross_validate_application(
        identity_doc=typed_id,
        income_doc=typed_inc,
        statement_doc=typed_stmt,
    )

    print(f"Statut Reconciliere Dosar: {'[CONCORDANTA TOTALA - VALID]' if cross_res.consistent else '[DISCREPANTE DETECTATE]'}")
    print(f"  * Nume reconciliat (CI vs Adeverinta vs Extras): {'[OK]' if cross_res.name_matched else '[DISCREPANTA]'}")
    print(f"  * CNP corelat (CI vs Adeverinta de Venit):       {'[OK]' if cross_res.cnp_matched else '[DISCREPANTA]'}")
    print(f"  * Salariu virat confirmat in extrasul bancar:    {'[OK]' if cross_res.salary_verified_in_statement else '[DISCREPANTA]'}")
    print(f"  * Necesita revizie manuala:                      {'DA' if cross_res.human_review_required else 'NU'}")

    if cross_res.reasons:
        print("\n  Detalii reconciliere:")
        for r in cross_res.reasons:
            print(f"    - {r}")


def list_customers() -> None:
    if not DOCS_DIR.exists():
        print(f"No documents folder at {DOCS_DIR}")
        return
    dirs = [d for d in DOCS_DIR.iterdir() if d.is_dir()]
    print("\nClienți sintetici disponibili pentru verificare manuală:")
    for d in dirs:
        pdfs = list(d.glob("*.pdf"))
        print(f"  - {d.name:40} ({len(pdfs)} fișiere PDF)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verificare manuală Pipeline Procesare & Validare Documente Bancare Românești"
    )
    parser.add_argument(
        "--customer",
        type=str,
        default=None,
        help="Numele folderului de client din data/synthetic/documents (ex: alex_morgan_demo_customer, dan_ionescu_dsti_39)",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Calea către un fișier PDF specific de verificat",
    )
    parser.add_argument(
        "--type",
        type=str,
        choices=["identity", "income", "statement"],
        default="identity",
        help="Tipul documentului dacă se folosește --file (identity, income, statement)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Afișează lista clienților sintetici disponibili",
    )

    args = parser.parse_args()

    if args.list:
        list_customers()
        return

    service = DocumentProcessingService()

    if args.file:
        kind = DocumentKind(args.type)
        verify_single_file(service, args.file, kind)
    else:
        # Default customer if none specified
        customer_name = args.customer or "alex_morgan_demo_customer"
        folder = DOCS_DIR / customer_name
        if not folder.exists():
            print(f"[EROARE] Nu s-a găsit folderul clientului: {folder}")
            list_customers()
            sys.exit(1)
        verify_customer_dossier(service, folder)


if __name__ == "__main__":
    main()
