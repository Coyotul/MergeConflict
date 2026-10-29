"""Strict monetary parsing for document evidence: malformed text is not zero income/debt."""
from decimal import Decimal
import re


def parse_document_amount(raw: str) -> float:
    """Support explicit Romanian/English separators; reject malformed or excessive figures."""
    value = re.sub(r"\s+", "", raw)
    if not re.fullmatch(r"[+-]?\d[\d.,]*", value):
        raise ValueError("The document amount is not a valid number.")
    sign = "-" if value.startswith("-") else ""
    value = value.lstrip("+-")
    if "." in value and "," in value:
        decimal_separator = "," if value.rfind(",") > value.rfind(".") else "."
        group_separator = "." if decimal_separator == "," else ","
        whole, fractional = value.rsplit(decimal_separator, 1)
        if not re.fullmatch(r"\d{1,3}(?:" + re.escape(group_separator) + r"\d{3})+|\d+", whole):
            raise ValueError("The document amount has inconsistent thousands separators.")
        if not re.fullmatch(r"\d{1,2}", fractional):
            raise ValueError("The document amount has invalid decimal precision.")
        value = whole.replace(group_separator, "") + "." + fractional
    elif "." in value or "," in value:
        separator = "." if "." in value else ","
        pieces = value.split(separator)
        if len(pieces) == 2 and re.fullmatch(r"\d+", pieces[0]) and re.fullmatch(r"\d{1,2}", pieces[1]):
            value = ".".join(pieces)
        elif re.fullmatch(r"\d{1,3}(?:" + re.escape(separator) + r"\d{3})+", value):
            value = value.replace(separator, "")
        else:
            raise ValueError("The document amount has inconsistent separators.")
    amount = Decimal(sign + value)
    if not amount.is_finite() or abs(amount) >= Decimal("1000000000000"):
        raise ValueError("The document amount is outside the supported range.")
    return float(amount)