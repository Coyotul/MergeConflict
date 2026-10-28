"""PDF test fixture builders using PyMuPDF."""
import pymupdf as fitz
from pathlib import Path


# Use Arial font for Romanian diacritic support
FONT_FILE = Path("C:/Windows/Fonts/arial.ttf")


def make_pdf(pages: list[list[tuple[float, float, str]]], fontsize: float = 9) -> bytes:
    """Build a PDF from positioned text spans.

    Args:
        pages: Each page is a list of (x, y, text) tuples for TextWriter calls
        fontsize: Font size for text

    Returns:
        PDF bytes
    """
    doc = fitz.open()

    # Load font once for all pages
    font = fitz.Font(fontfile=str(FONT_FILE))

    for page_items in pages:
        page = doc.new_page(width=595, height=842)  # A4 size
        tw = fitz.TextWriter(page.rect)

        for x, y, text in page_items:
            # Use TextWriter for proper font embedding
            tw.append((x, y), text, font=font, fontsize=fontsize)

        tw.write_text(page)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def make_pdf_from_lines(lines: list[str], fontsize: float = 6) -> bytes:
    """Build a PDF from text lines with automatic pagination and wrapping.

    Args:
        lines: Text lines to write
        fontsize: Font size for text (small fontsize to fit long lines)

    Returns:
        PDF bytes
    """
    doc = fitz.open()

    # Load font for proper diacritic support
    font = fitz.Font(fontfile=str(FONT_FILE))

    line_height = fontsize + 2  # Spacing between lines
    margin_left = 50
    margin_top = 50
    page_width = 595 - 100  # A4 width minus margins
    page_height = 842 - 100  # A4 height minus margins

    page = None
    y_position = margin_top
    tw = None

    def new_page():
        nonlocal page, y_position, tw
        if tw is not None:
            tw.write_text(page)
        page = doc.new_page(width=595, height=842)
        y_position = margin_top
        tw = fitz.TextWriter(page.rect)

    for line in lines:
        if page is None:
            new_page()

        # Wrap text manually by words
        words = line.split()
        current_line = ""
        x_position = margin_left

        for word in words:
            if font.text_length(word, fontsize=fontsize) > page_width:
                raise ValueError(f"word wider than the page, it would be clipped: {word[:40]!r}")
            test_line = current_line + (" " if current_line else "") + word
            # Estimate width (rough approximation)
            text_width = font.text_length(test_line, fontsize=fontsize)

            if text_width > page_width and current_line:
                # Write current line and start new one
                if y_position + line_height > margin_top + page_height:
                    new_page()

                tw.append((margin_left, y_position), current_line, font=font, fontsize=fontsize)
                y_position += line_height
                current_line = word
            else:
                current_line = test_line

        # Write remaining text
        if current_line:
            if y_position + line_height > margin_top + page_height:
                new_page()

            tw.append((margin_left, y_position), current_line, font=font, fontsize=fontsize)
            y_position += line_height

    # Write final page
    if tw is not None:
        tw.write_text(page)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def build_demo_cost_sheet() -> bytes:
    """Build a synthetic cost sheet that imitates the real cost sheet layout.

    The product, values and wording are invented. The layout mirrors the real
    template: a date and a title, fact lines, benefit bullets, a variant table
    whose header labels span 3 lines over 7 columns, variant cells over 2-3
    lines with vertically centred fee cells, footnotes, the early repayment
    label on the left with its value over two lines on the right, and one
    worked example with a small side table.
    """
    font = fitz.Font(fontfile=str(FONT_FILE))
    fontsize = 9

    def centred(centre: float, y: float, text: str) -> tuple[float, float, str]:
        return (centre - font.text_length(text, fontsize=fontsize) / 2, y, text)

    # Column centres for columns 1-6; column 0 is left aligned at x=20.
    # As in the real sheet, the first column's cells run well past its header,
    # so their right-hand words sit nearer column 1's header than column 0's.
    c1, c2, c3, c4, c5, c6 = 140, 225, 290, 355, 425, 505

    items = [
        (20, 40, "01.10.2026"),
        (190, 90, "Demoflex Fara Asigurare"),
        (20, 105, "Tip credit: Credit demo pentru nevoi personale"),
        (20, 115, "Valuta: Lei"),
        (20, 125, "Valoare: 1.000 Lei pana la 40.000 Lei"),
        (20, 135, "Perioada maxima: 5 ani."),
        (20, 147, "Beneficii:"),
        (150, 157, "- aprobare demo rapidă"),
        (150, 167, "- dobândă fixă demo pe toată perioada"),
        (20, 180, "Costuri credit:"),
        # Header labels over 3 lines (Rată dobândă sits between them).
        (20, 210, "Tip produs"),
        centred(c1, 200, "Monedă/"),
        centred(c1, 210, "tip"),
        centred(c1, 220, "dobândă"),
        centred(c2, 200, "Sumă credit"),
        centred(c2, 210, "(echivalent"),
        centred(c2, 220, "Euro)"),
        centred(c3, 205, "Rată"),
        centred(c3, 215, "dobândă"),
        centred(c4, 200, "Comision"),
        centred(c4, 210, "de analiză"),
        centred(c4, 220, "dosar"),
        centred(c5, 200, "Comision de"),
        centred(c5, 210, "administrare"),
        centred(c5, 220, "lunar"),
        centred(c6, 210, "DAE"),
    ]

    # Variant rows: multi-line cells, fee cells vertically centred between lines.
    for top, segment, rate, dae in (
        (245, "standard", ("de la 6.10%", "la 15.20%"), ("de la 9.80% la", "21.40%")),
        (290, "premium", ("de la 5.90%", "la 15.00%"), ("de la 9.50% la", "21.10%")),
    ):
        items += [
            (20, top, "Demoflex"),
            (20, top + 10, "Fara Asigurare, client"),
            (20, top + 20, segment),
            centred(c1, top, "Lei"),
            centred(c1, top + 10, "Fixa"),
            centred(c2, top, "Indiferent de"),
            centred(c2, top + 10, "suma"),
            centred(c3, top, rate[0]),
            centred(c3, top + 10, rate[1]),
            centred(c4, top + 5, "150 lei"),
            centred(c5, top + 5, "4 lei"),
            centred(c6, top, dae[0]),
            centred(c6, top + 10, dae[1]),
        ]

    items += [
        (20, 335, "1Rata dobânzii demo este fixă pe toată perioada creditului."),
        (20, 345, "*Valorile DAE demo sunt calculate pentru suma maximă."),
        # Early repayment: label on the left, value over two lines on the right.
        (20, 370, "Comision de plată anticipată"),
        (300, 366, "0,50 % in ultimul an de contract / 1,00%"),
        (290, 375, "inainte de inceperea ultimului an de contract"),
        # One worked example with a side table.
        (20, 400, "Exemplu de calcul pentru oferta demo standard"),
        (20, 415, "Pentru un credit demo de 40.000 Lei, acordat pe 5 ani, cu o"),
        (330, 416, "Rata lunară"),
        (430, 416, "DAE"),
        (20, 425, "rată fixă a dobânzii de 6.10%, rata lunară este 850,00 Lei"),
        (330, 430, "850,00 lei"),
        (430, 430, "9,80%"),
        (20, 435, "și DAE 9,80%."),
    ]
    return make_pdf([items], fontsize=fontsize)
