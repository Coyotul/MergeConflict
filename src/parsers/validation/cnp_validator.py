"""Romanian CNP (Cod Numeric Personal) validator and metadata extractor.

Implements the official mathematical validation algorithm using the test key
279146358279, calendar birth date parsing, sex/century mapping and age calculations.
"""

from datetime import date
from typing import NamedTuple, Optional, Tuple


CNP_CONTROL_KEY = (2, 7, 9, 1, 4, 6, 3, 5, 8, 2, 7, 9)

COUNTY_CODES = {
    "01": "Alba", "02": "Arad", "03": "Argeș", "04": "Bacău", "05": "Bihor",
    "06": "Bistrița-Năsăud", "07": "Botoșani", "08": "Brașov", "09": "Brăila", "10": "Buzău",
    "11": "Caraș-Severin", "12": "Cluj", "13": "Constanța", "14": "Covasna", "15": "Dâmbovița",
    "16": "Dolj", "17": "Galați", "18": "Gorj", "19": "Harghita", "20": "Hunedoara",
    "21": "Ialomița", "22": "Iași", "23": "Ilfov", "24": "Maramureș", "25": "Mehedinți",
    "26": "Mureș", "27": "Neamț", "28": "Olt", "29": "Prahova", "30": "Satu Mare",
    "31": "Sălaj", "32": "Sibiu", "33": "Suceava", "34": "Teleorman", "35": "Timiș",
    "36": "Tulcea", "37": "Vaslui", "38": "Vâlcea", "39": "Vrancea", "40": "București",
    "41": "București Sector 1", "42": "București Sector 2", "43": "București Sector 3",
    "44": "București Sector 4", "45": "București Sector 5", "46": "București Sector 6",
    "51": "Călărași", "52": "Giurgiu",
}


class CnpMetadata(NamedTuple):
    is_valid_format: bool
    is_valid_checksum: bool
    is_valid_date: bool
    gender: Optional[str]
    birth_date: Optional[date]
    county_code: Optional[str]
    county_name: Optional[str]
    age_years: Optional[int]
    error_message: Optional[str]


def compute_cnp_checksum(first_12_digits: str) -> int:
    """Calculate the 13th control digit according to the Romanian national algorithm."""
    total = sum(int(digit) * weight for digit, weight in zip(first_12_digits, CNP_CONTROL_KEY))
    remainder = total % 11
    return 1 if remainder == 10 else remainder


def parse_cnp(cnp: str, as_of: Optional[date] = None) -> CnpMetadata:
    """Parse and validate a Romanian CNP string."""
    clean = cnp.strip()
    if as_of is None:
        as_of = date.today()

    if not clean.isdigit() or len(clean) != 13:
        return CnpMetadata(
            is_valid_format=False, is_valid_checksum=False, is_valid_date=False,
            gender=None, birth_date=None, county_code=None, county_name=None,
            age_years=None, error_message="CNP must consist of exactly 13 digits.",
        )

    s = int(clean[0])
    aa = int(clean[1:3])
    ll = int(clean[3:5])
    zz = int(clean[5:7])
    county = clean[7:9]
    control_digit = int(clean[12])

    if s == 0:
        return CnpMetadata(
            is_valid_format=False, is_valid_checksum=False, is_valid_date=False,
            gender=None, birth_date=None, county_code=None, county_name=None,
            age_years=None, error_message="First digit cannot be 0.",
        )

    # Determine century and gender
    century_map = {
        1: (1900, "M"), 2: (1900, "F"),
        3: (1800, "M"), 4: (1800, "F"),
        5: (2000, "M"), 6: (2000, "F"),
        7: (1900, "M"), 8: (1900, "F"),  # Residents
    }

    if s not in century_map:
        return CnpMetadata(
            is_valid_format=False, is_valid_checksum=False, is_valid_date=False,
            gender=None, birth_date=None, county_code=None, county_name=None,
            age_years=None, error_message=f"Unsupported first digit '{s}'.",
        )

    century_base, gender = century_map[s]
    year = century_base + aa

    # Validate calendar date
    try:
        birth_date = date(year, ll, zz)
        is_valid_date = True
    except ValueError:
        return CnpMetadata(
            is_valid_format=True, is_valid_checksum=False, is_valid_date=False,
            gender=gender, birth_date=None, county_code=county, county_name=COUNTY_CODES.get(county),
            age_years=None, error_message=f"Invalid birth calendar date: {year}-{ll:02d}-{zz:02d}.",
        )

    # Calculate age
    age = as_of.year - birth_date.year - ((as_of.month, as_of.day) < (birth_date.month, birth_date.day))

    # Validate checksum
    expected_checksum = compute_cnp_checksum(clean[:12])
    is_valid_checksum = (control_digit == expected_checksum)

    county_name = COUNTY_CODES.get(county, "Unknown / Foreign")

    return CnpMetadata(
        is_valid_format=True,
        is_valid_checksum=is_valid_checksum,
        is_valid_date=is_valid_date,
        gender=gender,
        birth_date=birth_date,
        county_code=county,
        county_name=county_name,
        age_years=age,
        error_message=None if is_valid_checksum else f"Invalid control digit: got {control_digit}, expected {expected_checksum}.",
    )
