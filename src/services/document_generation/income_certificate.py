"""Romanian Salary & Income Certificate (Adeverință de Venit) generator.

Generates professional A4 synthetic income certificates in PDF and PNG formats,
with realistic employer headers, salary tables, stamps and disclaimers.
"""

from datetime import date
from pathlib import Path
from typing import List, Optional
from PIL import Image, ImageDraw, ImageFont

from src.services.document_generation.models import CustomerDocumentProfile, SalaryMonth


def _load_font(name: str, size: int) -> ImageFont.ImageFont:
    for candidate in [name, "arial.ttf", "calibri.ttf", "DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _format_money(amount: float) -> str:
    return f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _build_salary_months(net_amount: float) -> List[SalaryMonth]:
    """Calculate 6 months of breakdown matching the net monthly income."""
    # Approximate Romanian tax reverse calculation:
    # Gross = Net / 0.585 approx (or slightly rounded)
    gross = round(net_amount / 0.585, 2)
    cas = round(gross * 0.25, 2)
    cass = round(gross * 0.10, 2)
    taxable = max(0.0, gross - cas - cass - 300.0)  # deducere personala de baza
    tax = round(taxable * 0.10, 2)
    meal_tickets = 700.00  # 35 RON * 20 zile

    months = ["Mai", "Iunie", "Iulie", "August", "Septembrie", "Octombrie"]
    result = []
    for m in months:
        result.append(
            SalaryMonth(
                month_name=m,
                year=2026,
                gross_ron=gross,
                cas_ron=cas,
                cass_ron=cass,
                tax_ron=tax,
                meal_tickets_ron=meal_tickets,
                net_ron=net_amount,
            )
        )
    return result


def generate_income_certificate(
    profile: CustomerDocumentProfile,
    output_pdf: Optional[Path] = None,
    output_png: Optional[Path] = None,
) -> Image.Image:
    """Generate a synthetic Romanian Adeverință de Venit (A4 portrait)."""
    width, height = 1240, 1754  # A4 standard at ~150 DPI
    img = Image.new("RGB", (width, height), color="#FFFFFF")
    draw = ImageDraw.Draw(img)

    font_company = _load_font("arialbd.ttf", 26)
    font_bold_lg = _load_font("arialbd.ttf", 22)
    font_bold_md = _load_font("arialbd.ttf", 16)
    font_regular_md = _load_font("arial.ttf", 16)
    font_regular_sm = _load_font("arial.ttf", 13)
    font_table_hdr = _load_font("arialbd.ttf", 14)
    font_table_cell = _load_font("arial.ttf", 14)

    # 1. Subtle decorative margin border
    draw.rectangle([(30, 30), (width - 30, height - 30)], outline="#E2E8F0", width=1)

    # 2. Company Header (Top left) & Registration Info (Top right)
    curr_y = 60
    draw.text((70, curr_y), profile.employer_name.upper(), fill="#0F172A", font=font_company)
    curr_y += 34
    draw.text((70, curr_y), f"C.U.I. / C.I.F.: {profile.employer_cui}  ·  Nr. Reg. Com.: {profile.employer_reg_com}", fill="#475569", font=font_regular_sm)
    curr_y += 20
    draw.text((70, curr_y), f"Sediu social: {profile.employer_address}", fill="#475569", font=font_regular_sm)
    curr_y += 20
    draw.text((70, curr_y), "Email: contact@companie-fictiva.test  ·  Tel: +40 21 000 0000", fill="#475569", font=font_regular_sm)

    # Reg Number Box (Top right)
    draw.rounded_rectangle([(width - 380, 60), (width - 70, 140)], radius=8, fill="#F8FAFC", outline="#CBD5E1", width=1)
    draw.text((width - 360, 72), "Nr. Înregistrare:  418 / HR", fill="#0F172A", font=font_bold_md)
    draw.text((width - 360, 102), "Data emiterii:       28.10.2026", fill="#475569", font=font_regular_sm)

    # Separator line
    curr_y += 35
    draw.line([(70, curr_y), (width - 70, curr_y)], fill="#0F172A", width=3)
    draw.line([(70, curr_y + 4), (width - 70, curr_y + 4)], fill="#CBD5E1", width=1)

    # 3. Document Title
    curr_y += 45
    draw.text((width // 2 - 180, curr_y), "ADEVERINȚĂ DE VENIT", fill="#0F172A", font=font_bold_lg)
    curr_y += 32
    draw.text((width // 2 - 210, curr_y), "privind veniturile nete realizate în ultimele 6 luni", fill="#64748B", font=font_regular_md)

    # 4. Attestation Text
    curr_y += 50
    lines = [
        f"Prin prezenta se adeverește că dl./dna. {profile.full_name.upper()}, având CNP {profile.cnp},",
        f"domiciliat(ă) în {profile.address}, este angajat(ă) al societății",
        f"noastre în baza Contractului Individual de Muncă nr. 1042 / {profile.employment_start_date}, încheiat pe perioadă",
        f"NEDETERMINATĂ, ocupând în prezent funcția de {profile.job_title}.",
        "",
        "Menționăm că salariatul nu se află în perioadă de probă sau preaviz și nu înregistrează",
        "rețineri salariale, popriri din partea unor terți sau alte debite către societate.",
    ]

    for line in lines:
        if line:
            draw.text((70, curr_y), line, fill="#1E293B", font=font_regular_md)
        curr_y += 26

    # 5. Salary Table
    curr_y += 20
    draw.text((70, curr_y), "Situația veniturilor salariale lunare nete (ultimele 6 luni):", fill="#0F172A", font=font_bold_md)
    curr_y += 30

    table_x = 70
    col_widths = [160, 160, 140, 140, 130, 170, 200]
    headers = ["Luna / An", "Venit Brut", "CAS (25%)", "CASS (10%)", "Impozit", "Tichete Masă", "Venit Net Încasat"]

    # Table Header Row
    header_y = curr_y
    draw.rectangle([(table_x, header_y), (table_x + sum(col_widths), header_y + 36)], fill="#0F172A")
    cx = table_x
    for i, h in enumerate(headers):
        draw.text((cx + 10, header_y + 8), h, fill="#FFFFFF", font=font_table_hdr)
        cx += col_widths[i]

    curr_y += 36
    salary_rows = _build_salary_months(profile.monthly_net_income)

    total_net = 0.0
    for idx, s in enumerate(salary_rows):
        row_bg = "#F8FAFC" if idx % 2 == 1 else "#FFFFFF"
        draw.rectangle([(table_x, curr_y), (table_x + sum(col_widths), curr_y + 34)], fill=row_bg, outline="#E2E8F0", width=1)

        row_vals = [
            f"{s.month_name} {s.year}",
            f"{_format_money(s.gross_ron)} lei",
            f"{_format_money(s.cas_ron)} lei",
            f"{_format_money(s.cass_ron)} lei",
            f"{_format_money(s.tax_ron)} lei",
            f"{_format_money(s.meal_tickets_ron)} lei",
            f"{_format_money(s.net_ron)} lei",
        ]

        cx = table_x
        for j, val in enumerate(row_vals):
            fill_color = "#0F172A" if j == len(row_vals) - 1 else "#334155"
            font_use = font_bold_md if j == len(row_vals) - 1 else font_table_cell
            draw.text((cx + 10, curr_y + 8), val, fill=fill_color, font=font_use)
            cx += col_widths[j]

        total_net += s.net_ron
        curr_y += 34

    # Table Average / Total Footer
    avg_net = total_net / len(salary_rows)
    draw.rectangle([(table_x, curr_y), (table_x + sum(col_widths), curr_y + 40)], fill="#EEF2F6", outline="#CBD5E1", width=2)
    draw.text((table_x + 10, curr_y + 10), "MEDIA VENITULUI NET LUNAR:", fill="#0F172A", font=font_bold_md)
    draw.text((table_x + sum(col_widths) - 260, curr_y + 10), f"{_format_money(avg_net)} RON / lună", fill="#002B7F", font=font_bold_md)
    curr_y += 60

    # 6. Legal & Purpose Clause
    draw.text((70, curr_y), "Prezenta adeverință s-a eliberat la cererea salariatului pentru a-i servi la analiza", fill="#334155", font=font_regular_md)
    curr_y += 24
    draw.text((70, curr_y), "dosarului de creditare bancară și are o valabilitate de 30 de zile de la data emiterii.", fill="#334155", font=font_regular_md)

    # 7. Signature & Stamp Area
    curr_y += 70
    sig_left_x = 120
    sig_right_x = width - 420

    draw.text((sig_left_x, curr_y), "Director General / Administrator,", fill="#0F172A", font=font_bold_md)
    draw.text((sig_right_x, curr_y), "Departament Resurse Umane,", fill="#0F172A", font=font_bold_md)
    curr_y += 24
    draw.text((sig_left_x, curr_y), "Popescu Andrei", fill="#64748B", font=font_regular_sm)
    draw.text((sig_right_x, curr_y), "Ionescu Elena", fill="#64748B", font=font_regular_sm)

    # Stamp Mockup (Center bottom)
    stamp_center = (width // 2, curr_y + 60)
    draw.ellipse([(stamp_center[0] - 65, stamp_center[1] - 65), (stamp_center[0] + 65, stamp_center[1] + 65)], outline="#DC2626", width=3)
    draw.ellipse([(stamp_center[0] - 56, stamp_center[1] - 56), (stamp_center[0] + 56, stamp_center[1] + 56)], outline="#DC2626", width=1)
    draw.text((stamp_center[0] - 48, stamp_center[1] - 25), "SOCIETATE", fill="#DC2626", font=_load_font("arialbd.ttf", 10))
    draw.text((stamp_center[0] - 54, stamp_center[1] - 8), "COMERCIALĂ", fill="#DC2626", font=_load_font("arialbd.ttf", 10))
    draw.text((stamp_center[0] - 45, stamp_center[1] + 8), profile.employer_cui, fill="#DC2626", font=_load_font("arialbd.ttf", 9))
    draw.text((stamp_center[0] - 46, stamp_center[1] + 24), "ROMÂNIA", fill="#DC2626", font=_load_font("arialbd.ttf", 9))

    # Signature scribble effect
    draw.line([(sig_left_x, curr_y + 50), (sig_left_x + 60, curr_y + 40), (sig_left_x + 90, curr_y + 55), (sig_left_x + 150, curr_y + 45)], fill="#002B7F", width=2)
    draw.line([(sig_right_x, curr_y + 50), (sig_right_x + 50, curr_y + 42), (sig_right_x + 110, curr_y + 52), (sig_right_x + 160, curr_y + 46)], fill="#002B7F", width=2)

    # 8. Disclaimer Footer
    curr_y = height - 80
    draw.line([(70, curr_y), (width - 70, curr_y)], fill="#E2E8F0", width=1)
    curr_y += 12
    draw.text((70, curr_y), "DOCUMENT SINTETIC DE TESTARE · DATE FICTIVE PENTRU SIMULAREA PROCESULUI DE CREDITARE AGENTIC", fill="#94A3B8", font=_load_font("arialbd.ttf", 10))
    draw.text((70, curr_y + 16), "Nu reprezintă o adeverință fiscală reală și nu angajează răspunderea niciunei entități juridice existente.", fill="#94A3B8", font=_load_font("arial.ttf", 10))

    if output_png:
        output_png.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_png, "PNG")

    if output_pdf:
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_pdf, "PDF", resolution=150.0)

    return img
