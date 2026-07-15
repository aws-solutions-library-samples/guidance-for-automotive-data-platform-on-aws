"""Verify the cross-product join example SQL files parse cleanly under
sqlglot's Trino dialect (Athena Engine V3 superset).

Per Group 4 task `Cross-product join examples` Verify clause: each query
must be syntactically valid. sqlglot is a pure-Python parser that supports
the Trino/Presto dialect Athena Engine V3 uses, including Iceberg metadata
table references (`"<table>$snapshots"` etc.) and Iceberg time-travel
(`FOR TIMESTAMP AS OF`).

Usage:
    .venv/bin/python platform-foundation/scripts/verify-athena-queries.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import sqlglot
from sqlglot.errors import ParseError

QUERIES_DIR = Path(__file__).resolve().parents[1] / "source" / "athena-queries"
DIALECT = "trino"

# Iceberg metadata-table references (`"<table>$snapshots"`) parse as quoted
# identifiers; sqlglot accepts them under Trino. Time-travel commented blocks
# are excluded by the leading `--`.

failures: list[tuple[str, str]] = []
files = sorted(QUERIES_DIR.glob("*.sql"))

if not files:
    sys.stderr.write(f"ERROR: no .sql files in {QUERIES_DIR}\n")
    sys.exit(2)

for sql_path in files:
    sql_text = sql_path.read_text(encoding="utf-8")

    # Split on bare semicolons; ignore the optional time-travel-variant doc
    # block at the bottom of vin_full_360.sql (everything after the
    # `-- Optional time-travel variant` banner is comments).
    try:
        parsed_exprs = sqlglot.parse(sql_text, read=DIALECT)
    except ParseError as exc:
        failures.append((sql_path.name, f"parse: {exc}"))
        continue

    statements = [expr for expr in parsed_exprs if expr is not None]

    if not statements:
        failures.append((sql_path.name, "no parseable statement found"))
        continue

    # Re-validate each parsed statement by round-tripping through sqlglot's
    # transpile (Trino → Trino) — this catches anything `parse` accepted only
    # because of fault-tolerant defaults.
    for i, stmt in enumerate(statements, start=1):
        try:
            sqlglot.transpile(str(stmt), read=DIALECT, write=DIALECT)[0]
        except ParseError as exc:
            failures.append((sql_path.name, f"stmt {i}: {exc}"))

    print(f"OK  {sql_path.name}  ({len(statements)} stmt(s))")

if failures:
    print("\nFAIL", file=sys.stderr)
    for name, msg in failures:
        print(f"  - {name}: {msg}", file=sys.stderr)
    sys.exit(1)

print(f"\nALL OK — {len(files)} files, dialect={DIALECT}, sqlglot={sqlglot.__version__}")
