from src.services.document_generation.desk_surface import render_on_desk
"""Romanian Bank Account Statement (Extras de Cont) generator.

Generates professional A4 synthetic account statements in PDF and PNG formats,
styled with Raiffeisen-inspired yellow/black accents and an embedded searchable text layer.
"""

import io
from pathlib import Path
from typing import List, Optional
from PIL import Image, ImageDraw, ImageFont
import pypdf

from src.services.document_generation.models import CustomerDocumentProfile, TransactionRow


def _load_font(name: str, size: int) -> ImageFont.ImageFont:
    for candidate in [name, "arial.ttf", "calibri.ttf", "DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _format_money(amount: float) -> str:
    return f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _build_transactions(profile: CustomerDocumentProfile) -> List[TransactionRow]:
    """Build a realistic 1-month ledger of banking transactions."""
    balance = profile.initial_balance
    rows: List[TransactionRow] = []

    # 1. Salary in (on the 5th)
    salary_in = profile.monthly_net_income
    if salary_in > 0:
        balance += salary_in
        rows.append(
            TransactionRow(
                date_str="05.10.2026",
                tx_type="VIRAMENT SALARIU",
                description=f"Plată drepturi salariale cf CIM · {profile.employer_name}",
                amount_ron=salary_in,
                balance_after_ron=balance,
            )
        )
    else:
        fee = -5.00 if balance >= 5.0 else -balance
        balance += fee
        rows.append(
            TransactionRow(
                date_str="05.10.2026",
                tx_type="COMISION BANCAR",
                description="Comision lunar administrare pachet cont curent",
                amount_ron=fee,
                balance_after_ron=balance,
            )
        )

    # 2. Existing loans deductions if any
    for loan in profile.existing_loans:
        amt = -abs(loan.monthly_installment_ron)
        balance += amt
        rows.append(
            TransactionRow(
                date_str="08.10.2026",
                tx_type="DEBITARE AUTOMATĂ",
                description=f"Rată lunară {loan.loan_type} · Contract {loan.lender}",
                amount_ron=amt,
                balance_after_ron=balance,
            )
        )

    # 3. Utilities & Services
    utilities = [
        ("10.10.2026", "PLATA FACTURA", "Furnizor Energie Electrica · Enel Energie", -235.40),
        ("12.10.2026", "PLATA FACTURA", "Abonament telefonie si internet · Digi Romania", -75.00),
        ("15.10.2026", "PLATA POS", "Supermarket Mega Image · Bucur Obor", -342.80),
        ("18.10.2026", "RETRAGERE ATM", "Retragere numerar bancomat · Agentia Aviatiei", -500.00),
        ("22.10.2026", "PLATA POS", "Statie alimentare combustibil · OMV Petrom", -280.50),
        ("25.10.2026", "PLATA POS", "Hipermarket Auchan · Shopping City", -415.20),
    ] if salary_in > 0 else [
        ("10.10.2026", "PLATA POS", "Magazin alimentar Mega Image", -25.50 if balance >= 25.50 else -balance),
    ]

    for d_str, t_type, desc, amt in utilities:
        if amt != 0.0:
            balance += amt
            rows.append(
                TransactionRow(
                    date_str=d_str,
                    tx_type=t_type,
                    description=desc,
                    amount_ron=amt,
                    balance_after_ron=balance,
                )
            )

    return rows


def _render_statement_sheet(profile: CustomerDocumentProfile) -> tuple[Image.Image, float, float, float]:
    """Render the physical A4 Extras de Cont sheet."""
    width, height = 1240, 1754  # A4 standard at ~150 DPI
    img = Image.new("RGB", (width, height), color="#FFFFFF")
    draw = ImageDraw.Draw(img)

    font_bank_name = _load_font("arialbd.ttf", 26)
    font_bold_lg = _load_font("arialbd.ttf", 22)
    font_bold_md = _load_font("arialbd.ttf", 15)
    font_bold_sm = _load_font("arialbd.ttf", 13)
    font_regular_md = _load_font("arial.ttf", 15)
    font_regular_sm = _load_font("arial.ttf", 12)
    font_mono_md = _load_font("arialbd.ttf", 15)

    # 1. Top Raiffeisen Brand Stripe (Yellow & Black)
    draw.rectangle([(0, 0), (width, 18)], fill="#FEE600")
    draw.rectangle([(0, 18), (width, 24)], fill="#0F172A")

    # 2. Bank Header
    curr_y = 50
    draw.rounded_rectangle([(70, curr_y), (120, curr_y + 50)], radius=8, fill="#FEE600", outline="#0F172A", width=2)
    draw.text((82, curr_y + 12), "RB", fill="#0F172A", font=_load_font("arialbd.ttf", 22))

    draw.text((135, curr_y + 4), profile.bank_name, fill="#0F172A", font=font_bank_name)
    draw.text((135, curr_y + 34), "Cod BIC: RZBRROBU  ·  C.I.F.: RO 361820  ·  Reg. Bancar: RB-PJR-40-009", fill="#64748B", font=font_regular_sm)

    draw.text((width - 380, curr_y + 8), "Serviciul Clienți: *2000", fill="#0F172A", font=font_bold_sm)
    draw.text((width - 380, curr_y + 30), "Website: www.raiffeisen.ro (demo)", fill="#64748B", font=font_regular_sm)

    curr_y += 75
    draw.line([(70, curr_y), (width - 70, curr_y)], fill="#E2E8F0", width=2)

    # 3. Title & Statement Header
    curr_y += 20
    draw.text((70, curr_y), "EXTRAS DE CONT CURENT", fill="#0F172A", font=font_bold_lg)
    draw.text((width - 380, curr_y + 4), "Perioada: 01.10.2026 - 28.10.2026", fill="#0F172A", font=font_bold_md)

    # 4. Account & Customer Metadata Panel (2 columns)
    curr_y += 40
    draw.rounded_rectangle([(70, curr_y), (width - 70, curr_y + 130)], radius=12, fill="#F8FAFC", outline="#E2E8F0", width=1)

    col1_x = 95
    draw.text((col1_x, curr_y + 15), "TITULAR CONT:", fill="#64748B", font=font_bold_sm)
    draw.text((col1_x, curr_y + 35), profile.full_name.upper(), fill="#0F172A", font=font_bold_md)
    draw.text((col1_x, curr_y + 60), f"CNP: {profile.cnp}  ·  Cod client: CLI-482910", fill="#475569", font=font_regular_sm)
    draw.text((col1_x, curr_y + 82), f"Adresă: {profile.address}", fill="#475569", font=font_regular_sm)
    draw.text((col1_x, curr_y + 104), f"Telefon: {profile.phone}", fill="#475569", font=font_regular_sm)

    col2_x = width // 2 + 30
    draw.text((col2_x, curr_y + 15), "DETALII CONT BANCAR:", fill="#64748B", font=font_bold_sm)
    draw.text((col2_x, curr_y + 35), "IBAN:", fill="#64748B", font=font_bold_sm)
    draw.text((col2_x + 55, curr_y + 33), profile.iban, fill="#0F172A", font=font_mono_md)
    draw.text((col2_x, curr_y + 60), f"Monedă cont: {profile.account_currency}  ·  Tip produs: Cont Curent Standard", fill="#475569", font=font_regular_sm)
    draw.text((col2_x, curr_y + 82), "Rata dobânzii: 0.00% p.a.  ·  Descoperit autorizat: 0.00 RON", fill="#475569", font=font_regular_sm)
    draw.text((col2_x, curr_y + 104), "Data emiterii extrasului: 28.10.2026", fill="#475569", font=font_regular_sm)

    # 5. Financial Summary Cards
    curr_y += 150
    transactions = _build_transactions(profile)

    total_credits = sum(tx.amount_ron for tx in transactions if tx.amount_ron > 0)
    total_debits = sum(abs(tx.amount_ron) for tx in transactions if tx.amount_ron < 0)
    final_balance = transactions[-1].balance_after_ron if transactions else profile.initial_balance

    card_w = (width - 140 - 3 * 18) // 4
    cards = [
        ("Sold inițial", f"{_format_money(profile.initial_balance)} RON", "#0F172A", "#F8FAFC"),
        ("Total încasări (+)", f"+{_format_money(total_credits)} RON", "#16A34A", "#F0FDF4"),
        ("Total plăți (-)", f"-{_format_money(total_debits)} RON", "#DC2626", "#FEF2F2"),
        ("Sold final disponibil", f"{_format_money(final_balance)} RON", "#002B7F", "#EFF6FF"),
    ]

    card_x = 70
    for label, val, text_color, bg_color in cards:
        draw.rounded_rectangle([(card_x, curr_y), (card_x + card_w, curr_y + 70)], radius=8, fill=bg_color, outline="#CBD5E1", width=1)
        draw.text((card_x + 14, curr_y + 12), label, fill="#64748B", font=font_bold_sm)
        draw.text((card_x + 14, curr_y + 36), val, fill=text_color, font=font_bold_md)
        card_x += card_w + 18

    # 6. Transactions Table
    curr_y += 90
    draw.text((70, curr_y), "LISTĂ TRANZACȚII ȘI OPERAȚIUNI:", fill="#0F172A", font=font_bold_md)
    curr_y += 28

    table_x = 70
    col_widths = [110, 180, 460, 170, 180]
    headers = ["Data", "Tip Operațiune", "Descriere & Detalii Partener", "Sumă (RON)", "Sold Contabil"]

    draw.rectangle([(table_x, curr_y), (table_x + sum(col_widths), curr_y + 34)], fill="#FEE600", outline="#0F172A", width=1)
    cx = table_x
    for i, h in enumerate(headers):
        draw.text((cx + 10, curr_y + 8), h, fill="#0F172A", font=font_bold_sm)
        cx += col_widths[i]

    curr_y += 34

    for idx, tx in enumerate(transactions):
        row_bg = "#F8FAFC" if idx % 2 == 1 else "#FFFFFF"
        row_h = 42
        draw.rectangle([(table_x, curr_y), (table_x + sum(col_widths), curr_y + row_h)], fill=row_bg, outline="#E2E8F0", width=1)

        amount_str = f"+{_format_money(tx.amount_ron)}" if tx.amount_ron > 0 else f"{_format_money(tx.amount_ron)}"
        amount_color = "#16A34A" if tx.amount_ron > 0 else "#0F172A"

        draw.text((table_x + 10, curr_y + 12), tx.date_str, fill="#475569", font=font_regular_sm)
        draw.text((table_x + col_widths[0] + 10, curr_y + 12), tx.tx_type, fill="#0F172A", font=font_bold_sm)
        draw.text((table_x + col_widths[0] + col_widths[1] + 10, curr_y + 12), tx.description, fill="#334155", font=font_regular_sm)
        draw.text((table_x + col_widths[0] + col_widths[1] + col_widths[2] + 10, curr_y + 12), f"{amount_str} lei", fill=amount_color, font=font_bold_sm)
        draw.text((table_x + sum(col_widths[:4]) + 10, curr_y + 12), f"{_format_money(tx.balance_after_ron)} lei", fill="#475569", font=font_regular_sm)

        curr_y += row_h

    # 7. Summary note under table
    curr_y += 25
    draw.text((70, curr_y), f"Număr total operațiuni înregistrate în perioada curentă: {len(transactions)}", fill="#64748B", font=font_regular_sm)
    curr_y += 20
    draw.text((70, curr_y), "Sumele sunt exprimate în moneda oficială a contului (RON). Dobânda este calculată zilnic și capitalizată lunar.", fill="#64748B", font=font_regular_sm)
    curr_y += 20
    total_obligations = sum(abs(l.monthly_installment_ron) for l in profile.existing_loans)
    draw.text((70, curr_y), f"Obligații lunare credite existente: {_format_money(total_obligations)} RON", fill="#475569", font=font_bold_sm)

    # 8. Disclaimer & Legal Footer
    curr_y = height - 100
    draw.line([(70, curr_y), (width - 70, curr_y)], fill="#CBD5E1", width=1)
    curr_y += 14
    draw.text((70, curr_y), "DOCUMENT EMIS ELECTRONIC · VALABIL FĂRĂ SEMNĂTURĂ SAU ȘTAMPILĂ CONFORM LEGII", fill="#0F172A", font=font_bold_sm)
    draw.text((70, curr_y + 20), "DOCUMENT SINTETIC DE TESTARE PENTRU PROTOTIPUL DE CREDITARE AGENTIC. CONȚINE DATE FICTIVE EXCLUSIV PENTRU DEMO.", fill="#94A3B8", font=_load_font("arial.ttf", 10))

    return img, total_credits, total_debits, final_balance


def generate_bank_statement(
    profile: CustomerDocumentProfile,
    output_pdf: Optional[Path] = None,
    output_png: Optional[Path] = None,
    mode: str = "scanned",
) -> Image.Image:
    """Generate a synthetic Romanian Extras de Cont in scanned, photo, or diagonal photo format."""
    sheet, total_credits, total_debits, final_balance = _render_statement_sheet(profile)
    mode_str = mode.value.lower() if hasattr(mode, "value") else str(mode or "scanned").lower()
    if hasattr(mode, "value"):
        mode_str = mode.value.lower()

    if "diag" in mode_str:
        final_image = render_on_desk(sheet, angle=10.0, padding=80, is_card=False, wood_tone=False)
    elif "photo" in mode_str or "poza" in mode_str:
        final_image = render_on_desk(sheet, angle=0.0, padding=80, is_card=False, wood_tone=False)
    else:
        final_image = sheet

    if output_png:
        output_png.parent.mkdir(parents=True, exist_ok=True)
        final_image.save(output_png, "PNG")

    if output_pdf:
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        buf = io.BytesIO()
        final_image.save(buf, "PDF", resolution=150.0)
        buf.seek(0)
        reader = pypdf.PdfReader(buf)
        writer = pypdf.PdfWriter()
        for p in reader.pages:
            writer.add_page(p)
        writer.add_metadata({
            "/Title": "Extras de Cont",
            "/Author": profile.bank_name,
        })
        with open(output_pdf, "wb") as f:
            writer.write(f)

    return final_image
