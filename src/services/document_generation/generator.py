"""Orchestrator for generating synthetic banking test documents.

Builds customer profiles from default demo personas or by querying
the local SQLite credit sources database, and renders PDFs/PNGs.
"""

from pathlib import Path
import sqlite3
from typing import Dict, List, Optional

from src.services.document_generation.bank_statement import generate_bank_statement
from src.services.document_generation.id_card import generate_identity_card
from src.services.document_generation.income_certificate import generate_income_certificate
from src.services.document_generation.models import (
    CustomerDocumentProfile,
    ExistingLoanInfo,
)


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = ROOT_DIR / "data" / "local" / "credit_sources.db"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "synthetic" / "documents"


# Standard pre-configured demo profiles
PRESET_PROFILES: Dict[str, CustomerDocumentProfile] = {
    "alex_morgan": CustomerDocumentProfile(
        customer_id="customer-alex",
        first_name="Alex",
        last_name="Morgan",
        cnp="1920515410012",
        birth_date="1992-05-15",
        gender="M",
        address="Strada Aviației nr. 42, Sector 1, București",
        phone="+40 721 123 456",
        email="alex@example.test",
        persona_tag="DEMO_CUSTOMER",
        id_series="RX",
        id_number="781920",
        id_issuer="SPCLEP Sector 1 București",
        id_issue_date="2022-06-10",
        id_expiry_date="2032-06-10",
        birth_place="Mun. București Sec. 1",
        employer_name="Northstar Studio S.R.L.",
        employer_cui="RO 38192043",
        employer_reg_com="J40/4912/2019",
        employer_address="Calea Victoriei nr. 120, București",
        job_title="Senior Product Designer",
        contract_type="Nedeterminată",
        employment_start_date="2021-04-01",
        monthly_net_income=8500.00,
        monthly_gross_income=14530.00,
        bank_name="RAIFFEISEN BANK S.A.",
        iban="RO41RZBR0000060081924012",
        initial_balance=12480.50,
        existing_loans=[
            ExistingLoanInfo(
                loan_type="Credit de Nevoi Personale",
                lender="Raiffeisen Bank",
                original_amount_ron=35000.00,
                current_balance_ron=24750.00,
                monthly_installment_ron=785.40,
                remaining_months=36,
            ),
            ExistingLoanInfo(
                loan_type="Credit Auto",
                lender="Raiffeisen Bank",
                original_amount_ron=20000.00,
                current_balance_ron=12800.00,
                monthly_installment_ron=452.10,
                remaining_months=24,
            ),
        ],
    ),
    "dsti_39": CustomerDocumentProfile(
        customer_id="1790420000031",
        first_name="Dan",
        last_name="Ionescu",
        cnp="1790420000031",
        birth_date="1979-04-20",
        gender="M",
        address="Strada Exemplului nr. 3, Sector 2, București",
        phone="+40 722 390 039",
        email="dan.ionescu@test.local",
        persona_tag="DSTI_39",
        id_series="DP",
        id_number="391204",
        id_issuer="SPCLEP Sector 2 București",
        id_issue_date="2021-05-10",
        id_expiry_date="2031-05-10",
        birth_place="Mun. București",
        employer_name="Tech Solutions S.R.L.",
        employer_cui="RO 29481026",
        employer_reg_com="J40/8192/2015",
        employer_address="B-dul Dimitrie Pompeiu nr. 8, București",
        job_title="Inginer Software Principal",
        contract_type="Nedeterminată",
        employment_start_date="2018-09-01",
        monthly_net_income=5996.25,
        monthly_gross_income=10250.00,
        bank_name="RAIFFEISEN BANK S.A.",
        iban="RO39RZBR0000060039391003",
        initial_balance=8940.00,
        existing_loans=[
            ExistingLoanInfo(
                loan_type="Credit Ipotecar Imobiliar",
                lender="Banca Parteneră",
                original_amount_ron=420000.00,
                current_balance_ron=380000.00,
                monthly_installment_ron=2340.00,
                remaining_months=240,
            )
        ],
    ),
    "income_no_debt": CustomerDocumentProfile(
        customer_id="2820327000020",
        first_name="Elena",
        last_name="Popa",
        cnp="2820327000020",
        birth_date="1982-03-27",
        gender="F",
        address="Strada Florilor nr. 15, Cluj-Napoca",
        phone="+40 723 100 020",
        email="elena.popa@test.local",
        persona_tag="INCOME_NO_DEBT",
        id_series="CJ",
        id_number="829104",
        id_issuer="SPCLEP Cluj-Napoca",
        id_issue_date="2020-04-12",
        id_expiry_date="2030-04-12",
        birth_place="Mun. Cluj-Napoca",
        employer_name="Retail Logistics S.A.",
        employer_cui="RO 14920190",
        employer_reg_com="J12/551/2010",
        employer_address="Calea Baciului nr. 45, Cluj-Napoca",
        job_title="Manager Operațiuni Logistice",
        contract_type="Nedeterminată",
        employment_start_date="2017-02-15",
        monthly_net_income=4500.00,
        monthly_gross_income=7690.00,
        bank_name="RAIFFEISEN BANK S.A.",
        iban="RO87RZBR0000060028204002",
        initial_balance=15300.00,
        existing_loans=[],
    ),
    "multi_source_multi_loan": CustomerDocumentProfile(
        customer_id="1890325000097",
        first_name="Radu",
        last_name="Mihai",
        cnp="1890325000097",
        birth_date="1989-03-25",
        gender="M",
        address="B-dul Republicii nr. 88, Timișoara",
        phone="+40 724 500 097",
        email="radu.mihai@test.local",
        persona_tag="MULTI_SOURCE_MULTI_LOAN",
        id_series="TM",
        id_number="481920",
        id_issuer="SPCLEP Timișoara",
        id_issue_date="2021-08-20",
        id_expiry_date="2031-08-20",
        birth_place="Mun. Timișoara",
        employer_name="Alpha Systems S.R.L.",
        employer_cui="RO 31204914",
        employer_reg_com="J35/910/2016",
        employer_address="B-dul Simion Bărnuțiu nr. 34, Timișoara",
        job_title="Consultant Financiar",
        contract_type="Nedeterminată",
        employment_start_date="2019-11-01",
        monthly_net_income=5000.00,
        monthly_gross_income=8550.00,
        bank_name="RAIFFEISEN BANK S.A.",
        iban="RO38RZBR0000060018905009",
        initial_balance=6200.00,
        existing_loans=[
            ExistingLoanInfo(
                loan_type="Card de Credit",
                lender="Banca Alfa",
                original_amount_ron=10000.00,
                current_balance_ron=4500.00,
                monthly_installment_ron=180.00,
                remaining_months=24,
            ),
            ExistingLoanInfo(
                loan_type="Descoperit de Cont",
                lender="Banca Beta",
                original_amount_ron=5000.00,
                current_balance_ron=2000.00,
                monthly_installment_ron=120.00,
                remaining_months=12,
            ),
        ],
    ),
    "no_history": CustomerDocumentProfile(
        customer_id="1831107000012",
        first_name="Andrei",
        last_name="Stan",
        cnp="1831107000012",
        birth_date="1983-11-07",
        gender="M",
        address="Strada Păcii nr. 4, Brașov",
        phone="+40 725 000 012",
        email="andrei.stan@test.local",
        persona_tag="NO_HISTORY",
        id_series="BV",
        id_number="183110",
        id_issuer="SPCLEP Brașov",
        id_issue_date="2023-01-15",
        id_expiry_date="2033-01-15",
        birth_place="Mun. Brașov",
        employer_name="Servicii Digitale S.R.L.",
        employer_cui="RO 40192835",
        employer_reg_com="J08/1102/2021",
        employer_address="Str. Iuliu Maniu nr. 22, Brașov",
        job_title="Asistent Administrativ",
        contract_type="Nedeterminată",
        employment_start_date="2023-03-01",
        monthly_net_income=3500.00,
        monthly_gross_income=5980.00,
        bank_name="RAIFFEISEN BANK S.A.",
        iban="RO92RZBR0000060018313501",
        initial_balance=4100.00,
        existing_loans=[],
    ),
}


