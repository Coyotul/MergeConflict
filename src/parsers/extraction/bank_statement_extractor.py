"""Extractor for Romanian Bank Account Statements (Extras de Cont Curent)."""

from datetime import date, datetime
import re
from typing import Optional

from src.models.document_processing import ExtractedStatement
from src.parsers.extraction.amounts import parse_document_amount


def _parse_date_ro(d_str: str) -> Optional[date]:
    clean = d_str.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(clean, fmt).date()
        except ValueError:
            continue
    return None


def _parse_money(val_str: str) -> float:
    return parse_document_amount(val_str)


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
        holder_match = re.search(r"TITULAR\s*(?:CONT)?[:\s]+([A-ZĂÂÎȘȚa-zăâîșț\- ]+?)(?=\s*\d{13}|\s*·|\n|CNP|Cod\s*client)", text, re.IGNORECASE)
        if holder_match:
            extracted.account_holder = holder_match.group(1).strip()

        # 3. IBAN
        clean_text_for_iban = re.sub(r"R0(\d{2})", r"RO\1", text.replace(" ", "").upper())
        # Normalize OCR 'e', 'E', 'o', 'O' inside Romanian IBAN digits
        clean_text_for_iban = re.sub(
            r"(RO\d{2}[A-Z]{4})([0-9A-Z]{16})",
            lambda m: m.group(1) + m.group(2).replace("E", "0").replace("O", "0").replace("Q", "0"),
            clean_text_for_iban
        )
        iban_match = re.search(r"(RO\d{2}[A-Z]{4}[0-9A-Z]{16})", clean_text_for_iban)
        if not iban_match:
            iban_match = re.search(r"(?:IBAN|BAN)[:\s]*([A-Z0-9]{24})", clean_text_for_iban)
        if iban_match:
            raw_iban = iban_match.group(1)
            if raw_iban.startswith("R0"):
                raw_iban = "RO" + raw_iban[2:]
            extracted.iban = raw_iban

        # 4. Currency
        currency_match = re.search(r"(?:Moned[aă](?:\s+cont)?|Currency)[:\s]+([A-Z]{3})\b", text, re.IGNORECASE)
        if currency_match:
            extracted.currency = currency_match.group(1).upper()
        elif "EUR" in text and "RON" not in text:
            extracted.currency = "EUR"
        else:
            extracted.currency = "RON"

        # 5. Period
        period_match = re.search(r"Perioada[:\s]*(\d{2}[.\-/]\d{2}[.\-/]\d{4})\s*-\s*(\d{2}[.\-/]\d{2}[.\-/]\d{4})", text, re.IGNORECASE)
        if period_match:
            extracted.period_start = _parse_date_ro(period_match.group(1))
            extracted.period_end = _parse_date_ro(period_match.group(2))

        # 6. Balances
        init_match = re.search(r"(?:Sold inițial|Sold initial)(?:\s*\([^)]*\))?[\s\S]{0,40}?([\d.,]+)\s*(?:RON|lei)?", text, re.IGNORECASE)
        if init_match:
            extracted.initial_balance = _parse_money(init_match.group(1))

        final_match = re.search(r"(?:Sold final|Sold final disponibil)[\s\S]{0,40}?([\d.,]+)\s*(?:RON|lei)?", text, re.IGNORECASE)
        if final_match:
            extracted.closing_balance = _parse_money(final_match.group(1))

        credits_match = re.search(r"(?:Total încasări|Total incasari)[\s\S]{0,40}?\+?([\d.,]+)\s*(?:RON|lei)?", text, re.IGNORECASE)
        if credits_match:
            extracted.total_credits = _parse_money(credits_match.group(1))

        debits_match = re.search(r"(?:Total plăți|Total plati)[\s\S]{0,40}?-?([\d.,]+)\s*(?:RON|lei)?", text, re.IGNORECASE)
        if debits_match:
            extracted.total_debits = _parse_money(debits_match.group(1))
        extracted.balance_fields_complete = all((init_match, final_match, credits_match, debits_match))

        # 7. Salary detection in transaction history
        salary_match = re.search(
            r"(?:VIRAMENT SALARIU|salariu|drepturi salariale)[: \t]*\+([\d.,]+)\s*(?:lei|RON)\b",
            text, re.IGNORECASE,
        )
        if salary_match:
            extracted.detected_salary_deposit = _parse_money(salary_match.group(1))
        elif re.search(r"Tip Opera[tț]i\s*une[^\n]*\nVIRAMENT SALARIU\b", text, re.IGNORECASE):
            # Column-oriented OCR: only the first ledger row, explicitly labelled
            # salary, may be paired with the first amount in the amount column.
            first_amount = re.search(r"Sum[aă]\s*\(RON\)\s*\n\+([\d.,]+)\s*(?:lei|RON)\b", text, re.IGNORECASE)
            if first_amount:
                extracted.detected_salary_deposit = _parse_money(first_amount.group(1))
        # Generic transfers and total credits are not proof of a salary deposit.

        # Never "repair" ledger evidence: inconsistent totals must fail validation.
        # Only an explicit monthly debt total is evidence for the orchestrator's field.
        # Spending totals or absence of loan rows cannot establish zero obligations.
        obligations_match = re.search(
            r"(?:Obliga[tț]ii lunare (?:credite existente|de credit)|"
            r"Total rate lunare(?: credite)?|Existing monthly obligations)"
            r"[ :\t]*([0-9][0-9., ]*)\s*(?:RON|lei)\b",
            text, re.IGNORECASE,
        )
        if obligations_match:
            extracted.existing_monthly_obligations = _parse_money(obligations_match.group(1))

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
