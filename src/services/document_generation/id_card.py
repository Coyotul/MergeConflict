"""Romanian Identity Card (Buletin / Carte de Identitate) generator.

Generates high-resolution synthetic identity documents in standard A4 PDF format,
styled as a scanned copy of a Romanian ID-1 identity card with official conformity notes
and an embedded searchable text layer.
"""

import io
from pathlib import Path
from typing import Optional
from PIL import Image, ImageDraw, ImageFont
import pypdf

from src.services.document_generation.models import CustomerDocumentProfile


def _load_font(name: str, size: int) -> ImageFont.ImageFont:
    for candidate in [name, "arial.ttf", "calibri.ttf", "DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _load_mono_font(size: int) -> ImageFont.ImageFont:
    for candidate in ["consola.ttf", "cour.ttf", "Courier New.ttf", "DejaVuSansMono.ttf"]:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _render_id_card_surface(profile: CustomerDocumentProfile) -> Image.Image:
    """Render the physical ID-1 Romanian Identity Card surface."""
    width, height = 1100, 700
    card = Image.new("RGB", (width, height), color="#F4F8FA")
    draw = ImageDraw.Draw(card)

    # 1. Subtle background guilloche & card border
    draw.rounded_rectangle([(8, 8), (width - 8, height - 8)], radius=24, fill="#F8FAFC", outline="#CBD5E1", width=2)
    draw.rounded_rectangle([(14, 14), (width - 14, height - 14)], radius=20, outline="#E2E8F0", width=1)

    # 2. Tricolor band header (Blue, Yellow, Red)
    band_y = 20
    band_h = 10
    third = (width - 40) // 3
    draw.rectangle([(20, band_y), (20 + third, band_y + band_h)], fill="#002B7F")  # Albastru
    draw.rectangle([(20 + third, band_y), (20 + 2 * third, band_y + band_h)], fill="#FCD116")  # Galben
    draw.rectangle([(20 + 2 * third, band_y), (width - 20, band_y + band_h)], fill="#CE1126")  # Roșu

    # 3. Header Texts
    font_country = _load_font("arialbd.ttf", 30)
    font_title = _load_font("arialbd.ttf", 18)
    font_subtitle = _load_font("arial.ttf", 13)
    font_series = _load_font("arialbd.ttf", 20)

    draw.text((45, 42), "ROMÂNIA", fill="#0F172A", font=font_country)
    draw.text((45, 82), "CARTE DE IDENTITATE  ·  IDENTITY CARD  ·  CARTE D'IDENTITÉ", fill="#1E293B", font=font_title)
    draw.text((45, 106), "UNIUNEA EUROPEANĂ  /  MINISTERUL AFACERILOR INTERNE", fill="#64748B", font=font_subtitle)

    # Series & Number Badge (top right)
    draw.rounded_rectangle([(width - 340, 42), (width - 30, 98)], radius=10, fill="#EEF2F6", outline="#94A3B8", width=1)
    draw.text((width - 325, 48), "SERIA", fill="#64748B", font=font_subtitle)
    draw.text((width - 275, 46), profile.id_series, fill="#0F172A", font=font_series)
    draw.text((width - 225, 48), "NR.", fill="#64748B", font=font_subtitle)
    draw.text((width - 190, 46), profile.id_number, fill="#0F172A", font=font_series)
    draw.text((width - 325, 75), "SPECIMEN SINTETIC DEMO", fill="#DC2626", font=_load_font("arialbd.ttf", 10))

    # Decorative separator line
    draw.line([(24, 128), (width - 24, 128)], fill="#CBD5E1", width=2)

    # 4. Photo Portrait Placeholder (Left side)
    photo_box = [(35, 145), (255, 435)]
    draw.rounded_rectangle(photo_box, radius=14, fill="#E2E8F0", outline="#94A3B8", width=2)

    # Silhouette avatar inside photo box
    center_x = (photo_box[0][0] + photo_box[1][0]) // 2
    draw.ellipse([(center_x - 40, 210), (center_x + 40, 290)], fill="#94A3B8")
    draw.chord([(center_x - 75, 300), (center_x + 75, 440)], start=180, end=0, fill="#94A3B8")

    # Watermark overlay on photo
    draw.rectangle([(37, 385), (253, 415)], fill="#FEF2F2")
    draw.text((50, 394), "SPECIMEN DEMO", fill="#DC2626", font=_load_font("arialbd.ttf", 13))

    # 5. Field Labels & Values (Right side)
    font_lbl = _load_font("arial.ttf", 12)
    font_val = _load_font("arialbd.ttf", 16)
    font_cnp = _load_font("arialbd.ttf", 22)

    fields_start_x = 285
    curr_y = 142

    # CNP row
    draw.text((fields_start_x, curr_y), "C.N.P.  /  Personal Numerical Code", fill="#64748B", font=font_lbl)
    curr_y += 16
    draw.text((fields_start_x, curr_y), profile.cnp, fill="#0F172A", font=font_cnp)
    curr_y += 30

    # Nume / Last Name
    draw.text((fields_start_x, curr_y), "Nume  /  Nom  /  Last name", fill="#64748B", font=font_lbl)
    curr_y += 16
    draw.text((fields_start_x, curr_y), profile.last_name.upper(), fill="#0F172A", font=font_val)
    curr_y += 28

    # Prenume / First Name
    draw.text((fields_start_x, curr_y), "Prenume  /  Prénom  /  First name", fill="#64748B", font=font_lbl)
    curr_y += 16
    draw.text((fields_start_x, curr_y), profile.first_name.upper(), fill="#0F172A", font=font_val)
    curr_y += 28

    # Cetatenie / Sex
    draw.text((fields_start_x, curr_y), "Cetățenie  /  Nationalité", fill="#64748B", font=font_lbl)
    draw.text((fields_start_x + 320, curr_y), "Sex  /  Sexe", fill="#64748B", font=font_lbl)
    curr_y += 16
    draw.text((fields_start_x, curr_y), profile.citizenship, fill="#0F172A", font=font_val)
    draw.text((fields_start_x + 320, curr_y), profile.gender, fill="#0F172A", font=font_val)
    curr_y += 28

    # Loc Nastere
    draw.text((fields_start_x, curr_y), "Loc naștere  /  Place of birth", fill="#64748B", font=font_lbl)
    curr_y += 16
    draw.text((fields_start_x, curr_y), profile.birth_place, fill="#0F172A", font=font_val)
    curr_y += 28

    # Domiciliu / Adresa
    draw.text((fields_start_x, curr_y), "Domiciliu  /  Adresse  /  Address", fill="#64748B", font=font_lbl)
    curr_y += 16
    draw.text((fields_start_x, curr_y), profile.address, fill="#0F172A", font=font_val)
    curr_y += 30

    # Emis de & Valabilitate
    draw.text((fields_start_x, curr_y), "Emis de  /  Délivrée par", fill="#64748B", font=font_lbl)
    draw.text((fields_start_x + 320, curr_y), "Valabilitate  /  Validité", fill="#64748B", font=font_lbl)
    curr_y += 16
    draw.text((fields_start_x, curr_y), profile.id_issuer, fill="#0F172A", font=_load_font("arialbd.ttf", 15))
    val_text = f"{profile.id_issue_date} - {profile.id_expiry_date}"
    draw.text((fields_start_x + 320, curr_y), val_text, fill="#0F172A", font=_load_font("arialbd.ttf", 15))

    # Watermark across center
    font_wm = _load_font("arialbd.ttf", 22)
    draw.text((320, 440), "SPECIMEN SINTETIC · TESTARE DEMO NUMAI", fill="#CBD5E1", font=font_wm)

    # 6. MRZ Zone (Machine Readable Zone) at bottom
    mrz_bg = [(18, 500), (width - 18, height - 18)]
    draw.rounded_rectangle(mrz_bg, radius=10, fill="#FFFFFF", outline="#CBD5E1", width=2)

    font_mrz = _load_mono_font(22)
    last_padded = profile.last_name.upper().replace(" ", "<")
    first_padded = profile.first_name.upper().replace(" ", "<")
    line1_body = f"{last_padded}<<{first_padded}"
    line1 = f"IDROU{line1_body:<30}".replace(" ", "<")[:36]

    b_parts = profile.birth_date.replace("-", "")
    b_yymmdd = b_parts[2:8] if len(b_parts) >= 8 else "850101"
    exp_parts = profile.id_expiry_date.replace("-", "")
    exp_yymmdd = exp_parts[2:8] if len(exp_parts) >= 8 else "350101"

    cnp_tail = profile.cnp[-6:] if len(profile.cnp) >= 6 else "000000"
    series_nr = f"{profile.id_series}{profile.id_number}"
    line2 = f"{series_nr:<9}<0ROU{b_yymmdd}4{profile.gender}{exp_yymmdd}0<{cnp_tail}<<4".replace(" ", "<")[:36]

    draw.text((45, 525), line1, fill="#0F172A", font=font_mrz)
    draw.text((45, 580), line2, fill="#0F172A", font=font_mrz)
    draw.text((width - 400, 645), "DOCUMENT OFICIAL FICTIV PENTRU TESTARE BANCARĂ", fill="#94A3B8", font=_load_font("arial.ttf", 10))

    return card


def generate_identity_card(
    profile: CustomerDocumentProfile,
    output_pdf: Optional[Path] = None,
    output_png: Optional[Path] = None,
) -> Image.Image:
    """Generate a synthetic Romanian Identity Card embedded into a standard A4 scanned sheet (PDF/PNG)."""
    page_w, page_h = 1240, 1754
    a4_page = Image.new("RGB", (page_w, page_h), color="#FFFFFF")
    draw = ImageDraw.Draw(a4_page)

    font_page_title = _load_font("arialbd.ttf", 22)
    font_regular_md = _load_font("arial.ttf", 15)
    font_regular_sm = _load_font("arial.ttf", 13)
    font_bold_sm = _load_font("arialbd.ttf", 13)
    font_conform = _load_font("arialbd.ttf", 18)

    # 1. Subtle scanner margin
    draw.rectangle([(30, 30), (page_w - 30, page_h - 30)], outline="#E2E8F0", width=1)

    # 2. Header of the scanned copy
    curr_y = 60
    draw.text((70, curr_y), "COPIE SCANATĂ · CARTE DE IDENTITATE", fill="#0F172A", font=font_page_title)
    draw.text((page_w - 360, curr_y + 6), "Dosar credit bancar (Demo)", fill="#64748B", font=font_bold_sm)
    curr_y += 32
    draw.text((70, curr_y), f"Titular: {profile.full_name.upper()}  ·  CNP: {profile.cnp}", fill="#475569", font=font_regular_md)

    curr_y += 28
    draw.line([(70, curr_y), (page_w - 70, curr_y)], fill="#0F172A", width=2)

    # 3. Render and embed the physical ID card in upper-center
    card_img = _render_id_card_surface(profile)
    card_x = (page_w - card_img.width) // 2
    card_y = curr_y + 40

    draw.rounded_rectangle([(card_x - 3, card_y - 3), (card_x + card_img.width + 3, card_y + card_img.height + 3)], radius=26, outline="#94A3B8", width=2)
    a4_page.paste(card_img, (card_x, card_y))

    # 4. Conformity Declaration Box below the card
    box_y = card_y + card_img.height + 60
    box_w = page_w - 140
    draw.rounded_rectangle([(70, box_y), (70 + box_w, box_y + 180)], radius=12, fill="#F8FAFC", outline="#CBD5E1", width=1)

    draw.text((100, box_y + 24), "CONFORM CU ORIGINALUL", fill="#002B7F", font=font_conform)
    draw.text((100, box_y + 58), f"Subsemnatul/a {profile.full_name.upper()}, titular al actului de identitate seria {profile.id_series} nr. {profile.id_number},", fill="#334155", font=font_regular_sm)
    draw.text((100, box_y + 80), "declar pe propria răspundere că prezenta copie este fidelă și conformă cu originalul prezentat.", fill="#334155", font=font_regular_sm)

    draw.text((100, box_y + 125), "Data: 28.10.2026", fill="#0F172A", font=font_bold_sm)
    draw.text((page_w - 420, box_y + 125), "Semnătură titular: ________________________", fill="#0F172A", font=font_bold_sm)

    sig_x = page_w - 280
    sig_y = box_y + 115
    draw.line([(sig_x, sig_y), (sig_x + 35, sig_y - 12), (sig_x + 65, sig_y + 8), (sig_x + 120, sig_y - 5)], fill="#002B7F", width=2)

    # 5. Footer Disclaimer
    footer_y = page_h - 90
    draw.line([(70, footer_y), (page_w - 70, footer_y)], fill="#E2E8F0", width=1)
    footer_y += 14
    draw.text((70, footer_y), "DOCUMENT SINTETIC DE TESTARE PENTRU PROTOTIPUL DE CREDITARE AGENTIC · FORMAT PDF", fill="#94A3B8", font=_load_font("arialbd.ttf", 10))
    draw.text((70, footer_y + 18), "Toate datele cu caracter personal sunt fabricate în scop exclusiv demonstrativ și de testare tehnică.", fill="#94A3B8", font=_load_font("arial.ttf", 10))

    # 6. Save outputs if requested
    if output_png:
        output_png.parent.mkdir(parents=True, exist_ok=True)
        a4_page.save(output_png, "PNG")

    if output_pdf:
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        text_transcript = (
            f"ROMÂNIA\n"
            f"CARTE DE IDENTITATE · IDENTITY CARD\n"
            f"SERIA {profile.id_series} NR. {profile.id_number}\n"
            f"C.N.P. {profile.cnp}\n"
            f"Nume: {profile.last_name.upper()}\n"
            f"Prenume: {profile.first_name.upper()}\n"
            f"Cetățenie: {profile.citizenship} Sex: {profile.gender}\n"
            f"Loc naștere: {profile.birth_place}\n"
            f"Domiciliu: {profile.address}\n"
            f"Emis de: {profile.id_issuer} Valabilitate: {profile.id_issue_date} - {profile.id_expiry_date}\n"
            f"Titular: {profile.full_name.upper()}"
        )

        buf = io.BytesIO()
        a4_page.save(buf, "PDF", resolution=150.0)
        buf.seek(0)
        reader = pypdf.PdfReader(buf)
        writer = pypdf.PdfWriter()
        for p in reader.pages:
            writer.add_page(p)
        writer.add_metadata({
            "/Title": "Carte de Identitate",
            "/Author": profile.full_name,
            "/Subject": text_transcript,
        })
        with open(output_pdf, "wb") as f:
            writer.write(f)

    return a4_page