def load_profile_from_db(
    identifier: str, db_path: Path = DEFAULT_DB_PATH
) -> Optional[CustomerDocumentProfile]:
    """Look up a customer in the credit sources database by CNP or persona_tag."""
    if not db_path.exists():
        return None

    try:
        with sqlite3.connect(db_path) as db:
            db.row_factory = sqlite3.Row
            # Search by persona_tag or cnp
            row = db.execute(
                "SELECT * FROM persons WHERE persona_tag = ? OR cnp = ?",
                (identifier, identifier),
            ).fetchone()

            if not row:
                return None

            cnp = row["cnp"]
            tag = row["persona_tag"] or "DB_PERSONA"
            first_name = row["first_name"]
            last_name = row["last_name"]
            birth_date = row["birth_date"]
            address = row["address"] or "Strada Exemplului nr. 1, Sector 1, București"
            gender = "F" if cnp.startswith("2") or cnp.startswith("6") else "M"

            # Check employment & employer
            emp_row = db.execute(
                "SELECT emp.*, e.fiscal_code, e.address as emp_addr FROM employments emp "
                "LEFT JOIN employers e ON e.name = emp.employer WHERE emp.cnp = ? LIMIT 1",
                (cnp,),
            ).fetchone()

            employer_name = emp_row["employer"] if emp_row else "Societate Comercială S.R.L."
            employer_cui = emp_row["fiscal_code"] if emp_row and emp_row["fiscal_code"] else "RO 29104921"
            employer_address = emp_row["emp_addr"] if emp_row and emp_row["emp_addr"] else "Str. Principală nr. 10, București"

            # Check income
            inc_row = db.execute(
                "SELECT net_amount_ron, gross_amount_ron FROM income_records WHERE cnp = ? ORDER BY fiscal_year DESC LIMIT 1",
                (cnp,),
            ).fetchone()

            if inc_row and inc_row["net_amount_ron"]:
                monthly_net = round(inc_row["net_amount_ron"] / 12.0, 2)
                monthly_gross = round((inc_row["gross_amount_ron"] or inc_row["net_amount_ron"] * 1.7) / 12.0, 2)
            else:
                monthly_net = 4000.00
                monthly_gross = 6840.00

            # Check loans
            loan_rows = db.execute(
                "SELECT cp.*, pp.role FROM credit_products cp "
                "JOIN product_participants pp ON pp.product_id = cp.id WHERE pp.cnp = ?",
                (cnp,),
            ).fetchall()

            loans: List[ExistingLoanInfo] = []
            for lr in loan_rows:
                loans.append(
                    ExistingLoanInfo(
                        loan_type=lr["product_type"] or "Credit de Nevoi Personale",
                        lender=lr["lender"] or "Bancă Parteneră",
                        original_amount_ron=float(lr["amount_granted_ron"] or lr["amount_granted"] or 20000.0),
                        current_balance_ron=float((lr["amount_granted_ron"] or 20000.0) * 0.6),
                        monthly_installment_ron=float(lr["monthly_payment_ron"] if "monthly_payment_ron" in lr.keys() else 500.0),
                        remaining_months=int(lr["term_months"] or 36),
                    )
                )

            return CustomerDocumentProfile(
                customer_id=cnp,
                first_name=first_name,
                last_name=last_name,
                cnp=cnp,
                birth_date=birth_date,
                gender=gender,
                address=address,
                persona_tag=tag,
                employer_name=employer_name,
                employer_cui=employer_cui,
                employer_address=employer_address,
                monthly_net_income=monthly_net,
                monthly_gross_income=monthly_gross,
                existing_loans=loans,
            )
    except Exception:
        return None


