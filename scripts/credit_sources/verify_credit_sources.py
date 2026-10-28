"""Read-only verification of the delivered sample database and SQL exports."""

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

if __package__:
    from . import generate_credit_sources as fixtures
else:
    import generate_credit_sources as fixtures


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE = ROOT / "data" / "local" / "credit_sources.db"
DEFAULT_SAMPLES = ROOT / "data" / "synthetic" / "credit_sources"


def verify_saved_database(database=DEFAULT_DATABASE, sample_dir=DEFAULT_SAMPLES, replay=False):
    """Validate without changing D; optionally compare every saved/replayed row.

    Missing databases are errors, never implicitly created. Validation expects
    the manifest's default reporting date, not an arbitrary time-travel date.
    """
    database = Path(database).resolve()
    sample_dir = Path(sample_dir).resolve()
    manifest = json.loads((sample_dir / "sample_data_manifest.json").read_text(encoding="utf-8"))
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        counts = fixtures.validate_fixture(db, manifest)
        if replay:
            with closing(fixtures.new_database()) as expected:
                expected.executescript((sample_dir / "credit_sources_sample_data.sql").read_text(encoding="utf-8"))
                fixtures.validate_fixture(expected, manifest)
                schema_query = "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
                if [tuple(r) for r in db.execute(schema_query)] != [tuple(r) for r in expected.execute(schema_query)]:
                    raise ValueError("Saved database schema differs from the canonical SQL schema")
                for table in ("report_params",) + fixtures.TABLES:
                    rows = sorted((tuple(r) for r in db.execute(f"SELECT * FROM {table}")), key=repr)
                    expected_rows = sorted((tuple(r) for r in expected.execute(f"SELECT * FROM {table}")), key=repr)
                    if rows != expected_rows:
                        raise ValueError(f"Saved rows differ from sample SQL replay: {table}")
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--sample-dir", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--replay", action="store_true", help="Compare saved schema and every row with a fresh in-memory SQL replay")
    args = parser.parse_args()
    counts = verify_saved_database(args.database, args.sample_dir, args.replay)
    print(f"Verified read-only: {args.database.resolve()}")
    print(f"SQLite {sqlite3.sqlite_version}; all {len(counts)} views and fictional-data/integrity/FK checks passed.")
    if args.replay:
        print("Saved schema and rows exactly match the schema + sample SQL replay.")
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()