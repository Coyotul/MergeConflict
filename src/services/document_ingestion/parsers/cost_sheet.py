"""Cost sheet PDF parser.

Two templates: unsecured sheets list product variants as rows under a "Tip produs"
header; secured (mortgage) sheets draw one bordered table with the offers as columns.
"""
import re
import statistics
import unicodedata
from dataclasses import dataclass

import pymupdf as fitz

from src.core.errors import TemplateMismatch
from src.models.knowledge import ChunkKind
from src.services.document_ingestion.chunking import CHUNKER_VERSION, ChunkDraft, ParsedDocument, pack_lines
from src.services.document_ingestion.normalize import normalize_text
from src.services.document_ingestion.parsers.pdf_rows import Word, page_words, rebuild_rows

FACTS_PATH = ["Costuri complete", "Condiții și costuri"]
EXAMPLES_PATH = ["Costuri complete", "Exemple de calcul"]

LINE_TOLERANCE = 3.0  # same as rebuild_rows: words within 3pt of a line's y-centre
PHRASE_GAP = 5.0  # words on one line closer than this belong to one phrase (one cell)
COLUMN_GAP = 15.0  # header phrase x-centres further apart than this start a new column
HEADER_LINE_GAP = 10.0  # header lines above "Tip produs" are at most this far apart
CELL_GAP = 12.0  # rebuild_rows' column_gap: a gap this wide ends a cell
ROW_BAND = 12.0  # early repayment value lines lie within this distance of the label
EXAMPLE_INDENT = 20.0  # example lines starting further right are side-table residue
MIN_COLUMNS = 6
VALUE_MARGIN = 10.0  # offer table values start at most this far left of their offer header
MIN_WORD_HEIGHT = 4.0  # median word heights below this mark a miniature sheet
REFERENCE_WORD_HEIGHT = 6.0  # typical median word height of a full-size sheet
RULE_THICKNESS = 2.0  # drawn table borders are thinner than this
RULE_SLACK = 1.5  # a rule covers a point within this distance of its ends

DATE_RE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}$")
FOOTNOTE_RE = re.compile(r"^(\d{1,2}\s?[^\W\d_]|\*)")

# Canonical output labels, chosen by a keyword of the column's header text.
COLUMN_LABELS = (
    ("moneda", "Monedă/tip dobândă"),
    ("suma", "Sumă credit"),
    ("rata", "Rată dobândă"),
    ("analiza", "Comision analiză dosar"),
    ("administrare", "Comision administrare lunar"),
    ("dae", "DAE"),
)

Line = list[Word]