def generate_documents_for_profile(
    profile: CustomerDocumentProfile,
    output_dir: Path,
    include_pdf: bool = True,
    include_png: bool = False,
    mode: str = "all",
) -> Dict[str, Dict[str, Path]]:
    """Generate synthetic banking documents (ID Card, Income Certificate, Bank Statement) in scanned, photo, and diagonal modes."""
    cust_dir = output_dir / profile.slug
    cust_dir.mkdir(parents=True, exist_ok=True)

    results: Dict[str, Dict[str, Path]] = {}
    effective_mode = mode.lower() if mode else "all"

    # 1. Standard triad (scanned or chosen primary mode)
    primary_mode = "scanned" if effective_mode == "all" else effective_mode
    id_pdf = cust_dir / f"buletin_{profile.slug}.pdf" if include_pdf else None
    id_png = cust_dir / f"buletin_{profile.slug}.png" if include_png else None
    generate_identity_card(profile, output_pdf=id_pdf, output_png=id_png, mode=primary_mode)
    results["identity"] = {"pdf": id_pdf, "png": id_png}

    inc_pdf = cust_dir / f"adeverinta_venit_{profile.slug}.pdf" if include_pdf else None
    inc_png = cust_dir / f"adeverinta_venit_{profile.slug}.png" if include_png else None
    generate_income_certificate(profile, output_pdf=inc_pdf, output_png=inc_png, mode=primary_mode)
    results["income"] = {"pdf": inc_pdf, "png": inc_png}

    stmt_pdf = cust_dir / f"extras_cont_{profile.slug}.pdf" if include_pdf else None
    stmt_png = cust_dir / f"extras_cont_{profile.slug}.png" if include_png else None
    generate_bank_statement(profile, output_pdf=stmt_pdf, output_png=stmt_png, mode=primary_mode)
    results["statement"] = {"pdf": stmt_pdf, "png": stmt_png}

    # 2. When mode == "all", also generate dedicated photo and diagonal files for OCR testing
    if effective_mode == "all":
        # Straight photos on desk
        generate_identity_card(
            profile,
            output_pdf=cust_dir / "buletin_poza.pdf" if include_pdf else None,
            output_png=cust_dir / "buletin_poza.png" if include_png else None,
            mode="photo",
        )
        generate_income_certificate(
            profile,
            output_pdf=cust_dir / "adeverinta_poza.pdf" if include_pdf else None,
            output_png=cust_dir / "adeverinta_poza.png" if include_png else None,
            mode="photo",
        )
        generate_bank_statement(
            profile,
            output_pdf=cust_dir / "extras_poza.pdf" if include_pdf else None,
            output_png=cust_dir / "extras_poza.png" if include_png else None,
            mode="photo",
        )

        # Diagonal photos on desk (tilted camera angle)
        generate_identity_card(
            profile,
            output_pdf=cust_dir / "buletin_diagonala.pdf" if include_pdf else None,
            output_png=cust_dir / "buletin_diagonala.png" if include_png else None,
            mode="photo_diagonal",
        )
        generate_income_certificate(
            profile,
            output_pdf=cust_dir / "adeverinta_diagonala.pdf" if include_pdf else None,
            output_png=cust_dir / "adeverinta_diagonala.png" if include_png else None,
            mode="photo_diagonal",
        )
        generate_bank_statement(
            profile,
            output_pdf=cust_dir / "extras_diagonala.pdf" if include_pdf else None,
            output_png=cust_dir / "extras_diagonala.png" if include_png else None,
            mode="photo_diagonal",
        )

    return results


