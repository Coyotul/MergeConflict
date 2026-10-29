"""PDF text extraction and optical character recognition (OCR) adapter.

Combines native vector text extraction with fallback to Windows Media OCR (ro-RO/en-US)
for scanned raster PDFs and images, with auto-rotation handling for tilted/upside-down scans.
"""

import io
from pathlib import Path
import re
from typing import Union
import warnings
import pypdf

from src.storage.secure_documents.validation import MAX_PDF_PAGES, MAX_IMAGE_PIXELS


class PdfExtractor:
    """Extract page text or OCR actual page images; metadata is never document evidence."""

    @classmethod
    def _ocr_image_bytes(cls, image_bytes: bytes) -> str:
        """Run OCR on image bytes using Windows Media OCR (ro-RO / en-US)."""
        try:
            import winocr
            from PIL import Image
            from winrt.windows.media.ocr import OcrEngine
        except ImportError as exc:
            raise ValueError("Scanned documents require Windows OCR with Romanian or English language support.") from exc

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(image_bytes)) as source:
                    if source.width * source.height > MAX_IMAGE_PIXELS:
                        raise ValueError("The scan exceeds the image processing limit.")
                    img = source.convert("RGB")
            max_dimension = OcrEngine.max_image_dimension
            if max(img.size) > max_dimension:
                img.thumbnail((max_dimension, max_dimension))
        except Exception as exc:
            raise ValueError("The scan could not be decoded safely.") from exc

        # First attempt: native orientation with Romanian OCR engine
        best_text = ""
        def quality(text: str) -> tuple[int, int]:
            # Upside-down OCR can produce many characters of gibberish. Banking
            # labels are a better orientation signal than raw character count.
            labels = re.findall(
                r"\b(?:cnp|seria|nume|prenume|titular|venit|salariu|sold|total|iban|identity|income|statement)\b",
                text.casefold(),
            )
            return len(set(labels)), len(text)

        recognized = False
        for lang in ("ro-RO", "en-US"):
            try:
                res = winocr.recognize_pil_sync(img, lang=lang)
                recognized = True
                lines = [l.get("text", "") for l in res.get("lines", []) if l.get("text")]
                cand = "\n".join(lines).strip() if lines else (res.get("text") or "").strip()
                if quality(cand) > quality(best_text):
                    best_text = cand
                if quality(best_text)[0] >= 2:
                    break
            except Exception:
                continue

        # Bounded rotation attempts, including long-but-unreadable upside-down scans.
        if quality(best_text)[0] < 2:
            candidate_angles = [90, 180, 270, -10, 10, -15, 15]
            for angle in candidate_angles:
                try:
                    rotated = img.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
                    if max(rotated.size) > max_dimension:
                        rotated.thumbnail((max_dimension, max_dimension))
                    lang = next((tag for tag in ("ro-RO", "en-US") if any(
                        item.language_tag == tag for item in OcrEngine.available_recognizer_languages
                    )), "en-US")
                    res = winocr.recognize_pil_sync(rotated, lang=lang)
                    recognized = True
                    lines = [l.get("text", "") for l in res.get("lines", []) if l.get("text")]
                    cand = "\n".join(lines).strip() if lines else (res.get("text") or "").strip()
                    if quality(cand) > quality(best_text):
                        best_text = cand
                    if quality(best_text)[0] >= 2:
                        break
                except Exception:
                    continue

        if not recognized:
            raise ValueError("Windows OCR is unavailable or cannot read this scan.")
        return best_text

    @classmethod
    def extract_text(cls, source: Union[bytes, Path, io.BytesIO]) -> str:
        """Extract all textual content from a PDF input.

        Check every page independently so mixed text/scanned PDFs do not lose pages.
        Never treat user-controlled PDF metadata as a trusted OCR transcript.
        """
        if isinstance(source, bytes):
            stream = io.BytesIO(source)
        elif isinstance(source, (str, Path)):
            stream = open(source, "rb")
        else:
            stream = source

        try:
            reader = pypdf.PdfReader(stream)
            if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
                raise ValueError("Encrypted, empty or excessively long PDFs are not supported.")
            extracted_pages = []

            # 1. First, check native vector text stream
            for page in reader.pages:
                text = (page.extract_text() or "").strip()
                if not text:
                    if len(page.images) > 20:
                        raise ValueError("The page exceeds the embedded-image processing limit.")
                    text = "\n".join(cls._ocr_image_bytes(image.data) for image in page.images).strip()
                if text:
                    extracted_pages.append(text)
                if sum(len(part) for part in extracted_pages) > 200_000:
                    raise ValueError("The document exceeds the extracted-text processing limit.")
            return "\n\n".join(extracted_pages).strip()
        except Exception as exc:
            raise ValueError(f"Failed to extract text from PDF: {exc}") from exc
        finally:
            if isinstance(source, (str, Path)) and not stream.closed:
                stream.close()

    @classmethod
    def extract_image_text(cls, source: Union[bytes, Path, io.BytesIO]) -> str:
        """Extract text directly from an image file (PNG, JPG, TIFF)."""
        if isinstance(source, (str, Path)):
            data = Path(source).read_bytes()
        elif isinstance(source, io.BytesIO):
            data = source.getvalue()
        else:
            data = source
        return cls._ocr_image_bytes(data)

    @staticmethod
    def get_page_count(source: Union[bytes, Path, io.BytesIO]) -> int:
        if isinstance(source, bytes):
            stream = io.BytesIO(source)
        elif isinstance(source, (str, Path)):
            stream = open(source, "rb")
        else:
            stream = source

        try:
            reader = pypdf.PdfReader(stream)
            return len(reader.pages)
        finally:
            if isinstance(source, (str, Path)) and not stream.closed:
                stream.close()
