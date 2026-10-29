"""Check actual file bytes before accepting an applicant upload into local storage."""
import io
import warnings

from PIL import Image
from pypdf import PdfReader

from src.core.errors import InvalidUpload

MAX_PDF_PAGES = 40
MAX_IMAGE_PIXELS = 25_000_000
MIME_SUFFIXES = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}


def validate_document_bytes(content: bytes, mime_type: str, max_bytes: int) -> str:
    """Return the canonical MIME type; do not trust the filename or client header."""
    mime = mime_type.lower().strip()
    if mime == "image/jpg":
        mime = "image/jpeg"
    if mime not in MIME_SUFFIXES:
        raise InvalidUpload("unsupported_media_type", "Only PDF, JPEG and PNG documents are supported.")
    if not content:
        raise InvalidUpload("empty_upload", "The uploaded file is empty.")
    if len(content) > max_bytes:
        raise InvalidUpload("upload_too_large", f"The file exceeds the {max_bytes}-byte upload limit.")

    signatures = {
        "application/pdf": content.startswith(b"%PDF-"),
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
    }
    if not signatures[mime]:
        raise InvalidUpload("file_type_mismatch", "The file contents do not match the declared PDF or image type.")

    try:
        if mime == "application/pdf":
            reader = PdfReader(io.BytesIO(content), strict=True)
            if reader.is_encrypted:
                raise InvalidUpload("invalid_file_format", "Password-protected PDFs cannot be processed; upload an unlocked copy.")
            if not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
                raise InvalidUpload("invalid_file_format", f"A PDF must contain between 1 and {MAX_PDF_PAGES} pages.")
            root = reader.trailer["/Root"]
            names = root.get("/Names", {})
            if hasattr(names, "get_object"):
                names = names.get_object()
            if any(key in root for key in ("/OpenAction", "/AA", "/AF")) or any(
                key in names for key in ("/JavaScript", "/EmbeddedFiles")
            ):
                raise InvalidUpload("invalid_file_format", "PDFs with automatic actions or embedded files are not supported.")
            for page in reader.pages:
                if "/AA" in page:
                    raise InvalidUpload("invalid_file_format", "PDFs with automatic page actions are not supported.")
                for annotation in page.get("/Annots", []):
                    annotation = annotation.get_object()
                    if any(key in annotation for key in ("/A", "/AA", "/FS")) or annotation.get("/Subtype") == "/FileAttachment":
                        raise InvalidUpload("invalid_file_format", "PDFs with interactive actions or attached files are not supported.")
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    expected = "PNG" if mime == "image/png" else "JPEG"
                    if image.format != expected:
                        raise InvalidUpload("file_type_mismatch", "The image contents do not match its declared type.")
                    if image.width * image.height > MAX_IMAGE_PIXELS or getattr(image, "n_frames", 1) != 1:
                        raise InvalidUpload("invalid_file_format", "The image is too large or contains multiple frames.")
                    image.verify()
    except InvalidUpload:
        raise
    except Exception as exc:
        raise InvalidUpload("invalid_file_format", "The document is damaged or cannot be decoded; upload a valid PDF or image.") from exc
    return mime