def generate_document_suite(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    profiles: Optional[List[CustomerDocumentProfile]] = None,
    include_pdf: bool = True,
    include_png: bool = False,
    mode: str = "all",
) -> List[Dict[str, any]]:
    """Generate the complete suite of synthetic documents (all in PDF) and create a manifest INDEX.md."""
    output_dir.mkdir(parents=True, exist_ok=True)

    if profiles is None:
        profiles = list(PRESET_PROFILES.values())

    manifest_entries = []

    for profile in profiles:
        doc_paths = generate_documents_for_profile(
            profile, output_dir, include_pdf=include_pdf, include_png=include_png, mode=mode
        )
        manifest_entries.append({"profile": profile, "documents": doc_paths})

    # Write summary INDEX.md
    index_md = output_dir / "INDEX.md"
    content = [
        "# Documente Sintetice Fictive pentru Testare Aplicație (Format PDF)",
        "",
        "Acest director conține dosarele complete de documente fictive în **format PDF** (A4) generate automat pentru clienții existenți.",
        "Toate documentele (buletin, adeverință de venit, extras de cont) sunt fișiere `.pdf` gata de încărcat direct în formularul de credit din aplicație (**Document Checklist**).",
        "",
        "## Clienți Disponibili & Documente PDF",
        "",
        "| Client | Scenariu / Tag | CNP Sintetic | Venit Net Lunar | Documente PDF |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]

    for entry in manifest_entries:
        p: CustomerDocumentProfile = entry["profile"]
        docs = entry["documents"]
        slug = p.slug

        id_links = []
        if docs["identity"].get("pdf"):
            id_links.append(f"📄 [Copie Buletin (PDF)]({slug}/{docs['identity']['pdf'].name})")
        if docs["income"].get("pdf"):
            id_links.append(f"📄 [Adeverință Venit (PDF)]({slug}/{docs['income']['pdf'].name})")
        if docs["statement"].get("pdf"):
            id_links.append(f"📄 [Extras Cont (PDF)]({slug}/{docs['statement']['pdf'].name})")

        content.append(
            f"| **{p.full_name}** | `{p.persona_tag}` | `{p.cnp}` | {p.monthly_net_income:,.2f} RON | {'<br>'.join(id_links)} |"
        )

    content.extend([
        "",
        "## Cum se folosesc în aplicație:",
        "1. Deschide aplicația client la `http://localhost:3000` (autentificare cu `alex@example.test` / `ClientDemo123!`).",
        "2. Mergi la secțiunea de solicitare credit sau aplicație existentă.",
        "3. În fereastra **Document Checklist**, apasă pe **Add Identity document**, **Add Proof of income** sau **Add Account statement**.",
        "4. Alege fișierul `.pdf` corespunzător din acest folder (ex: `alex_morgan_demo_customer/buletin_alex_morgan_demo_customer.pdf`).",
        "5. Salvează metadatele documentului.",
        "",
        "> [!NOTE]",
        "> Toate documentele sunt generate pe bază de date sintetice pentru testare și conțin marcaje explicite `SPECIMEN TEST DEMO`.",
    ])

    index_md.write_text("\n".join(content), encoding="utf-8")
    return manifest_entries
