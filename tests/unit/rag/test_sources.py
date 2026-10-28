"""Tests for source configuration and classification."""
from pathlib import Path
from src.models.knowledge import DocKind, ChunkKind, Product, Topic
from src.services.document_ingestion.sources import (
    load_source_config,
    classify_document,
    classify_topic,
    products_for_url,
    is_allowed_url,
    fee_section_products,
)

D = "https://www.raiffeisen.ro/content/dam/rbi/retail/eu/ro/documents/"


def test_classify_document_and_topic():
    cfg = load_source_config(Path("config/rag/sources.yaml"))
    assert classify_document(D + "costuri/costuri-complete-flexicredit-standard/20261015-x.pdf", cfg) == (DocKind.cost_sheet, [Product.personal_loan])
    assert classify_document("https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/credite-de-nevoi-personale/intrebari-frecvente-credit-nevoi-personale.html", cfg)[0] is DocKind.faq_page
    assert classify_topic(DocKind.general_terms, ChunkKind.clause, ["3. Conditii", "3.4 Descoperit de cont"], "", cfg) is Topic.general_terms_credit
    assert classify_topic(DocKind.general_terms, ChunkKind.clause, ["5. Card", "5.1 Emiterea"], "", cfg) is Topic.cards
    assert classify_topic(DocKind.product_page, ChunkKind.section, ["Flexicredit", "Ce acte îți trebuie"], "act de identitate", cfg) is Topic.required_documents
    assert classify_topic(DocKind.cost_sheet, ChunkKind.cost_facts, [], "", cfg) is Topic.costs_fees


def test_hubs_and_link_allowlist():
    cfg = load_source_config(Path("config/rag/sources.yaml"))
    C = "https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/"
    assert classify_document(C + "credite-de-nevoi-personale.html", cfg)[0] is DocKind.category_hub
    assert classify_document(C + "credite-de-nevoi-personale/conditii-credit-nevoi-personale.html", cfg)[0] is DocKind.guide
    assert products_for_url(C + "overdraft.html", cfg) == [Product.overdraft]
    assert is_allowed_url(C + "overdraft.html#x", cfg)
    assert not is_allowed_url("https://raiffeisen.go.link/abc", cfg)
    assert not is_allowed_url("https://www.raiffeisen.ro/ro/contact/agentii.html", cfg)


def test_fee_list_sections_by_heading_keyword():
    cfg = load_source_config(Path("config/rag/sources.yaml"))
    cc = ["7. Taxe, comisioane și dobânzi aplicabile cardurilor de credit"]
    assert classify_topic(DocKind.fee_list, ChunkKind.fee_table, cc, "", cfg) is Topic.costs_fees
    assert fee_section_products(cc, cfg) == [Product.credit_card]
    assert classify_topic(DocKind.fee_list, ChunkKind.fee_table, ["1. Operațiuni de încasări*", "1.1. Încasare sume"], "", cfg) is Topic.payments
    assert classify_topic(DocKind.fee_list, ChunkKind.fee_table, ["1. Conturi curente, de economii și alte operațiuni bancare"], "", cfg) is Topic.accounts
    assert classify_topic(DocKind.fee_list, ChunkKind.fee_table, ["9. Ceva necunoscut"], "", cfg) is Topic.other


def test_product_rules_priority():
    cfg = load_source_config(Path("config/rag/sources.yaml"))
    # More specific rule should match first
    assert products_for_url("https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/refinantare-garantat-cu-ipoteca.html", cfg) == [Product.refinancing_mortgage]
    # Generic refinancing
    assert products_for_url("https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/refinantare-credit.html", cfg) == [Product.refinancing_unsecured]


def test_topic_keyword_rules():
    cfg = load_source_config(Path("config/rag/sources.yaml"))
    # Early repayment
    assert classify_topic(DocKind.faq_page, ChunkKind.faq, ["Pot rambursa anticipat?"], "Da, poți rambursa anticipat creditul", cfg) is Topic.early_repayment
    # Variable rate IRCC
    assert classify_topic(DocKind.product_page, ChunkKind.section, ["Dobândă"], "Dobanda variabilă IRCC + marja", cfg) is Topic.variable_rate_ircc
    # Eligibility
    assert classify_topic(DocKind.guide, ChunkKind.section, ["Condiții"], "Vârstă minimă 18 ani și venit minim 1500 lei", cfg) is Topic.eligibility


def test_default_topic_by_doc_kind():
    cfg = load_source_config(Path("config/rag/sources.yaml"))
    # Product page with no matching keywords should get credit_process
    assert classify_topic(DocKind.product_page, ChunkKind.section, ["Despre produs"], "text generic", cfg) is Topic.credit_process
