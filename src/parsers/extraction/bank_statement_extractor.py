"""Extractor for Romanian Bank Account Statements (Extras de Cont Curent)."""

from datetime import date, datetime
import re
from typing import Optional

from src.models.document_processing import ExtractedStatement


def _parse_date_ro(d_str: str) -> Optional[date]:
    clean = d_str.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(clean, fmt).date()
        except ValueError:
            continue
    return None


def _parse_money(val_str: str) -> float:
    clean = val_str.replace(" ", "").replace("lei", "").replace("RON", "").replace("+", "").replace("-", "").strip()
    clean = clean.replace(".", "").replace(",", ".")
    try:
        return float(clean)
    except ValueError:
        return 0.0


class BankStatementExtractor:
    """Extracts structured banking figures and transaction signals from an Extras de Cont."""

    @classmethod
    def extract(cls, text: str) -> ExtractedStatement:
        extracted = ExtractedStatement(raw_text=text)

        # 1. Bank Name
        if "RAIFFEISEN" in text.upper():
            extracted.bank_name = "RAIFFEISEN BANK S.A."
        elif "BANCA TRANSILVANIA" in text.upper():
            extracted.bank_name = "BANCA TRANSILVANIA S.A."
        elif "BCR" in text.upper() or "BANCA COMERCIALA ROMANA" in text.upper():
            extracted.bank_name = "BANCA COMERCIALĂ ROMÂNĂ S.A."
        elif "BRD" in text.upper():
            extracted.bank_name = "BRD GROUPE SOCIETE GENERALE"
        elif "ING" in text.upper():
            extracted.bank_name = "ING BANK N.V. AMSTERDAM"
        else:
            extracted.bank_name = "Instituție Bancară Parteneră"

        # 2. Account Holder
        holder_match = re.search(r"TITULAR CONT[:\s]+([A-ZĂÂÎȘȚ\- ]+?)(?=\n|CNP|Cod client)", text, re.IGNORECASE)
        if holder_match:
            extracted.account_holder = holder_match.group(1).strip()

        # 3. IBAN
        iban_match = re.search(r"\b(RO\d{2}[A-Z]{4}[0-9A-Z]{16})\b", text.replace(" ", ""))
        if iban_match:
            extracted.iban = iban_match.group(1)

        # 4. Currency
        if "EUR" in text and "RON" not in text:
            extracted.currency = "EUR"
        else:
            extracted.currency = "RON"

        # 5. Period
        period_match = re.search(r"Perioada[:\s]*(\d{2}[.\-/]\d{2}[.\-/]\d{4})\s*-\s*(\d{2}[.\-/]\d{2}[.\-/]\d{4})", text, re.IGNORECASE)
        if period_match:
            extracted.period_start = _parse_date_ro(period_match.group(1))
            extracted.period_end = _parse_date_ro(period_match.group(2))

        # 6. Balances
        init_match = re.search(r"(?:Sold inițial|Sold initial)[^\n\d]*([\d.,]+)\s*(?:RON|lei)?", text, re.IGNORECASE)
        if init_match:
            extracted.initial_balance = _parse_money(init_match.group(1))

        final_match = re.search(r"(?:Sold final|Sold final disponibil)[^\n\d]*([\d.,]+)\s*(?:RON|lei)?", text, re.IGNORECASE)
        if final_match:
            extracted.closing_balance = _parse_money(final_match.group(1))

        credits_match = re.search(r"(?:Total încasări|Total incasari)[^\n\d]*\+?([\d.,]+)\s*(?:RON|lei)?", text, re.IGNORECASE)
        if credits_match:
            extracted.total_credits = _parse_money(credits_match.group(1))

        debits_match = re.search(r"(?:Total plăți|Total plati)[^\n\d]*-?([\d.,]+)\s*(?:RON|lei)?", text, re.IGNORECASE)
        if debits_match:
            extracted.total_debits = _parse_money(debits_match.group(1))

        # 7. Salary detection in transaction history
        salary_match = re.search(r"(?:VIRAMENT SALARIU|salariu|drepturi salariale)[^\n]*?\+([\d.,]+)\s*(?:lei|RON)?", text, re.IGNORECASE)
        if salary_match:
            extracted.detected_salary_deposit = _parse_money(salary_match.group(1))

        # 8. Transactions Count
        tx_count_match = re.search(r"Număr total operațiuni[^\d]*(\d+)", text, re.IGNORECASE)
        if tx_count_match:
            extracted.transactions_count = int(tx_count_match.group(1))
        else:
            # Estimate from date occurrences
            extracted.transactions_count = len(re.findall(r"\b\d{2}\.\d{2}\.202\d\b", text))

        # Confidence score
        score = 0.0
        if extracted.iban: score += 0.3
        if extracted.account_holder: score += 0.25
        if extracted.closing_balance > 0 or extracted.initial_balance > 0: score += 0.25
        if extracted.period_end: score += 0.1
        if extracted.detected_salary_deposit: score += 0.1
        extracted.confidence_score = round(min(1.0, score), 2)

        return extracted
