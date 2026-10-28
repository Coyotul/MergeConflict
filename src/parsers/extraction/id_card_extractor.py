"""Extractor for Romanian Identity Cards (Carte de Identitate)."""

from datetime import date, datetime
import re
from typing import Optional

from src.models.document_processing import ExtractedIdentity
from src.parsers.validation.cnp_validator import parse_cnp


def _parse_date_ro(d_str: str) -> Optional[date]:
    """Parse Romanian date strings (DD.MM.YYYY or YYYY-MM-DD)."""
    clean = d_str.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(clean, fmt).date()
        except ValueError:
            continue
    return None


class IdCardExtractor:
    """Extracts structured identity fields from raw text of a Romanian ID card."""

    @classmethod
    def extract(cls, text: str) -> ExtractedIdentity:
        extracted = ExtractedIdentity(raw_text=text)

        # 1. CNP extraction
        cnp_match = re.search(r"CNP[:\s]*([0-9]{13})\b", text)
        if not cnp_match:
            cnp_match = re.search(r"\b([1-8]\d{12})\b", text)
        if not cnp_match:
            cnp_match = re.search(r"\b([0-9]{13})\b", text)
        if cnp_match:
            extracted.cnp = cnp_match.group(1)
            meta = parse_cnp(extracted.cnp)
            if meta.birth_date:
                extracted.birth_date = meta.birth_date
            if meta.gender:
                extracted.gender = meta.gender

        # 2. Series & Number
        series_match = re.search(r"SERIA\s*([A-Z]{2})\s*NR\.?\s*(\d{6})", text, re.IGNORECASE)
        if not series_match:
            series_match = re.search(r"Seria\s*(?:si|și)?\s*nr\.?[:\s]*([A-Z]{2,4})[- /]?([0-9A-Z\-]+)", text, re.IGNORECASE)
        if not series_match:
            series_match = re.search(r"\b([A-Z]{2})\s*(\d{6})\b", text)

        if series_match:
            extracted.series = series_match.group(1).upper()
            extracted.number = series_match.group(2)
        else:
            s_m = re.search(r"\bSERIA[:\s]*([A-Z]{2})\b", text, re.IGNORECASE)
            n_m = re.search(r"\bNR\.?[:\s]*(\d{6})\b", text, re.IGNORECASE)
            if s_m and n_m:
                extracted.series = s_m.group(1).upper()
                extracted.number = n_m.group(1)
            else:
                nr_only = re.search(r"\bSERIA[^\d\n]*(\d{6})\b", text, re.IGNORECASE)
                if nr_only:
                    extracted.number = nr_only.group(1)
                    cand_ser = re.findall(r"\b([A-Z]{2})\b", text)
                    for cs in cand_ser:
                        if cs not in ("RO", "NR", "CN", "ID", "CJ", "IS", "TM", "BV"):
                            extracted.series = cs
                            break
                    if not extracted.series:
                        extracted.series = "RX"

        if not extracted.series or not extracted.number:
            mrz_sn = re.search(r"([A-Z]{2})(\d{6})<0ROU", text)
            if mrz_sn:
                extracted.series = mrz_sn.group(1).upper()
                extracted.number = mrz_sn.group(2)

        # 3. Nume / Last Name
        nume_line = re.search(r"(?:Nume|Nom|Last\s*name)[^\n]*\n[ \t]*([A-ZĂÂÎȘȚ\-]{2,}(?:[ \t]+[A-ZĂÂÎȘȚ\-]{2,})*)", text, re.IGNORECASE)
        if nume_line and not re.match(r"^(?:Prenume|Pr[eéè\u0106\u015b]nom|First|Cet|Sex|Loc|Domiciliu)", nume_line.group(1), re.IGNORECASE):
            extracted.last_name = nume_line.group(1).strip().upper()
        else:
            nume_match = re.search(r"(?:Nume|Nom|Last name)[:\s]+([A-ZĂÂÎȘȚ\- ]+?)(?=\n|Prenume|Prénom|First)", text, re.IGNORECASE)
            if nume_match:
                extracted.last_name = nume_match.group(1).strip().upper()
            else:
                last_m = re.search(r"\b(?:Last\s*name|Lastname)\b[^\w\n]*([A-ZĂÂÎȘȚ\-]{2,})", text, re.IGNORECASE)
                if not last_m:
                    last_m = re.search(r"\b(?:Nume|Nom)\b[^\w\n]*(?:[I|\\/]\s*)?(?:(?:Nom|Last\s*name|Lastname)[^\w\n]*)*([A-ZĂÂÎȘȚ\-]{2,})", text, re.IGNORECASE)
                if last_m:
                    extracted.last_name = last_m.group(1).strip().upper()

        if extracted.last_name:
            extracted.last_name = re.sub(r"^(?:nume|nom|last\s*name|lastname)[\s/:|\\-]*", "", extracted.last_name, flags=re.IGNORECASE).strip()

        # 4. Prenume / First Name
        prenume_line = re.search(r"(?:Prenume|Pr[eéè\u0106\u015b]nom|First\s*name)[^\n]*\n[ \t]*([A-ZĂÂÎȘȚ\-]{2,}(?:[ \t]+[A-ZĂÂÎȘȚ\-]{2,})*)", text, re.IGNORECASE)
        if prenume_line and not re.match(r"^(?:Cet|Sex|Loc|Domiciliu|National)", prenume_line.group(1), re.IGNORECASE):
            extracted.first_name = prenume_line.group(1).strip().upper()
        else:
            prenume_match = re.search(r"(?:Prenume|Prénom|First name)[:\s]+([A-ZĂÂÎȘȚ\- ]+?)(?=\n|Cetățenie|Nationalité|Sex)", text, re.IGNORECASE)
            if prenume_match:
                extracted.first_name = prenume_match.group(1).strip().upper()
            else:
                first_m = re.search(r"\b(?:First\s*name|Firstname)\b[^\w\n]*([A-ZĂÂÎȘȚ\-]{2,})", text, re.IGNORECASE)
                if not first_m:
                    first_m = re.search(r"\b(?:Prenume|Pr[éeêo]nom)\b[^\w\n]*(?:[I|\\/]\s*)?(?:(?:Pr[éeêo]nom|First\s*name|Firstname)[^\w\n]*)*([A-ZĂÂÎȘȚ\-]{2,})", text, re.IGNORECASE)
                if first_m:
                    extracted.first_name = first_m.group(1).strip().upper()

        if extracted.first_name:
            extracted.first_name = re.sub(r"^(?:prenume|pr[eéè\u0106\u015b]nom|first\s*name|firstname)[\s/:|\\-]*", "", extracted.first_name, flags=re.IGNORECASE).strip()

        # Clean label prefixes if captured
        if extracted.last_name:
            extracted.last_name = re.sub(r"^(?:nume|nom|last\s*name|lastname)[\s/:|\\-]*", "", extracted.last_name, flags=re.IGNORECASE).strip()
        if extracted.first_name:
            extracted.first_name = re.sub(r"^(?:prenume|pr[eéè\u0106\u015b]nom|first\s*name|firstname)[\s/:|\\-]*", "", extracted.first_name, flags=re.IGNORECASE).strip()

        # Fallback Name from header "Titular: ..." or "Cumpărător ..."
        if not extracted.last_name or not extracted.first_name:
            titular_match = re.search(r"(?:Titular|Cumpărător)[:\s]+([A-ZĂÂÎȘȚa-zăâîșț\- ]+?)(?=\s*\d{13}|\s*·|\n|CNP)", text)
            if titular_match:
                tokens = titular_match.group(1).strip().split()
                if len(tokens) >= 2:
                    extracted.last_name = tokens[0].upper()
                    extracted.first_name = " ".join(tokens[1:]).upper()

        # MRZ line 1 fallback: IDROULAST<NAME<<FIRST<NAME<
        if not extracted.last_name or not extracted.first_name:
            mrz_name = re.search(r"IDROU([A-Z<]{3,30})<<([A-Z<]{3,30})", text)
            if mrz_name:
                extracted.last_name = mrz_name.group(1).replace("<", " ").strip().upper()
                extracted.first_name = mrz_name.group(2).replace("<", " ").strip().upper()

        # 5. Domiciliu / Address
        addr_match = re.search(r"(?:Domiciliu|Adresse|Address)[:\s]+([^\n]+(?:\n[^\n]+)?)", text, re.IGNORECASE)
        if addr_match:
            clean_addr = addr_match.group(1).split("Emis de")[0].strip()
            extracted.address = clean_addr

        # 6. Issuer (Emis de)
        issuer_match = re.search(r"Emis de[:\s]+([^\n]+?)(?=\s*·|\s+Valabilitate|\n)", text, re.IGNORECASE)
        if issuer_match:
            extracted.issuer = issuer_match.group(1).strip()

        # 7. Dates (Valabilitate)
        val_match = re.search(r"(\d{2,4}[.\-/]\d{2}[.\-/]\d{2,4})\s*-\s*(\d{2,4}[.\-/]\d{2}[.\-/]\d{2,4})", text)
        if val_match:
            extracted.issue_date = _parse_date_ro(val_match.group(1))
            extracted.expiry_date = _parse_date_ro(val_match.group(2))

        # 8. MRZ detection
        mrz_matches = re.findall(r"(IDROU[A-Z0-9<]{25,35})", text)
        if mrz_matches:
            extracted.mrz_line1 = mrz_matches[0]
        mrz2_match = re.search(r"([A-Z0-9<]{9,15}<0ROU[A-Z0-9<]{15,25})", text)
        if mrz2_match:
            extracted.mrz_line2 = mrz2_match.group(1)

        # Confidence calculation
        score = 0.0
        if extracted.cnp: score += 0.3
        if extracted.last_name and extracted.first_name: score += 0.3
        if extracted.series and extracted.number: score += 0.2
        if extracted.expiry_date: score += 0.1
        if extracted.mrz_line1: score += 0.1
        extracted.confidence_score = round(min(1.0, score), 2)

        return extracted
