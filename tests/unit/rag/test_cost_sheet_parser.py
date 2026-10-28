"""Tests for the cost sheet template parser."""
from src.models.knowledge import ChunkKind
from src.services.document_ingestion.parsers.cost_sheet import parse_cost_sheet
from tests.fixtures.rag.pdf_builders import build_demo_cost_sheet, make_pdf


def test_cost_sheet_variants_are_clean_rows():
    doc = parse_cost_sheet(build_demo_cost_sheet())
    facts = doc.chunks[0]
    assert facts.kind is ChunkKind.cost_facts and doc.parser_name == "cost_sheet"
    rows = [l for l in facts.text.splitlines() if l.startswith("Variantă:")]
    assert rows == [
        "Variantă: Demoflex Fara Asigurare, client standard | Monedă/tip dobândă: Lei Fixa | Sumă credit: Indiferent de suma | Rată dobândă: de la 6.10% la 15.20% | Comision analiză dosar: 150 lei | Comision administrare lunar: 4 lei | DAE: de la 9.80% la 21.40%",
        "Variantă: Demoflex Fara Asigurare, client premium | Monedă/tip dobândă: Lei Fixa | Sumă credit: Indiferent de suma | Rată dobândă: de la 5.90% la 15.00% | Comision analiză dosar: 150 lei | Comision administrare lunar: 4 lei | DAE: de la 9.50% la 21.10%",
    ]
    assert "Comision de plată anticipată: 0,50 % in ultimul an de contract / 1,00% inainte de inceperea ultimului an de contract" in facts.text


def test_cost_sheet_examples_chunk():
    ex = parse_cost_sheet(build_demo_cost_sheet()).chunks[1]
    assert ex.kind is ChunkKind.cost_examples and ex.text.startswith("Exemplu de calcul")


def test_cost_sheet_fallback_on_unknown_layout():
    doc = parse_cost_sheet(make_pdf([[(50, 60, "01.01.2026"), (50, 80, "Altceva complet diferit")]]))
    assert doc.parser_name == "cost_sheet_fallback" and doc.warnings and doc.chunks[0].kind is ChunkKind.generic


def test_cost_sheet_facts_title_and_order():
    doc = parse_cost_sheet(build_demo_cost_sheet())
    facts = doc.chunks[0]
    assert doc.title == "Demoflex Fara Asigurare"
    assert facts.section_path == ["Costuri complete", "Condiții și costuri"]
    lines = facts.text.splitlines()
    assert lines[:5] == [
        "Tip credit: Credit demo pentru nevoi personale",
        "Valuta: Lei",
        "Valoare: 1.000 Lei pana la 40.000 Lei",
        "Perioada maxima: 5 ani.",
        "Beneficii:",
    ]
    assert lines[5].endswith("aprobare demo rapidă") and lines[6].endswith("dobândă fixă demo pe toată perioada")
    assert lines[7] == "Costuri credit:"
    assert lines[8].startswith("Variantă:") and lines[9].startswith("Variantă:")
    assert lines[10:] == [
        "1Rata dobânzii demo este fixă pe toată perioada creditului.",
        "*Valorile DAE demo sunt calculate pentru suma maximă.",
        "Comision de plată anticipată: 0,50 % in ultimul an de contract / 1,00% inainte de inceperea ultimului an de contract",
    ]


def test_cost_sheet_examples_keep_prose_and_drop_side_table():
    ex = parse_cost_sheet(build_demo_cost_sheet()).chunks[1]
    assert ex.section_path == ["Costuri complete", "Exemple de calcul"]
    assert ex.text.splitlines() == [
        "Exemplu de calcul pentru oferta demo standard",
        "Pentru un credit demo de 40.000 Lei, acordat pe 5 ani, cu o",
        "rată fixă a dobânzii de 6.10%, rata lunară este 850,00 Lei",
        "și DAE 9,80%.",
    ]


def test_cost_sheet_fallback_when_last_column_has_no_percent():
    pdf = make_pdf([[
        (20, 40, "01.01.2026"),
        (190, 90, "Demoflex Demo"),
        (20, 210, "Tip produs"),
        (150, 210, "Moneda"),
        (210, 210, "Suma"),
        (270, 210, "Rata"),
        (330, 210, "Analiza"),
        (400, 210, "Administrare"),
        (490, 210, "DAE"),
        (20, 240, "Demoflex Unu"),
        (150, 240, "Lei"),
        (210, 240, "Oricare"),
        (270, 240, "6.10%"),
        (330, 240, "150 lei"),
        (400, 240, "4 lei"),
        (490, 240, "nespecificat"),
    ]])
    doc = parse_cost_sheet(pdf)
    assert doc.parser_name == "cost_sheet_fallback"
    assert doc.warnings[0].startswith("cost sheet template mismatch: ") and "%" in doc.warnings[0]
    assert [c.kind for c in doc.chunks] == [ChunkKind.generic] and "Demoflex Unu" in doc.chunks[0].text
