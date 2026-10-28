"""Generate complete eligibility test suites with zero-income and eligible documents."""

import sys
sys.path.insert(0, ".")
from pathlib import Path

from src.services.document_generation.generator import PRESET_PROFILES
from src.services.document_generation.anaf_certificate import generate_anaf_certificate
from src.services.document_generation.income_certificate import generate_income_certificate
from src.services.document_generation.id_card import generate_identity_card
from src.services.document_generation.bank_statement import generate_bank_statement

def generate_all_samples():
    root = Path("data/test_samples_eligibility")
    root.mkdir(parents=True, exist_ok=True)

    # 1. Zero Income (Victor Nistor)
    dir_zero = root / "01_RESPINS_Venit_Zero"
    dir_zero.mkdir(parents=True, exist_ok=True)
    victor = PRESET_PROFILES["victor_nistor_zero_income"]

    generate_anaf_certificate(
        victor,
        output_pdf=dir_zero / "adeverinta_anaf_zero_venit.pdf",
        output_png=dir_zero / "adeverinta_anaf_zero_venit.png",
    )
    generate_income_certificate(
        victor,
        output_pdf=dir_zero / "adeverinta_venit_zero_venituri.pdf",
        output_png=dir_zero / "adeverinta_venit_zero_venituri.png",
    )
    generate_identity_card(
        victor,
        output_pdf=dir_zero / "buletin_victor_nistor.pdf",
        output_png=dir_zero / "buletin_victor_nistor.png",
    )
    generate_bank_statement(
        victor,
        output_pdf=dir_zero / "extras_cont_zero_incasari.pdf",
        output_png=dir_zero / "extras_cont_zero_incasari.png",
    )
    print("[OK] Set 1 (Venit Zero - Respins) generat cu succes.")

    # 2. OK Income (Alex Morgan)
    dir_ok = root / "02_ELIGIBIL_Venit_Optim"
    dir_ok.mkdir(parents=True, exist_ok=True)
    alex = PRESET_PROFILES["alex_morgan"]

    generate_anaf_certificate(
        alex,
        output_pdf=dir_ok / "adeverinta_anaf_venit_ok.pdf",
        output_png=dir_ok / "adeverinta_anaf_venit_ok.png",
    )
    generate_income_certificate(
        alex,
        output_pdf=dir_ok / "adeverinta_venit_ok_8500_ron.pdf",
        output_png=dir_ok / "adeverinta_venit_ok_8500_ron.png",
    )
    generate_identity_card(
        alex,
        output_pdf=dir_ok / "buletin_alex_morgan.pdf",
        output_png=dir_ok / "buletin_alex_morgan.png",
    )
    generate_bank_statement(
        alex,
        output_pdf=dir_ok / "extras_cont_alex_morgan.pdf",
        output_png=dir_ok / "extras_cont_alex_morgan.png",
    )
    print("[OK] Set 2 (Venit Optim - Eligibil) generat cu succes.")

    # 3. Sub-minimum Wage (Maria Popescu)
    dir_low = root / "03_RESPINS_Venit_Sub_Minim"
    dir_low.mkdir(parents=True, exist_ok=True)
    maria = PRESET_PROFILES["maria_popescu_low_income"]

    generate_income_certificate(
        maria,
        output_pdf=dir_low / "adeverinta_venit_sub_minim_1500_ron.pdf",
        output_png=dir_low / "adeverinta_venit_sub_minim_1500_ron.png",
    )
    generate_identity_card(
        maria,
        output_pdf=dir_low / "buletin_maria_popescu.pdf",
        output_png=dir_low / "buletin_maria_popescu.png",
    )
    print("[OK] Set 3 (Venit Sub Minim Legal - Respins) generat cu succes.")

    # Also generate in data/synthetic/documents for standard library integration
    docs_dir = Path("data/synthetic/documents")
    v_doc_dir = docs_dir / "victor_nistor_zero_income"
    v_doc_dir.mkdir(parents=True, exist_ok=True)
    generate_anaf_certificate(victor, output_pdf=v_doc_dir / "adeverinta_anaf_victor_nistor_zero_income.pdf")
    generate_income_certificate(victor, output_pdf=v_doc_dir / "adeverinta_venit_victor_nistor_zero_income.pdf")
    generate_identity_card(victor, output_pdf=v_doc_dir / "buletin_victor_nistor_zero_income.pdf")
    generate_bank_statement(victor, output_pdf=v_doc_dir / "extras_cont_victor_nistor_zero_income.pdf")

if __name__ == "__main__":
    generate_all_samples()
