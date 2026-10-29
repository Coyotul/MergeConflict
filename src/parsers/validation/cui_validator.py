"""Romanian CUI / CIF fiscal code validator.

Implements the official testing key algorithm using constant 753217532.
"""

from typing import Tuple


CUI_TEST_KEY = "753217532"


def validate_cui(cui: str) -> Tuple[bool, str]:
    """Validate a Romanian CUI/CIF fiscal identification code.

    Returns:
        (is_valid, reason_or_clean_cui)
    """
    clean = str(cui).strip().upper()
    if clean.startswith("RO"):
        clean = clean[2:].strip()

    if not clean.isdigit():
        return False, "CUI must contain only numeric digits (after optional 'RO' prefix)."

    if len(clean) < 2 or len(clean) > 10:
        return False, f"CUI length must be between 2 and 10 digits; got {len(clean)}."

    control_digit = int(clean[-1])
    body = clean[:-1]

    # Align key from right to left
    total = 0
    body_idx = len(body) - 1
    key_idx = len(CUI_TEST_KEY) - 1

    while body_idx >= 0:
        total += int(body[body_idx]) * int(CUI_TEST_KEY[key_idx])
        body_idx -= 1
        key_idx -= 1

    remainder = (total * 10) % 11
    expected_control = 0 if remainder == 10 else remainder

    if control_digit == expected_control:
        return True, clean
    return False, f"Invalid CUI control digit: expected {expected_control}, got {control_digit}."
