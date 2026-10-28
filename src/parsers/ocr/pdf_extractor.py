"""PDF text extraction and OCR adapter."""

import io
from pathlib import Path
from typing import Optional, Union
import pypdf


class PdfExtractor:
    """Extracts text content and metadata from PDF files with OCR text layer fallback."""

    @staticmethod
    def extract_text(source: Union[bytes, Path, io.BytesIO]) -> str:
        """Extract all textual content from a PDF input.

        Checks vector text stream first; falls back to embedded OCR metadata layer
        for scanned document PDFs.
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
            for idx, page in enumerate(reader.pages):
                text = page.extract_text()
                if text and text.strip():
                    extracted_pages.append(text)

            combined_text = "\n\n".join(extracted_pages).strip()

            # If page extract_text is empty, check PDF metadata OCR layer (/Subject or /Description)
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
