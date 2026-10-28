"""Cost sheet PDF parser (one template shared by all product cost sheets)."""
import re
import unicodedata

import pymupdf as fitz

from src.core.errors import TemplateMismatch
from src.models.knowledge import ChunkKind
from src.services.document_ingestion.chunking import CHUNKER_VERSION, ChunkDraft, ParsedDocument
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


def _document_words(data: bytes) -> list[Word]:
    """All words of the document, pages stacked vertically in one coordinate space."""
    doc = fitz.open(stream=data, filetype="pdf")
    words = []
    offset = 0.0
    for page in doc:
        for w in page_words(page):
            words.append(Word(w.x0, w.y0 + offset, w.x1, w.y1 + offset, w.text))
        offset += page.rect.height
    doc.close()
    return words


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
    first_variant = next(
        (i for i in range(tip_idx + 1, len(lines))
         if any(w.text.startswith(first_word) and w.x0 < left_edge for w in lines[i])),
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

    def ends_body(i: int) -> bool:
        starts_left = min(w.x0 for w in lines[i]) < left_edge
        return (starts_left and bool(FOOTNOTE_RE.match(texts[i]))) or "plata anticipata" in _fold(texts[i])

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


def parse_cost_sheet(data: bytes) -> ParsedDocument:
    """Parse a cost sheet PDF into a cost facts chunk and a worked examples chunk.

    Falls back to one generic chunk of rebuilt rows, with a warning, when the
    document does not match the cost sheet template.
    """
    lines = _group_lines(_document_words(data))
    texts = [_line_text(line) for line in lines]
    full_text = "\n".join(t for t in texts if t)
    title_idx = next((i for i, t in enumerate(texts) if t and not DATE_RE.match(t)), None)
    title = texts[title_idx] if title_idx is not None else ""

    try:
        if title_idx is None:
            raise TemplateMismatch("no title line")
        facts, examples = _parse_template(lines, title_idx, title)
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

    chunks = [ChunkDraft(kind=ChunkKind.cost_facts, section_path=list(FACTS_PATH), text=facts, page=1)]
    if examples:
        chunks.append(ChunkDraft(kind=ChunkKind.cost_examples, section_path=list(EXAMPLES_PATH), text=examples, page=1))
    return ParsedDocument(
        title=title,
        chunks=chunks,
        metadata_text=full_text,
        parser_name="cost_sheet",
        parser_version=CHUNKER_VERSION,
    )
