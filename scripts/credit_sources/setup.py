"""Create a local external-source database from versioned fictional SQL fixtures.

Never replaces an existing database. Application/assessment stores are unrelated.
"""

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

if __package__:
    from . import generate_credit_sources as fixtures
    from .verify_credit_sources import DEFAULT_DATABASE, DEFAULT_SAMPLES, verify_saved_database
else:
    import generate_credit_sources as fixtures
    from verify_credit_sources import DEFAULT_DATABASE, DEFAULT_SAMPLES, verify_saved_database


def create_database(database=DEFAULT_DATABASE, sample_dir=DEFAULT_SAMPLES, empty=False):
    """Build and verify in memory first, then exclusively create the local file."""
    if sqlite3.sqlite_version_info < (3, 35, 0):
        raise RuntimeError("SQLite 3.35 or newer is required")
    database, sample_dir = Path(database).resolve(), Path(sample_dir).resolve()
    if database.exists():
        raise FileExistsError(f"Refusing to overwrite existing database: {database}")
    schema = fixtures.SCHEMA_PATH.read_text(encoding="utf-8")
    with closing(sqlite3.connect(":memory:")) as prepared:
        prepared.row_factory = sqlite3.Row
        prepared.executescript(schema)
        if not empty:
            prepared.executescript((sample_dir / "credit_sources_sample_data.sql").read_text(encoding="utf-8"))
            manifest = json.loads((sample_dir / "sample_data_manifest.json").read_text(encoding="utf-8"))
            fixtures.validate_fixture(prepared, manifest)
        if prepared.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or prepared.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Prepared database failed integrity/foreign-key checks")
        database.parent.mkdir(parents=True, exist_ok=True)
        # Do not use a replace/reset flag: existing files must be preserved.
        with database.open("xb"):
            pass
        with closing(sqlite3.connect(database.as_uri() + "?mode=rw", uri=True)) as saved:
            prepared.backup(saved)
    if not empty:
        verify_saved_database(database, sample_dir, replay=True)
    return database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--sample-dir", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--empty", action="store_true", help="Create schema only, with its single parameter row")
    args = parser.parse_args()
    try:
        target = create_database(args.database, args.sample_dir, args.empty)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        parser.exit(1, f"{error}\n")
    print(f"Created and verified {'empty schema' if args.empty else 'fictional sample database'}: {target}")


if __name__ == "__main__":
    main()