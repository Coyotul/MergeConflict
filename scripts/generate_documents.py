#!/usr/bin/env python3
"""CLI tool for generating synthetic banking test documents.

Generates realistic identity cards (buletin), proof of income certificates (adeverință venit)
and bank account statements (extras de cont) in PDF and PNG formats for testing.

Examples:
    # Generate default test suite (Alex Morgan + primary personas)
    python scripts/generate_documents.py

    # Generate documents only for Alex Morgan (the main frontend test account)
    python scripts/generate_documents.py --customer alex_morgan

    # Generate for a specific scenario persona
    python scripts/generate_documents.py --persona DSTI_39

    # Generate by CNP from credit_sources.db
    python scripts/generate_documents.py --cnp 1790420000031

    # Generate only PDFs in a custom directory
    python scripts/generate_documents.py --format pdf --output-dir data/my_docs
"""

import argparse
from pathlib import Path
import sys

# Ensure repository root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.document_generation.generator import (
    DEFAULT_DB_PATH,
    DEFAULT_OUTPUT_DIR,
    PRESET_PROFILES,
    generate_document_suite,
    generate_documents_for_profile,
    load_profile_from_db,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate synthetic Romanian banking documents (ID card, income certificate, bank statement)."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to save generated documents (default: data/synthetic/documents)",
    )
    parser.add_argument(
        "--customer",
        type=str,
        default=None,
        help="Generate for a specific preset profile (e.g. alex_morgan, dsti_39, income_no_debt)",
    )
    parser.add_argument(
        "--persona",
        type=str,
        default=None,
        help="Generate for a persona tag from credit_sources.db (e.g. DSTI_39, INCOME_NO_DEBT)",
    )
    parser.add_argument(
        "--cnp",
        type=str,
        default=None,
        help="Generate for a specific synthetic CNP from credit_sources.db",
    )
    parser.add_argument(
        "--format",
        choices=["pdf", "png", "both"],
        default="pdf",
        help="Output format: pdf, png, or both (default: pdf)",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Path to credit_sources.db (default: data/local/credit_sources.db)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available presets and exit",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.list:
        print("\nAvailable preset customer profiles:")
        for key, p in PRESET_PROFILES.items():
            print(f"  - {key:<24} | {p.full_name:<20} | CNP: {p.cnp} | Net: {p.monthly_net_income:,.2f} RON ({p.persona_tag})")
        return 0

    include_pdf = args.format in ("pdf", "both")
    include_png = args.format in ("png", "both")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Custom lookup by CNP or Persona
    if args.cnp or args.persona:
        identifier = args.cnp or args.persona
        print(f"Looking up '{identifier}' in credit sources database ({args.db_path})...")
        profile = load_profile_from_db(identifier, db_path=args.db_path)
        if not profile:
            # Fallback to presets if available
            lower_id = identifier.lower().replace("-", "_")
            profile = PRESET_PROFILES.get(lower_id)

        if not profile:
            print(f"Error: Customer with CNP or Persona '{identifier}' not found in database or presets.", file=sys.stderr)
            return 1

        print(f"Generating documents for {profile.full_name} ({profile.cnp})...")
        docs = generate_documents_for_profile(profile, output_dir, include_pdf=include_pdf, include_png=include_png)
        print(f"[OK] Documents generated in {output_dir / profile.slug}:")
        for kind, paths in docs.items():
            for fmt, path in paths.items():
                if path:
                    print(f"  [{kind.upper()}] {fmt.upper()}: {path}")
        return 0

    # 2. Single preset customer
    if args.customer:
        key = args.customer.lower().replace("-", "_")
        profile = PRESET_PROFILES.get(key)
        if not profile:
            print(f"Error: Preset customer '{args.customer}' not found. Use --list to see options.", file=sys.stderr)
            return 1

        print(f"Generating documents for preset customer: {profile.full_name} ({profile.persona_tag})...")
        docs = generate_documents_for_profile(profile, output_dir, include_pdf=include_pdf, include_png=include_png)
        print(f"[OK] Documents generated in {output_dir / profile.slug}:")
        for kind, paths in docs.items():
            for fmt, path in paths.items():
                if path:
                    print(f"  [{kind.upper()}] {fmt.upper()}: {path}")
        return 0

    # 3. Default: Full suite of demo test customers
    print(f"Generating complete synthetic document suite in {output_dir}...")
    manifest = generate_document_suite(
        output_dir=output_dir,
        include_pdf=include_pdf,
        include_png=include_png,
    )

    print(f"\n[OK] Successfully generated documents for {len(manifest)} customer profiles:")
    for entry in manifest:
        p = entry["profile"]
        docs = entry["documents"]
        print(f"  * {p.full_name:<20} ({p.persona_tag}):")
        for kind, paths in docs.items():
            files_str = ", ".join(f"{fmt.upper()}: {path.name}" for fmt, path in paths.items() if path)
            print(f"      - {kind:<10} -> {files_str}")

    print(f"\nIndex and documentation updated at: {output_dir / 'INDEX.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
