"""Text normalization utilities."""
import re
import unicodedata


def normalize_text(text: str) -> str:
    """Normalize text: NFC, fix diacritics, collapse whitespace, trim lines.

    Applies:
    - Unicode NFC normalization
    - Maps incorrect cedilla diacritics to correct comma-below forms (ş→ș, ţ→ț)
    - Replaces NBSP with regular space
    - Collapses runs of spaces and tabs to single space
    - Trims whitespace from each line
    - Keeps single newlines
    - Collapses 3+ newlines to 2
    """
    # Apply NFC normalization
    text = unicodedata.normalize("NFC", text)

    # Fix Romanian diacritics (cedilla → comma below)
    diacritic_map = str.maketrans({
        "ş": "ș",
        "ţ": "ț",
        "Ş": "Ș",
        "Ţ": "Ț",
    })
    text = text.translate(diacritic_map)

    # Replace NBSP with regular space
    text = text.replace("\xa0", " ")

    # Collapse runs of spaces and tabs to single space
    text = re.sub(r"[ \t]+", " ", text)

    # Trim each line
    lines = text.split("\n")
    lines = [line.strip() for line in lines]
    text = "\n".join(lines)

    # Collapse 3+ newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text
