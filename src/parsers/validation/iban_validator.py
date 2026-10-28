"""Romanian IBAN validator using ISO 7064 MOD 97-10 check."""

import re
from typing import Tuple


RO_IBAN_PATTERN = re.compile(r"^RO\d{2}[A-Z]{4}[0-9A-Z]{16}$")

KNOWN_RO_BANKS = {
    "RZBR": "Raiffeisen Bank",
    "BTRL": "Banca Transilvania",
    "RNCB": "Banca Comercială Română (BCR)",
    "BRDE": "BRD Groupe Société Générale",
    "INGB": "ING Bank România",
    "BACX": "UniCredit Bank",
    "TREZ": "Trezoreria Statului",
    "CECE": "CEC Bank",
    "OTPV": "OTP Bank",
    "WBAN": "Alpha Bank",
}


def validate_iban(iban: str) -> Tuple[bool, str]:
    """Validate a Romanian IBAN account number.

    Returns:
        (is_valid, reason_or_bank_name)
    """
    clean = re.sub(r"[\s\-]+", "", str(iban).upper())

    if len(clean) != 24:
        return False, f"Romanian IBAN must have exactly 24 characters; got {len(clean)}."

    if not clean.startswith("RO"):
        return False, "Romanian IBAN must start with country code 'RO'."

    if not RO_IBAN_PATTERN.match(clean):
        return False, "IBAN does not conform to the Romanian IBAN format (RO + 2 digits + 4 bank letters + 16 characters)."

    # Rearrange: first 4 characters to end
    rearranged = clean[4:] + clean[:4]

    # Convert letters to digits: A=10, ..., Z=35
    numeric_str = ""
    for ch in rearranged:
        if ch.isdigit():
            numeric_str += ch
        elif "A" <= ch <= "Z":
            numeric_str += str(ord(ch) - ord("A") + 10)
        else:
            return False, f"Invalid character '{ch}' in IBAN."

    # Compute MOD 97
    if int(numeric_str) % 97 != 1:
        return False, "IBAN checksum validation failed (MOD 97 check)."

    bank_code = clean[4:8]
    bank_name = KNOWN_RO_BANKS.get(bank_code, f"Instituție Bancară ({bank_code})")
    return True, bank_name
