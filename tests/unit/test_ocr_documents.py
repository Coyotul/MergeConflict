"""OCR checks use real images/PDFs; test names describe exactly what is guaranteed."""
from io import BytesIO
import sys

from PIL import Image
import pytest
from pypdf import PdfReader, PdfWriter

from src.parsers.ocr.pdf_extractor import PdfExtractor
from tests.fixtures.documents import identity_text, image_bytes, pdf_bytes


def scanned_pdf_bytes(text):
    with Image.open(BytesIO(image_bytes(text))) as image:
        output = BytesIO()
        image.save(output, format="PDF", resolution=150)
        return output.getvalue()


def test_native_pdf_text_is_read_without_calling_ocr(monkeypatch):
    def forbidden(*args):
        raise AssertionError("Native PDF text should not need OCR")
    monkeypatch.setattr(PdfExtractor, "_ocr_image_bytes", forbidden)
    assert "SERIA RX NR. 781920" in PdfExtractor.extract_text(pdf_bytes(identity_text()))


@pytest.mark.skipif(sys.platform != "win32", reason="Actual Windows OCR requires Windows")
@pytest.mark.parametrize("format,rotation", [("PNG", 0), ("JPEG", 0), ("PNG", 180)])
def test_real_windows_ocr_reads_clear_and_rotated_scan_images(format, rotation):
    text = PdfExtractor.extract_image_text(image_bytes(identity_text(), image_format=format, rotation=rotation))
    assert "POPESCU" in text.upper()
    assert "781920" in text


@pytest.mark.skipif(sys.platform != "win32", reason="Actual Windows OCR requires Windows")
def test_scanned_pdf_is_read_from_its_image_not_metadata():
    text = PdfExtractor.extract_text(scanned_pdf_bytes(identity_text()))
    assert "POPESCU" in text.upper()
    assert "781920" in text


@pytest.mark.skipif(sys.platform != "win32", reason="Actual Windows OCR requires Windows")
def test_mixed_native_and_scanned_pdf_does_not_silently_drop_the_scanned_page():
    writer = PdfWriter()
    writer.add_page(PdfReader(BytesIO(pdf_bytes("Native first page"))).pages[0])
    writer.add_page(PdfReader(BytesIO(scanned_pdf_bytes(identity_text()))).pages[0])
    output = BytesIO()
    writer.write(output)
    text = PdfExtractor.extract_text(output.getvalue())
    assert "Native first page" in text
    assert "POPESCU" in text.upper()