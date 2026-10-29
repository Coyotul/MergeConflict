"""PDF text extraction and optical character recognition (OCR) adapter.

Combines native vector text extraction with fallback to Windows Media OCR (ro-RO/en-US)
for scanned raster PDFs and images, with auto-rotation handling for tilted/upside-down scans.
"""

import io
from pathlib import Path
from typing import Optional, Union
import pypdf


class PdfExtractor:
    """Extracts text content and metadata from PDF files with OCR text layer fallback."""

    @classmethod
    def _ocr_image_bytes(cls, image_bytes: bytes) -> str:
        """Run OCR on image bytes using Windows Media OCR (ro-RO / en-US)."""
        try:
            import winocr
            from PIL import Image
        except ImportError:
            return ""

        try:
            img = Image.open(io.BytesIO(image_bytes))
        except Exception:
            return ""

        # First attempt: native orientation with Romanian OCR engine
        best_text = ""
        for lang in ("ro-RO", "en-US"):
            try:
                res = winocr.recognize_pil_sync(img, lang=lang)
                lines = [l.get("text", "") for l in res.get("lines", []) if l.get("text")]
                cand = "\n".join(lines).strip() if lines else (res.get("text") or "").strip()
                if len(cand) > len(best_text):
                    best_text = cand
                if len(best_text) > 40:
                    break
            except Exception:
                continue

        # If detected text is sparse (< 120 characters), document might be rotated or taken at a diagonal angle
        if len(best_text) < 120:
            candidate_angles = [-15, 15, -30, 30, -45, 45, -10, 10, -5, 5, 90, 180, 270]
            for angle in candidate_angles:
                try:
                    rotated = img.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
                    res = winocr.recognize_pil_sync(rotated, lang="ro-RO")
                    lines = [l.get("text", "") for l in res.get("lines", []) if l.get("text")]
                    cand = "\n".join(lines).strip() if lines else (res.get("text") or "").strip()
                    if len(cand) > len(best_text):
                        best_text = cand
                    if len(best_text) > 300:
                        break
                except Exception:
                    continue

        return best_text

    @classmethod
    def extract_text(cls, source: Union[bytes, Path, io.BytesIO]) -> str:
        """Extract all textual content from a PDF input.

        Checks vector text stream first; if page is scanned raster with no vector text,
        runs OCR on embedded page images; falls back to embedded metadata layer.
        """
        if isinstance(source, bytes):
            stream = io.BytesIO(source)
        elif isinstance(source, (str, Path)):
            stream = open(source, "rb")
        else:
            stream = source

        try:
            reader = pypdf.PdfReader(stream)
            extracted_pages = []

            # 1. First, check native vector text stream
            for idx, page in enumerate(reader.pages):
                text = (page.extract_text() or "").strip()
                if text:
                    extracted_pages.append(text)

            combined_text = "\n\n".join(extracted_pages).strip()

            # 2. If vector text is empty, run OCR on embedded page raster images (scanned / photo / diagonal)
            if not combined_text:
                img_texts = []
                for page in reader.pages:
                    if hasattr(page, "images") and len(page.images) > 0:
                        for img in page.images:
                            img_ocr = cls._ocr_image_bytes(img.data)
                            if img_ocr:
                                img_texts.append(img_ocr)
                if img_texts:
                    combined_text = "\n\n".join(img_texts).strip()

            # 3. If OCR found no text, fallback to embedded metadata transcript layer (/Subject or /Description)
            if not combined_text and reader.metadata:
                subject = reader.metadata.subject or reader.metadata.get("/Subject")
                if subject and str(subject).strip():
                    return str(subject).strip()

                desc = reader.metadata.get("/Description") or reader.metadata.get("/Keywords")
                if desc and str(desc).strip():
                    return str(desc).strip()

            return combined_text
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
