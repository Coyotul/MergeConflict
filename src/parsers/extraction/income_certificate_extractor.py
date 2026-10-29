"""Extractor for Romanian Salary & Income Certificates (Adeverință de Venit)."""

from datetime import date, datetime
import re
from typing import Any, Dict, List, Optional

from src.models.document_processing import ExtractedIncome
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
    """Parse Romanian currency format: 8.500,00 -> 8500.0."""
    return parse_document_amount(val_str)


class IncomeCertificateExtractor:
    """Extracts structured income details from text of an Adeverință de Venit."""

    @classmethod
    def extract(cls, text: str) -> ExtractedIncome:
        extracted = ExtractedIncome(raw_text=text)

        # 1. Employer Name (usually top header line)
        emp_match = re.search(r"^([^\n]+(?:S\.R\.L\.|S\.A\.|SRL|SA|Studio|Solutions|Logistics|Systems)[^\n]*)", text, re.MULTILINE | re.IGNORECASE)
        if emp_match:
            raw_emp = emp_match.group(1).strip()
            extracted.employer_name = re.split(r"(?:C\.?U\.?I|C\.?I\.?F|CLI|Nr\.?\s*Reg|Sediu)", raw_emp, flags=re.IGNORECASE)[0].strip(" -:;,._")

        # 2. Employer CUI / CIF
        cui_match = re.search(r"(?:C[\.\s_]*[UUI1L][\.\s_]*[II1L]|C[\.\s_]*I[\.\s_]*F|CUI|CIF)[^0-9a-zA-Z\n]*(?:RO|R0)?\s*(\d{2,10})", text, re.IGNORECASE)
        if cui_match:
            extracted.employer_cui = cui_match.group(1).strip()
        if not extracted.employer_cui:
            stamp_cui = re.search(r"\b(?:RO|R0)\s*(\d{6,10})\b", text, re.IGNORECASE)
            if stamp_cui:
                extracted.employer_cui = stamp_cui.group(1).strip()

        # Reg Com
        reg_match = re.search(r"Nr\.?\s*Reg\.?\s*Com\.?[:\s]*([JjFf]\d{2}/\d+/\d{4})", text, re.IGNORECASE)
        if reg_match:
            extracted.employer_reg_com = reg_match.group(1).strip()

        # 3. Employee CNP
        cnp_match = re.search(r"CNP[:\s]*([1-8]\d{12})\b", text)
        if cnp_match:
            extracted.employee_cnp = cnp_match.group(1)

        # 4. Employee Name
        name_match = re.search(r"(?:dl[./\]\s]*dna[.]?|salariatul|angajatul|salariat(?:ul)?)\s+([A-ZĂÂÎȘȚ\- ]+?)(?=,|\s+având|\s+CNP)", text, re.IGNORECASE)
        if name_match:
            extracted.employee_name = name_match.group(1).strip()

        # 5. Contract type
        if re.search(r"nedeterminat[aă]", text, re.IGNORECASE):
            extracted.contract_type = "NEDETERMINATĂ"
        elif re.search(r"determinat[aă]", text, re.IGNORECASE):
            extracted.contract_type = "DETERMINATĂ"

        # 6. Job title
        job_match = re.search(r"funcția de\s+([^\n,.]+?)(?=\.|\n|,)", text, re.IGNORECASE)
        if job_match:
            extracted.job_title = job_match.group(1).strip()

        # 7. Employment start date
        start_match = re.search(r"(?:din data de|CIM nr\.[^\n]+din)\s*(\d{2,4}[.\-/]\d{2}[.\-/]\d{2,4})", text, re.IGNORECASE)
        if start_match:
            extracted.employment_start_date = _parse_date_ro(start_match.group(1))
        else:
            start_match = re.search(
                r"(?:Contractului Individual de Munc[aă]|CIM)[^\n]{0,50}?"
                r"(?:/|din)\s*(\d{2,4}[.\-/]\d{2}[.\-/]\d{2,4})",
                text, re.IGNORECASE,
            )
            if start_match:
                extracted.employment_start_date = _parse_date_ro(start_match.group(1))

        # 8. Date of issue
        issue_match = re.search(r"Data\s*emiterii[^\d\n]*(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})", text, re.IGNORECASE)
        if not issue_match:
            issue_match = re.search(r"\b(\d{1,2}[.\-/]\d{1,2}\.202\d)\b", text)
        if issue_match:
            extracted.issue_date = _parse_date_ro(issue_match.group(1))

        # 9. Income amounts (Average / Net / Gross)
        avg_match = re.search(r"(?:MEDIA VENITULUI NET|Media venitului net|Venit net mediu)[:\s]*([\d.,]+)\s*(?:RON|lei)?", text, re.IGNORECASE)
        if avg_match:
            extracted.average_net_income = _parse_money(avg_match.group(1))

        net_match = re.search(r"Venit(?:ul)?\s+net\s+(?:lunar|lunar mediu)(?:\s+de)?[:\s]+([\d.,]+)\s*(?:RON|lei)\b", text, re.IGNORECASE)
        if net_match:
            extracted.monthly_net_income = _parse_money(net_match.group(1))
        # For column-oriented OCR, amounts under the explicit net-income column
        # are evidence; arbitrary last monetary figures or gross pay are not.
        net_column = re.search(
            r"Venit Net [ÎI]ncasat\s*\n"
            r"((?:[\d.,]+\s*(?:lei|RON)\s*\n)+)", text, re.IGNORECASE,
        )
        net_matches = re.findall(r"([\d.,]+)\s*(?:lei|RON)\b", net_column.group(1)) if net_column else []
        if net_matches:
            parsed_amounts = [_parse_money(m) for m in net_matches]
            if len(set(parsed_amounts)) == 1:
                extracted.monthly_net_income = extracted.monthly_net_income or parsed_amounts[0]

        if extracted.average_net_income and not extracted.monthly_net_income:
            extracted.monthly_net_income = extracted.average_net_income
        elif extracted.monthly_net_income and not extracted.average_net_income:
            extracted.average_net_income = extracted.monthly_net_income

        # Confidence calculation
        score = 0.0
        if extracted.employer_cui: score += 0.25
        if extracted.employee_cnp: score += 0.25
        if extracted.monthly_net_income > 0: score += 0.3
        if extracted.contract_type: score += 0.1
        if extracted.issue_date: score += 0.1
        extracted.confidence_score = round(min(1.0, score), 2)

        return extracted
