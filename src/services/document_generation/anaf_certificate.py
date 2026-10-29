"""Romanian ANAF Income Certificate (Adeverință de Venit ANAF) generator.

Generates official A4 synthetic tax authority certificates in PDF and PNG formats,
with realistic ANAF headers, fiscal income tables, stamps, seals and embedded text.
"""

from datetime import date
import io
from pathlib import Path
from typing import List, Optional
from PIL import Image, ImageDraw, ImageFont
import pypdf

from src.services.document_generation.desk_surface import render_on_desk
from src.services.document_generation.models import CustomerDocumentProfile


def _load_font(name: str, size: int) -> ImageFont.ImageFont:
    for candidate in [name, "arial.ttf", "calibri.ttf", "DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _format_money(amount: float) -> str:
    return f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _render_anaf_sheet(profile: CustomerDocumentProfile) -> tuple[Image.Image, float]:
    """Render the official A4 ANAF Adeverință de Venit sheet."""
    width, height = 1240, 1754  # A4 standard at ~150 DPI
    img = Image.new("RGB", (width, height), color="#FFFFFF")
    draw = ImageDraw.Draw(img)

    font_header_lg = _load_font("arialbd.ttf", 22)
    font_header_md = _load_font("arialbd.ttf", 15)
    font_header_sm = _load_font("arial.ttf", 13)
    font_title_lg = _load_font("arialbd.ttf", 24)
    font_title_sub = _load_font("arial.ttf", 15)
    font_body_bold = _load_font("arialbd.ttf", 15)
    font_body = _load_font("arial.ttf", 15)
    font_table_hdr = _load_font("arialbd.ttf", 13)
    font_table_cell = _load_font("arial.ttf", 13)
    font_table_bold = _load_font("arialbd.ttf", 14)

    # 1. Outer decorative border
    draw.rectangle([(30, 30), (width - 30, height - 30)], outline="#CBD5E1", width=1)
    draw.rectangle([(36, 36), (width - 36, height - 36)], outline="#E2E8F0", width=1)

    # 2. Tricolor Top Bar
    band_y = 45
    band_h = 6
    third = (width - 140) // 3
    draw.rectangle([(70, band_y), (70 + third, band_y + band_h)], fill="#002B7F")
    draw.rectangle([(70 + third, band_y), (70 + 2 * third, band_y + band_h)], fill="#FCD116")
    draw.rectangle([(70 + 2 * third, band_y), (width - 70, band_y + band_h)], fill="#CE1126")

    # 3. ANAF Authority Header
    curr_y = 65
    draw.text((70, curr_y), "MINISTERUL FINANȚELOR", fill="#0F172A", font=font_header_lg)
    curr_y += 28
    draw.text((70, curr_y), "AGENȚIA NAȚIONALĂ DE ADMINISTRARE FISCALĂ", fill="#1E3A8A", font=font_header_md)
    curr_y += 22
    draw.text((70, curr_y), "Direcția Generală Regională a Finanțelor Publice București", fill="#334155", font=font_header_sm)
    curr_y += 18
    draw.text((70, curr_y), "C.U.I. / C.I.F.: 8609468  ·  Sediu: Str. Dimitrie Gerota nr. 13, Sector 2, București", fill="#475569", font=font_header_sm)

    # Registration Box (Top right)
    draw.rounded_rectangle([(width - 390, 65), (width - 70, 145)], radius=8, fill="#F8FAFC", outline="#94A3B8", width=1)
    draw.text((width - 370, 77), "Nr. Înregistrare: A-VEN/8419", fill="#0F172A", font=font_header_md)
    draw.text((width - 370, 107), "Data emiterii: 28.10.2026", fill="#334155", font=font_header_sm)

    # Header Separator
    curr_y += 35
    draw.line([(70, curr_y), (width - 70, curr_y)], fill="#002B7F", width=2)
    draw.line([(70, curr_y + 3), (width - 70, curr_y + 3)], fill="#CBD5E1", width=1)

    # 4. Title
    curr_y += 45
    draw.text((width // 2 - 160, curr_y), "ADEVERINȚĂ DE VENIT", fill="#0F172A", font=font_title_lg)
    curr_y += 34
    draw.text((width // 2 - 220, curr_y), "privind veniturile realizate supuse impozitului pe venit", fill="#64748B", font=font_title_sub)

    # 5. Contribuabil Identification Section
    curr_y += 50
    draw.text((70, curr_y), "I. IDENTIFICARE CONTRIBUABIL", fill="#002B7F", font=font_body_bold)
    curr_y += 26

    intro_lines = [
        f"Ca urmare a solicitării înregistrate și a verificării evidențelor fiscale din sistemul informatic ANAF,",
        f"se certifică faptul că dl./dna. {profile.full_name.upper()},",
        f"având Codul Numeric Personal (CNP): {profile.cnp}, domiciliat(ă) în {profile.address},",
        f"este înregistrat(ă) în baza de date fiscală cu Contract Individual de Muncă pe perioadă NEDETERMINATĂ",
        f"și figurează cu următoarea situație a veniturilor declarate conform Formularului D112:",
    ]
    for line in intro_lines:
        draw.text((70, curr_y), line, fill="#1E293B", font=font_body)
        curr_y += 24

    # 6. Fiscal Table
    curr_y += 25
    draw.text((70, curr_y), "II. SITUAȚIA VENITURILOR IMPOZABILE ÎNREGISTRATE (D112 / FIȘĂ FISCALĂ):", fill="#002B7F", font=font_body_bold)
    curr_y += 30

    table_x = 70
    col_widths = [130, 200, 260, 150, 160, 200]
    headers = ["An Fiscal", "Categorie Venit", "Plătitor / Angajator", "Venit Brut", "Impozit", "Venit Net Realizat"]

    header_y = curr_y
    draw.rectangle([(table_x, header_y), (table_x + sum(col_widths), header_y + 36)], fill="#002B7F")
    cx = table_x
    for i, h in enumerate(headers):
        draw.text((cx + 10, header_y + 8), h, fill="#FFFFFF", font=font_table_hdr)
        cx += col_widths[i]

    curr_y += 36

    is_zero = profile.monthly_net_income <= 0
    if is_zero:
        rows_data = [
            ("2025", "Venituri din salarii", "FĂRĂ ACTIVITATE DECLARATĂ", "0,00 lei", "0,00 lei", "0,00 lei"),
            ("2026 (Sem. I)", "Venituri din salarii", "FĂRĂ ACTIVITATE DECLARATĂ", "0,00 lei", "0,00 lei", "0,00 lei"),
            ("2026 (Trim. III)", "Venituri din salarii", "FĂRĂ ACTIVITATE DECLARATĂ", "0,00 lei", "0,00 lei", "0,00 lei"),
        ]
        avg_net = 0.0
    else:
        annual_net = profile.monthly_net_income * 12.0
        annual_gross = profile.monthly_gross_income * 12.0
        tax = round((annual_gross - annual_net) * 0.18, 2)
        sem_net = round(annual_net / 2.0, 2)
        sem_gross = round(annual_gross / 2.0, 2)
        sem_tax = round(tax / 2.0, 2)
        trim_net = round(annual_net / 4.0, 2)
        trim_gross = round(annual_gross / 4.0, 2)
        trim_tax = round(tax / 4.0, 2)

        emp_label = f"{profile.employer_name} ({profile.employer_cui})"
        rows_data = [
            ("2025", "Venituri din salarii", emp_label, f"{_format_money(annual_gross)} lei", f"{_format_money(tax)} lei", f"{_format_money(annual_net)} lei"),
            ("2026 (Sem. I)", "Venituri din salarii", emp_label, f"{_format_money(sem_gross)} lei", f"{_format_money(sem_tax)} lei", f"{_format_money(sem_net)} lei"),
            ("2026 (Trim. III)", "Venituri din salarii", emp_label, f"{_format_money(trim_gross)} lei", f"{_format_money(trim_tax)} lei", f"{_format_money(trim_net)} lei"),
        ]
        avg_net = profile.monthly_net_income

    for idx, rvals in enumerate(rows_data):
        row_bg = "#F8FAFC" if idx % 2 == 1 else "#FFFFFF"
        draw.rectangle([(table_x, curr_y), (table_x + sum(col_widths), curr_y + 34)], fill=row_bg, outline="#E2E8F0", width=1)
        cx = table_x
        for j, val in enumerate(rvals):
            fill_color = "#002B7F" if j == len(rvals) - 1 else "#1E293B"
            font_use = font_table_bold if j == len(rvals) - 1 else font_table_cell
            draw.text((cx + 10, curr_y + 8), val, fill=fill_color, font=font_use)
            cx += col_widths[j]
        curr_y += 34

    # Average Net Income Bar
    draw.rectangle([(table_x, curr_y), (table_x + sum(col_widths), curr_y + 40)], fill="#EEF2F6", outline="#CBD5E1", width=2)
    draw.text((table_x + 10, curr_y + 10), "MEDIA VENITULUI NET LUNAR:", fill="#0F172A", font=font_body_bold)
    draw.text((table_x + sum(col_widths) - 280, curr_y + 10), f"{_format_money(avg_net)} RON / lună", fill="#002B7F", font=font_title_lg)
    curr_y += 60

    # 7. Official Assessment Note
    draw.text((70, curr_y), "III. MENȚIUNI ȘI CONCLUZII FISCALE:", fill="#002B7F", font=font_body_bold)
    curr_y += 24
    if is_zero:
        notes = [
            "Contribuabilul nu figurează în evidențele fiscale cu venituri salariale realizate în perioada de referință.",
            "Venitul lunar mediu calculat conform bazei de date ANAF este de 0,00 RON.",
            "Declarațiile 112 transmise de plătitori nu cuprind sume impozabile sau contribuții achitate pe numele acestui CNP.",
        ]
    else:
        notes = [
            "Contribuabilul figurează cu venituri salariale declarate și achitate la zi conform Declarației 112.",
            f"Venitul net lunar de {_format_money(avg_net)} RON este stabil și provine din contract de muncă activ.",
            "Impozitul pe venit și contribuțiile sociale obligatorii au fost reținute la sursă de către angajator.",
        ]
    for n in notes:
        draw.text((70, curr_y), f"• {n}", fill="#334155", font=font_body)
        curr_y += 22

    curr_y += 20
    draw.text((70, curr_y), "Prezenta adeverință s-a eliberat pentru a servi la: Analiza dosarului de creditare bancară.", fill="#0F172A", font=font_body_bold)
    curr_y += 22
    draw.text((70, curr_y), "Valabilitate: 30 de zile de la data emiterii conform reglementărilor legale în vigoare.", fill="#64748B", font=font_header_sm)

    # 8. Signature & Stamp Area
    curr_y += 60
    sig_left_x = 120
    sig_right_x = width - 440

    draw.text((sig_left_x, curr_y), "Șef Serviciu Evidență Contribuabili,", fill="#0F172A", font=font_body_bold)
    draw.text((sig_right_x, curr_y), "Inspector Fiscal Verificator,", fill="#0F172A", font=font_body_bold)
    curr_y += 24
    draw.text((sig_left_x, curr_y), "Dumitrescu Elena", fill="#64748B", font=font_header_sm)
    draw.text((sig_right_x, curr_y), "Ionescu Mihai", fill="#64748B", font=font_header_sm)

    # Official ANAF Round Stamp (in center)
    stamp_center = (width // 2, curr_y + 50)
    draw.ellipse([(stamp_center[0] - 68, stamp_center[1] - 68), (stamp_center[0] + 68, stamp_center[1] + 68)], outline="#1E3A8A", width=3)
    draw.ellipse([(stamp_center[0] - 58, stamp_center[1] - 58), (stamp_center[0] + 58, stamp_center[1] + 58)], outline="#1E3A8A", width=1)
    draw.text((stamp_center[0] - 52, stamp_center[1] - 28), "AGENȚIA NAȚIONALĂ", fill="#1E3A8A", font=_load_font("arialbd.ttf", 9))
    draw.text((stamp_center[0] - 46, stamp_center[1] - 12), "ADMINISTRARE", fill="#1E3A8A", font=_load_font("arialbd.ttf", 9))
    draw.text((stamp_center[0] - 34, stamp_center[1] + 4), "FISCALĂ", fill="#1E3A8A", font=_load_font("arialbd.ttf", 9))
    draw.text((stamp_center[0] - 38, stamp_center[1] + 20), "CUI 8609468", fill="#1E3A8A", font=_load_font("arialbd.ttf", 9))

    draw.line([(sig_left_x, curr_y + 45), (sig_left_x + 70, curr_y + 35), (sig_left_x + 110, curr_y + 50), (sig_left_x + 160, curr_y + 40)], fill="#002B7F", width=2)
    draw.line([(sig_right_x, curr_y + 45), (sig_right_x + 60, curr_y + 38), (sig_right_x + 100, curr_y + 52), (sig_right_x + 150, curr_y + 42)], fill="#002B7F", width=2)

    # 9. Disclaimer Footer
    curr_y = height - 80
    draw.line([(70, curr_y), (width - 70, curr_y)], fill="#E2E8F0", width=1)
    curr_y += 12
    draw.text((70, curr_y), "DOCUMENT SINTETIC DE TESTARE · DATE FICTIVE PENTRU EVALUAREA ELIGIBILITĂȚII DE CREDITARE", fill="#94A3B8", font=_load_font("arialbd.ttf", 10))
    draw.text((70, curr_y + 16), "Nu reprezintă o adeverință fiscală reală și nu angajează răspunderea niciunei autorități publice existente.", fill="#94A3B8", font=_load_font("arial.ttf", 10))

    return img, avg_net


def generate_anaf_certificate(
    profile: CustomerDocumentProfile,
    output_pdf: Optional[Path] = None,
    output_png: Optional[Path] = None,
    mode: str = "scanned",
) -> Image.Image:
    """Generate a synthetic Romanian ANAF Adeverință de Venit in scanned or photo format."""
    sheet, avg_net = _render_anaf_sheet(profile)
    mode_str = str(mode or "scanned").lower()

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
            "/Title": "Adeverință de Venit ANAF",
            "/Author": "Agenția Națională de Administrare Fiscală",
            "/Subject": f"Venit lunar mediu: {_format_money(avg_net)} RON. CNP: {profile.cnp}. CUI: 8609468",
        })
        with open(output_pdf, "wb") as f:
            writer.write(f)

    return final_image