def _fold(text: str) -> str:
    """Lower-case and strip diacritics, for accent-insensitive matching."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _yc(word: Word) -> float:
    return (word.y0 + word.y1) / 2


def _xc(word: Word) -> float:
    return (word.x0 + word.x1) / 2


@dataclass
class Rule:
    """A drawn table border: a horizontal (y0 == y1) or vertical (x0 == x1) segment."""
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def horizontal(self) -> bool:
        return self.y1 - self.y0 < self.x1 - self.x0


def _page_rules(page: fitz.Page, offset: float) -> list[Rule]:
    """Thin lines and hairline rectangles drawn on the page, as segments along their long side."""
    rules = []
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] == "l":
                (a, b) = item[1], item[2]
                x0, x1, y0, y1 = min(a.x, b.x), max(a.x, b.x), min(a.y, b.y), max(a.y, b.y)
            elif item[0] == "re":
                r = item[1]
                if min(r.width, r.height) >= RULE_THICKNESS:
                    continue
                x0, x1, y0, y1 = r.x0, r.x1, r.y0, r.y1
            else:
                continue
            if y1 - y0 < RULE_THICKNESS:  # horizontal
                y0 = y1 = (y0 + y1) / 2
            elif x1 - x0 < RULE_THICKNESS:  # vertical
                x0 = x1 = (x0 + x1) / 2
            else:
                continue
            rules.append(Rule(x0, y0 + offset, x1, y1 + offset))
    return rules


def _document_layout(data: bytes) -> tuple[list[Word], list[Rule]]:
    """All words and table rules of the document, pages stacked vertically in one coordinate space.

    A sheet drawn as a miniature (median word height under MIN_WORD_HEIGHT) is scaled
    up to REFERENCE_WORD_HEIGHT, so the point tolerances below fit every sheet.
    """
    doc = fitz.open(stream=data, filetype="pdf")
    words: list[Word] = []
    rules: list[Rule] = []
    offset = 0.0
    for page in doc:
        for w in page_words(page):
            words.append(Word(w.x0, w.y0 + offset, w.x1, w.y1 + offset, w.text))
        rules += _page_rules(page, offset)
        offset += page.rect.height
    doc.close()
    if words:
        median_height = statistics.median(w.y1 - w.y0 for w in words)
        if median_height < MIN_WORD_HEIGHT:
            s = REFERENCE_WORD_HEIGHT / median_height
            words = [Word(w.x0 * s, w.y0 * s, w.x1 * s, w.y1 * s, w.text) for w in words]
            rules = [Rule(r.x0 * s, r.y0 * s, r.x1 * s, r.y1 * s) for r in rules]
    return words, rules


def _group_lines(words: list[Word]) -> list[Line]:
    """Group words into lines by y-centre, top to bottom.

    Each line keeps its topmost word first, so rebuild_rows() turns the line
    back into exactly one row.
    """
    lines: list[Line] = []
    for word in sorted(words, key=lambda w: (_yc(w), w.x0)):
        if lines and abs(_yc(word) - _yc(lines[-1][0])) <= LINE_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
    return lines


def _line_y(line: Line) -> float:
    return _yc(line[0])


def _line_text(line: Line) -> str:
    return normalize_text(rebuild_rows(line)[0]) if line else ""


def _split_line(line: Line, gap: float) -> list[Line]:
    """Split a line, left to right, wherever the gap between words exceeds gap."""
    parts: list[Line] = []
    for word in sorted(line, key=lambda w: w.x0):
        if parts and word.x0 - parts[-1][-1].x1 <= gap:
            parts[-1].append(word)
        else:
            parts.append([word])
    return parts


def _join(words: list[Word]) -> str:
    return " ".join(w.text for w in words)


def _phrase_x(phrase: Line) -> tuple[float, float]:
    return min(w.x0 for w in phrase), max(w.x1 for w in phrase)


def _find_header_start(lines: list[Line]) -> tuple[int, float]:
    """Index of the line holding "Tip produs", and the right edge of "produs"."""
    for i, line in enumerate(lines):
        ordered = sorted(line, key=lambda w: w.x0)
        for a, b in zip(ordered, ordered[1:]):
            if _fold(a.text) == "tip" and _fold(b.text) == "produs":
                return i, b.x1
    raise TemplateMismatch("no 'Tip produs' header")


def _column_label(header_text: str) -> str:
    folded = _fold(header_text)
    for keyword, label in COLUMN_LABELS:
        if keyword in folded:
            return label
    return header_text


def _build_columns(header_lines: list[Line]) -> list[dict]:
    """Cluster header phrases by x-centre into columns, left to right."""
    phrases = [p for line in header_lines for p in _split_line(line, PHRASE_GAP)]
    phrases.sort(key=lambda p: sum(_phrase_x(p)) / 2)
    clusters: list[list[Line]] = []
    last_centre = None
    for phrase in phrases:
        centre = sum(_phrase_x(phrase)) / 2
        if last_centre is None or centre - last_centre > COLUMN_GAP:
            clusters.append([])
        clusters[-1].append(phrase)
        last_centre = centre
    columns = []
    for cluster in clusters:
        words = sorted((w for p in cluster for w in p), key=lambda w: (_yc(w), w.x0))
        columns.append({
            "x0": min(w.x0 for w in words),
            "x1": max(w.x1 for w in words),
            "header": _join(words),
        })
    return columns


def _column_for(phrase: Line, columns: list[dict]) -> int:
    """The column whose x-range holds the phrase centre, else the nearest one."""
    x0, x1 = _phrase_x(phrase)
    centre = (x0 + x1) / 2

    def distance(col: dict) -> float:
        if col["x0"] <= centre <= col["x1"]:
            return 0.0
        return min(abs(centre - col["x0"]), abs(centre - col["x1"]))

    return min(range(len(columns)), key=lambda i: distance(columns[i]))


def _variant_lines(body_lines: list[Line], columns: list[dict], first_word: str) -> list[str]:
    """Split the table body into variant rows and render one line per variant."""
    rows: list[list[list[str]]] = []
    for line in body_lines:
        for phrase in _split_line(line, PHRASE_GAP):
            col = _column_for(phrase, columns)
            if col == 0 and any(w.text == first_word for w in phrase):
                rows.append([[] for _ in columns])
            if rows:
                rows[-1][col].append(_join(phrase))

    if not rows:
        raise TemplateMismatch("no variant rows")
    labels = ["Variantă"] + [_column_label(c["header"]) for c in columns[1:]]
    rendered = []
    for i, row in enumerate(rows, start=1):
        cells = [normalize_text(" ".join(parts)) for parts in row]
        if "%" not in cells[-1]:
            raise TemplateMismatch(f"variant row {i} has no % in the last column")
        rendered.append(" | ".join(f"{label}: {cell}" for label, cell in zip(labels, cells)))
    return rendered


def _early_repayment(lines: list[Line]) -> tuple[str | None, set[int]]:
    """The early repayment line, and the ids of the words it used."""
    for line in lines:
        if "plata anticipata" not in _fold(_join(sorted(line, key=lambda w: w.x0))):
            continue
        label = _split_line(line, CELL_GAP)[0]
        label_x1 = max(w.x1 for w in label)
        label_y = _line_y(line)
        value_words = [
            w for other in lines for w in other
            if abs(_yc(w) - label_y) <= ROW_BAND and w.x0 > label_x1
        ]
        value = " ".join(_join(sorted(l, key=lambda w: w.x0)) for l in _group_lines(value_words))
        used = {id(w) for w in label} | {id(w) for w in value_words}
        return f"Comision de plată anticipată: {normalize_text(value)}", used
    return None, set()


def _example_lines(lines: list[Line]) -> list[str]:
    """Example titles and prose; side-table cells are dropped."""
    margin = min(w.x0 for w in lines[0])
    kept = []
    for line in lines:
        if min(w.x0 for w in line) > margin + EXAMPLE_INDENT:
            continue  # starts inside the side table
        prose = _line_text(line).split(" | ")[0]
        if prose:
            kept.append(prose)
    return kept


def _parse_template(lines: list[Line], title_idx: int, title: str) -> tuple[str, str | None]:
    """Build the cost facts text and the examples text, or raise TemplateMismatch."""
    first_word = title.split()[0]
    tip_idx, left_edge = _find_header_start(lines)

    # Header band: up from "Tip produs" over close lines right of the first
    # column, down to the line before the first variant.
    top = tip_idx
    while top > title_idx + 1:
        above = lines[top - 1]
        if _line_y(lines[top]) - _line_y(above) > HEADER_LINE_GAP or any(w.x0 < left_edge for w in above):
            break
        top -= 1
    # Variant labels sit left of the first header column; some sheets indent them past "produs".
    variant_edge = min((w.x0 for w in lines[tip_idx] if w.x0 > left_edge), default=left_edge)
    first_variant = next(
        (i for i in range(tip_idx + 1, len(lines))
         if any(w.text.startswith(first_word) and w.x0 < variant_edge for w in lines[i])),
        None,
    )
    if first_variant is None:
        raise TemplateMismatch(f"no variant row starting with {first_word!r}")
    columns = _build_columns(lines[top:first_variant])
    if len(columns) < MIN_COLUMNS:
        raise TemplateMismatch(f"found {len(columns)} header columns, expected at least {MIN_COLUMNS}")

    texts = [_line_text(line) for line in lines]
    examples_idx = next(
        (i for i in range(first_variant, len(lines)) if _fold(texts[i]).startswith("exemplu de calcul")),
        len(lines),
    )

    # The early repayment value can be drawn just above its label: the body ends at that band.
    early_ys = [_line_y(lines[i]) for i in range(first_variant, examples_idx) if "plata anticipata" in _fold(texts[i])]

    def ends_body(i: int) -> bool:
        starts_left = min(w.x0 for w in lines[i]) < left_edge
        near_early_repayment = any(_line_y(lines[i]) >= y - ROW_BAND for y in early_ys)
        return (starts_left and bool(FOOTNOTE_RE.match(texts[i]))) or near_early_repayment

    body_end = next((i for i in range(first_variant, examples_idx) if ends_body(i)), examples_idx)
    variants = _variant_lines(lines[first_variant:body_end], columns, first_word)

    early_repayment, used = _early_repayment(lines[:examples_idx])
    footnotes = [_line_text([w for w in line if id(w) not in used]) for line in lines[body_end:examples_idx]]

    pre_table = [texts[i] for i in range(title_idx + 1, top)]
    if pre_table and _fold(pre_table[-1]) == "costuri credit:":
        pre_table.pop()

    facts = pre_table + ["Costuri credit:"] + variants + [f for f in footnotes if f]
    if early_repayment:
        facts.append(early_repayment)

    examples = None
    if examples_idx < len(lines):
        examples = "\n".join(_example_lines(lines[examples_idx:]))
    return "\n".join(facts), examples


def _has_oferta(line: Line) -> bool:
    return any(_fold(w.text) == "oferta" for w in line)


def _rule_ys(rules: list[Rule], x: float, top: float, bottom: float) -> list[float]:
    """Distinct heights of the horizontal rules crossing x between top and bottom."""
    ys: list[float] = []
    for y in sorted(r.y0 for r in rules if r.horizontal and r.x0 - RULE_SLACK <= x <= r.x1 + RULE_SLACK
                    and top <= r.y0 <= bottom):
        if not ys or y - ys[-1] > RULE_SLACK:
            ys.append(y)
    return ys


def _cell_text(words: list[Word]) -> str:
    """Words of one cell, line by line, left to right."""
    text = " ".join(_join(sorted(line, key=lambda w: w.x0)) for line in _group_lines(words))
    return normalize_text(" ".join(text.split()))


def _offer_split_xs(rules: list[Rule], offers: list[dict], a: float, b: float) -> list[float] | None:
    """x of the vertical dividers between the offers over the row band a..b; None if any is missing."""
    xs = []
    for left, right in zip(offers, offers[1:]):
        covering = [r.x0 for r in rules if not r.horizontal and left["x0"] < r.x0 < right["x0"]
                    and r.y0 - RULE_SLACK <= a and r.y1 + RULE_SLACK >= b]
        if not covering:
            return None
        xs.append(covering[0])
    return xs


def _offer_rows(body: list[Word], rules: list[Rule], offers: list[dict], label_x: float,
                top: float, bottom: float) -> list[str]:
    """One line per drawn row of the offer table, with a heading line for each row group.

    Row bands come from the horizontal rules crossing the label column, group bands from
    those crossing the group column on its left. A row has one value per offer where
    vertical dividers separate the offers over its band, else one value shared by all.
    """
    group_words = [w for w in body if w.x1 < label_x - RULE_SLACK]
    row_ys = _rule_ys(rules, label_x + RULE_SLACK, top, bottom)
    if len(row_ys) < 2:
        raise TemplateMismatch("offer table has no drawn row borders")
    group_ys = _rule_ys(rules, min(w.x0 for w in group_words) + RULE_SLACK, top, bottom) if group_words else []
    value_x = offers[0]["x0"] - VALUE_MARGIN

    rendered: list[str] = []
    current_group = None
    for a, b in zip(row_ys, row_ys[1:]):
        band = [w for w in body if a < _yc(w) < b and w.x1 >= label_x - RULE_SLACK]
        label = [w for w in band if _xc(w) < value_x]
        values = [w for w in band if _xc(w) >= value_x]
        if not label:
            continue
        group = next(((g0, g1) for g0, g1 in zip(group_ys, group_ys[1:]) if g0 <= (a + b) / 2 <= g1), None)
        if group is not None and group != current_group:
            current_group = group
            heading = _cell_text([w for w in group_words if group[0] < _yc(w) < group[1]])
            if heading:
                rendered.append(f"{heading}:")
        row = _cell_text(label)
        split_xs = _offer_split_xs(rules, offers, a, b)
        if values and split_xs is not None:
            cells = [[w for w in values if sum(x < _xc(w) for x in split_xs) == i] for i in range(len(offers))]
            row += "".join(f" | {normalize_text(o['header'])}: {_cell_text(c)}" for o, c in zip(offers, cells) if c)
        elif values:
            row += f" | {_cell_text(values)}"
        rendered.append(row)
    return rendered


def _parse_offer_table(lines: list[Line], rules: list[Rule], title_idx: int) -> tuple[str, str, list[str]]:
    """Title, cost facts and worked example blocks of a secured-credit sheet, or raise TemplateMismatch."""
    header_idx = next((i for i in range(title_idx, len(lines)) if _has_oferta(lines[i])), None)
    if header_idx is None:
        raise TemplateMismatch("no 'Oferta' header")
    header_end = header_idx
    while header_end + 1 < len(lines) and _has_oferta(lines[header_end + 1]):
        header_end += 1
    columns = _build_columns(lines[header_idx:header_end + 1])
    if len(columns) < 3:
        raise TemplateMismatch(f"found {len(columns)} offer table header columns, expected at least 3")
    table_title, offers = columns[0], columns[1:]

    texts = [_line_text(line) for line in lines]
    body_start = header_end + 1
    if body_start >= len(lines):
        raise TemplateMismatch("no offer table body")
    label_x = min(w.x0 for w in lines[body_start])
    footnote_idx = next(
        (i for i in range(body_start, len(lines))
         if texts[i].startswith("*") and min(w.x0 for w in lines[i]) < label_x),
        None,
    )
    if footnote_idx is None:
        raise TemplateMismatch("no footnotes after the offer table")
    top = max(_yc(w) for line in lines[header_idx:header_end + 1] for w in line)
    body = [w for line in lines[body_start:footnote_idx] for w in line]
    rows = _offer_rows(body, rules, offers, label_x, top, _line_y(lines[footnote_idx]))

    examples_idx = next(
        (i for i in range(footnote_idx, len(lines)) if _fold(texts[i]).startswith("exemplu de calcul")), len(lines)
    )
    blocks: list[list[str]] = []
    for i in range(examples_idx, len(lines)):
        if not blocks or _fold(texts[i]).startswith(("exemplu de calcul", "avertisment")):
            blocks.append([])
        blocks[-1].append(texts[i])

    name = re.sub(r"\*+$", "", normalize_text(table_title["header"])).strip()
    title = f"{name} ({texts[title_idx]})" if title_idx < header_idx else name
    facts = [t for t in texts[title_idx + 1:header_idx] if t] + ["Costuri credit:"] + rows
    facts += [t for t in texts[footnote_idx:examples_idx] if t]
    return title, "\n".join(facts), ["\n".join(t for t in block if t) for block in blocks]


def parse_cost_sheet(data: bytes) -> ParsedDocument:
    """Parse a cost sheet PDF into cost facts chunks and worked examples chunks.

    Tries the variant-rows template, then the offer-table template. Falls back to
    one generic chunk of rebuilt rows, with a warning, when neither matches.
    """
    words, rules = _document_layout(data)
    lines = _group_lines(words)
    texts = [_line_text(line) for line in lines]
    full_text = "\n".join(t for t in texts if t)
    title_idx = next((i for i, t in enumerate(texts) if t and not DATE_RE.match(t)), None)
    title = texts[title_idx] if title_idx is not None else ""

    try:
        if title_idx is None:
            raise TemplateMismatch("no title line")
        try:
            facts, examples = _parse_template(lines, title_idx, title)
            example_blocks = [examples] if examples else []
        except TemplateMismatch as variant_mismatch:
            try:
                title, facts, example_blocks = _parse_offer_table(lines, rules, title_idx)
            except TemplateMismatch as offer_mismatch:
                raise TemplateMismatch(f"{variant_mismatch}; offer table: {offer_mismatch}") from offer_mismatch
    except TemplateMismatch as exc:
        chunks = [ChunkDraft(kind=ChunkKind.generic, section_path=[], text=full_text, page=1)] if full_text else []
        return ParsedDocument(
            title=title,
            chunks=chunks,
            metadata_text=full_text,
            parser_name="cost_sheet_fallback",
            parser_version=CHUNKER_VERSION,
            warnings=[f"cost sheet template mismatch: {exc}"],
        )

    # The facts are one atomic chunk (spec §9), even over MAX_TOKENS: the footnotes and the early
    # repayment fee belong with the variant rows they qualify. BGE-M3 embeds inputs far longer
    # than one sheet's facts.
    chunks = [ChunkDraft(kind=ChunkKind.cost_facts, section_path=list(FACTS_PATH), text=facts, page=1)]
    # Each example block is atomic; several fit in one piece.
    chunks += [
        ChunkDraft(kind=ChunkKind.cost_examples, section_path=list(EXAMPLES_PATH), text=piece, page=1)
        for piece in pack_lines(example_blocks)
    ]
    return ParsedDocument(
        title=title,
        chunks=chunks,
        metadata_text=full_text,
        parser_name="cost_sheet",
        parser_version=CHUNKER_VERSION,
    )
