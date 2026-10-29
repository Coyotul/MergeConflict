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


def build_demo_cost_sheet(variant_name_x: float = 20, footnotes: bool = True, extra_footnotes: int = 0) -> bytes:
    """Build a synthetic cost sheet that imitates the real cost sheet layout.

    The product, values and wording are invented. The layout mirrors the real
    template: a date and a title, fact lines, benefit bullets, a variant table
    whose header labels span 3 lines over 7 columns, variant cells over 2-3
    lines with vertically centred fee cells, footnotes, the early repayment
    label on the left with its value over two lines on the right, and one
    worked example with a small side table.

    variant_name_x moves the first line of each variant label (the product name) right;
    a real sheet centres it so that it starts just past the end of "Tip produs".
    footnotes=False drops the footnotes, as on sheets without any.
    extra_footnotes adds that many long footnote lines (10pt apart), pushing the
    early repayment fee and the example down, so the facts can exceed MAX_TOKENS.
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
            (variant_name_x, top, "Demoflex"),
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

    if footnotes:
        items += [
            (20, 335, "1Rata dobânzii demo este fixă pe toată perioada creditului."),
            (20, 345, "*Valorile DAE demo sunt calculate pentru suma maximă."),
        ]
    shift = 10 * extra_footnotes
    items += [
        (20, 355 + 10 * n, f"{n + 2}Nota demo {n}: condiție demonstrativă de acordare, valabilă pentru toate variantele demo.")
        for n in range(extra_footnotes)
    ]
    items += [(x, y + shift, text) for x, y, text in [
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
    ]]
    return make_pdf([items], fontsize=fontsize)


def build_demo_offer_cost_sheet(scale: float = 1.0) -> bytes:
    """Build a synthetic secured-credit cost sheet: one bordered table, offers as columns.

    Invented product and values. The layout mirrors the real secured sheets: a short
    title line, a header row naming the table and two offers, attribute rows with a
    group label in a left column, per-offer values where a vertical divider separates
    the offers and one shared value where it does not, a fee row whose value starts on
    a line above its label (nearer the previous row), then footnotes, two worked
    examples and a risk warning. scale draws the whole sheet as a miniature.
    """
    font = fitz.Font(fontfile=str(FONT_FILE))
    items = [
        (270, 58, "3Y demo"),
        (150, 80, "Oferta credit Demo Casa ****"),
        (300, 80, "Oferta clienti Premium* demo"),
        (450, 80, "Oferta standard"),
        # Group A: fixed rate, per-offer values.
        (150, 94, "Rata dobanda fixa 3 ani"), (330, 94, "4.10%"), (460, 94, "5.20%"),
        (150, 106, "Formula demo"), (320, 106, "IRCC** + 1.50%"), (450, 106, "IRCC** + 2.50%"),
        (52, 112, "Dobanda fixa demo"),
        (150, 118, "DAE***"), (330, 118, "5.00%"), (460, 118, "6.00%"), (52, 118, "3 ani (Lei)"),
        # Group B: variable rate.
        (150, 131, "Rata dobanda"), (330, 131, "6.40%"), (460, 131, "7.40%"),
        (52, 137, "Dobanda variabila"),
        (150, 143, "DAE***"), (330, 143, "7.00%"), (460, 143, "8.00%"), (52, 145, "demo (Lei)"),
        # Group C: fees, one value shared by both offers.
        (150, 156, "Comision analiza"), (400, 156, "700 lei"),
        (330, 165, "0,10% x valoarea demo a imobilului"),
        (52, 172, "Taxe si comisioane"),
        (150, 181, "Asigurare imobil facultativa"), (350, 181, "conform evaluarii demo /an"),
        (52, 181, "demo"),
        (150, 193, "Comision rambursare anticipata"), (410, 193, "0"),
        (52, 215, "* Clienti Premium demo: venit minim 9.000 lei"),
        (52, 227, "** Indice demo trimestrial: 4.00%"),
        (52, 239, "*** DAE demo calculata pentru 100.000 lei"),
        (58, 265, "Exemplu de calcul reprezentativ: credit demo de 100.000 Lei, dobanda fixa 4.10%,"),
        (58, 277, "rata lunara 600,00 lei, DAE 5.00%."),
        (58, 300, "Exemplu de calcul reprezentativ: credit demo de 100.000 Lei, dobanda variabila 6.40%,"),
        (58, 312, "rata lunara 650,00 lei, DAE 7.00%."),
        (52, 340, "Avertisment! Riscuri demo: dobanda poate creste."),
        (52, 352, "IRCC demo se actualizeaza de 4 ori pe an."),
    ]
    label_rules = [98, 110, 135, 160, 184]  # label and value columns
    group_rules = [70, 84, 122, 147, 197]  # whole table width
    value_rules = [172]  # splits the two value lines of the facultative insurance row
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    tw = fitz.TextWriter(page.rect)
    for x, y, text in items:
        tw.append((x * scale, y * scale), text, font=font, fontsize=9 * scale)
    tw.write_text(page)

    def line(x0: float, y0: float, x1: float, y1: float) -> None:
        page.draw_line((x0 * scale, y0 * scale), (x1 * scale, y1 * scale), width=0.5 * scale)

    for y in label_rules:
        line(149, y, 570, y)
    for y in group_rules:
        line(51, y, 570, y)
    for y in value_rules:
        line(291, y, 570, y)
    for x in (51, 149, 290, 570):
        line(x, 70, x, 197)
    line(440, 70, 440, 147)  # offers have separate values only in the rate rows
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes
