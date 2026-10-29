"""Small, readable synthetic documents with real PDF/image bytes (not mocked files)."""
from datetime import date
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from src.parsers.validation.cnp_validator import compute_cnp_checksum

REFERENCE_DATE = date(2026, 10, 28)
_CNP_BODY = "292051541001"
CNP = _CNP_BODY + str(compute_cnp_checksum(_CNP_BODY))


def identity_text(*, first_name="ANA", last_name="POPESCU", cnp=CNP,
                  expiry="2032-06-10") -> str:
    return (
        "CARTE DE IDENTITATE - SYNTHETIC TEST DOCUMENT\n"
        f"CNP: {cnp}\nSERIA RX NR. 781920\n"
        f"Nume\n{last_name}\nPrenume\n{first_name}\n"
        f"Valabilitate: 2022-06-10 - {expiry}\n"
    )


def income_text(*, name="ANA POPESCU", cnp=CNP, net="6.200,00",
                issued=REFERENCE_DATE, contract="NEDETERMINATA") -> str:
    return (
        "TechCorp SRL\nCUI: 18318261\nADEVERINTA DE VENIT - SYNTHETIC TEST\n"
        f"salariatul {name}, avand CNP: {cnp}\n"
        f"Contract pe perioada {contract}\n"
        "Angajat din data de 01.04.2021\n"
        f"Data emiterii: {issued:%d.%m.%Y}\n"
        f"Media venitului net: {net} RON\n"
    )


def statement_text(*, holder="ANA POPESCU", salary="6.200,00",
                   closing="6.800,00", obligations="400,00",
                   period_end=REFERENCE_DATE) -> str:
    return (
        "RAIFFEISEN BANK S.A. - SYNTHETIC TEST DOCUMENT\n"
        f"TITULAR CONT: {holder}\nIBAN: RO54RZBR0000060012345678\n"
        f"Perioada: 01.10.2026 - {period_end:%d.%m.%Y}\n"
        "Sold initial: 1.000,00 RON\n"
        f"Total incasari: {salary} RON\nTotal plati: 400,00 RON\n"
        f"Sold final: {closing} RON\nVIRAMENT SALARIU: +{salary} RON\n"
        f"Obligatii lunare credite existente: {obligations} RON\n"
    )


def pdf_bytes(*texts: str, metadata: dict[str, str] | None = None) -> bytes:
    """Build native-text PDFs using the already installed pypdf library."""
    writer = PdfWriter()
    for text in texts or ("",):
        page = writer.add_blank_page(width=595, height=842)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
        })
        commands = ["BT /F1 12 Tf 40 800 Td"]
        for line in text.splitlines():
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"({escaped}) Tj 0 -18 Td")
        commands.append("ET")
        stream = DecodedStreamObject()
        stream.set_data("\n".join(commands).encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    if metadata:
        writer.add_metadata(metadata)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def image_bytes(text: str = "", *, image_format="PNG", rotation=0) -> bytes:
    """A clear scan that can be exercised with the real Windows OCR engine."""
    image = Image.new("RGB", (1400, 950), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 32)
    except OSError:
        font = ImageFont.load_default(size=32)
    draw.multiline_text((50, 50), text, fill="black", font=font, spacing=14)
    if rotation:
        image = image.rotate(rotation, expand=True)
    output = BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


def document_bytes(doc_type: str) -> bytes:
    texts = {"id_card": identity_text(), "payslip": income_text(), "bank_statement": statement_text()}
    return pdf_bytes(texts[doc_type])