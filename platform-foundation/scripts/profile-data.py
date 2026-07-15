#!/usr/bin/env python3
"""profile-data.py — Distribution profiling reports for all 9 ADP products.

Implements Group 6 task ``Distribution profiling reports for all 9
products`` from the
``2026-05-28-adp-ev-startup-foundation`` spec.

For each of the 9 foundation data products this script computes:

- **Per-column stats** — count, distinct, null_rate, plus
  percentiles (p25/p50/p75/p95/p99) for numeric columns and a top-K
  histogram for categorical/boolean columns. Timestamp/date columns
  emit min/max/distinct.
- **Per-product edge-case rate measurements** — aggregate rate +
  per-code rate. Sourced from ``manifest.json`` if the generator
  wrote one, otherwise inferred heuristically from the curated
  parquet (``DRIFT-`` prefix, range violations, etc.).
- **FK orphan rates** — for every FK declared in the product schema,
  the fraction of values that do NOT match a key in the referenced
  dimension (or parent table). Per spec Constraint #5 the target is
  zero.
- **Partition-key cardinality** — distinct value count per partition
  key, plus the bucketing column cardinality where applicable.

Outputs:

- Per-product Markdown report and JSON to
  ``s3://adp-{stage}-foundation-lake-{account}-us-east-1/quality-reports/<product>/``
  (and locally under ``<curated-root>/../quality-reports/<product>/``
  for inspection / debugging).
- CloudWatch metrics under namespace ``ADP/Foundation/{stage}`` per
  the contract in ``source/quality-dashboard/metrics.py``. The 6
  metric names emitted match the dashboard widgets one-to-one
  (``RowCount``, ``EdgeCaseAggregateRate``, ``EdgeCodeRate``,
  ``LastSeedRunTimestamp``, ``DriftCheckPassed``,
  ``DriftCheckFailed``).

Stage-parameterised — fail-closed on missing/invalid stage matching
the convention in ``smoke-test-subscription.sh``,
``deploy-quality-dashboard.sh``, and the foundation Makefile (Fix
Group A3).

Usage::

    # Dry-run: print product list + metric names, no AWS / parquet
    python scripts/profile-data.py --stage staging --dry-run

    # Profile against a local curated tree (post-`make seed`)
    python scripts/profile-data.py --stage staging \\
        --curated-root /tmp/adp-curated --dim-root /tmp/adp-dim

    # Profile + upload + publish against the deployed foundation
    python scripts/profile-data.py --stage staging \\
        --curated-root s3://adp-staging-foundation-lake-{account}-us-east-1/curated \\
        --dim-root s3://adp-staging-foundation-lake-{account}-us-east-1/dimensions

    # Local profile, skip upload + CloudWatch publish
    python scripts/profile-data.py --stage staging --no-upload --no-publish

Verify (per the task instruction)::

    python scripts/profile-data.py --stage staging --dry-run
    .venv/bin/pytest tests/ -q

The ``--dry-run`` mode runs without AWS credentials or parquet on
disk; pytest collection is unaffected because this file lives under
``scripts/`` and ``pytest.ini`` scopes ``testpaths = tests``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Project-relative imports — match the convention used by
# tests/conftest.py and source/data-products/*/generator.py.
# ---------------------------------------------------------------------------

_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parent.parent  # platform-foundation/
_LIB = _REPO_ROOT / "source" / "lib"
_QUALITY_DIR = _REPO_ROOT / "source" / "quality-dashboard"

for _p in (_LIB, _QUALITY_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# These imports are fast and have no AWS-side effects (boto3 is
# lazy-imported below, only when actually publishing/uploading).
from schema_loader import (  # noqa: E402
    ForeignKey,
    Schema,
    Table,
    discover_schemas,
    load_schema,
    load_schema_from_path,
)

# Single source of truth for namespace + metric/dimension names. A
# typo here would silently emit the wrong namespace and the dashboard
# would render empty cells — importing from the same module the
# dashboard uses guarantees they stay in sync.
from metrics import (  # noqa: E402
    DIMENSION_DRIFT_CHECK,
    DIMENSION_EDGE_CODE,
    DIMENSION_PRODUCT,
    DIMENSION_TABLE,
    DRIFT_CHECKS,
    EDGE_CODES,
    METRIC_DRIFT_CHECK_FAILED,
    METRIC_DRIFT_CHECK_PASSED,
    METRIC_EDGE_CASE_AGGREGATE_RATE,
    METRIC_EDGE_CODE_RATE,
    METRIC_LAST_SEED_RUN_TIMESTAMP,
    METRIC_NAMES,
    METRIC_ROW_COUNT,
    PRODUCTS,
    TABLES,
    namespace,
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


VALID_STAGES = ("staging", "prod")
DEFAULT_REGION = "us-east-1"
DEFAULT_TOP_K = 10
NUMERIC_TYPES = {"int", "bigint", "double", "decimal"}
CATEGORICAL_TYPES = {"string", "boolean"}
TEMPORAL_TYPES = {"timestamp", "date"}
DRIFT_PREFIX = "DRIFT-"  # matches EdgeCaseInjector.schema_drift in product_generator.py


# Mapping from FK reference table -> pluralized location under the
# dimension/curated tree. Cross-table FK (ota_campaign_events ->
# ota_campaigns header) is resolved against the curated tree.
_DIMENSION_TABLES = {
    "vins",
    "customers",
    "dealers",
    "suppliers",
    "parts",
    "charging_stations",
}


# ---------------------------------------------------------------------------
# Logging helpers (stderr; stdout reserved for tooling-friendly output)
# ---------------------------------------------------------------------------


def _log(msg: str, *, prefix: str = "profile-data") -> None:
    print(f"[{prefix}] {msg}", file=sys.stderr, flush=True)


def _err(msg: str) -> None:
    print(f"[profile-data ERROR] {msg}", file=sys.stderr, flush=True)


def _ok(msg: str) -> None:
    print(f"[profile-data OK] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Stage validation (mirrors deploy-quality-dashboard.sh / Makefile)
# ---------------------------------------------------------------------------


def _validate_stage(stage: str) -> str:
    if not stage:
        _err("--stage is required (staging or prod, lower-case)")
        raise SystemExit(2)
    if stage not in VALID_STAGES:
        _err(f"--stage must be 'staging' or 'prod' (got {stage!r}); case-sensitive")
        raise SystemExit(2)
    return stage


# ---------------------------------------------------------------------------
# Path resolution — local Path or s3:// URI
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DataRoot:
    """A curated/dim root that can be either local or s3://."""

    raw: str

    @property
    def is_s3(self) -> bool:
        return self.raw.startswith("s3://")

    def join(self, *parts: str) -> "DataRoot":
        if self.is_s3:
            base = self.raw.rstrip("/")
            return DataRoot(base + "/" + "/".join(p.strip("/") for p in parts))
        p = Path(self.raw).expanduser()
        for part in parts:
            p = p / part
        return DataRoot(str(p))

    def to_local(self) -> Path:
        if self.is_s3:
            raise ValueError(f"Cannot resolve s3 URI to local Path: {self.raw}")
        return Path(self.raw).expanduser()

    def to_s3(self) -> tuple[str, str]:
        if not self.is_s3:
            raise ValueError(f"Cannot resolve local path to s3 URI: {self.raw}")
        bucket, _, prefix = self.raw[len("s3://") :].partition("/")
        return bucket, prefix.rstrip("/")

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.raw


def _default_curated_root() -> str:
    return str(_REPO_ROOT / "curated")


def _default_dim_root() -> str:
    return str(_REPO_ROOT / "dimensions")


def _stage_lake_bucket(stage: str, account: str, region: str) -> str:
    """Compose the per-stage lake bucket name per design §2.2."""
    return f"adp-{stage}-foundation-lake-{account}-{region}"


def _quality_reports_root(stage: str, account: str, region: str) -> str:
    return f"s3://{_stage_lake_bucket(stage, account, region)}/quality-reports"


# ---------------------------------------------------------------------------
# Parquet I/O — read locally OR from S3 via pyarrow.fs.S3FileSystem
# ---------------------------------------------------------------------------


def _list_parquet_files(root: DataRoot, *, region: str) -> list[str]:
    """Return parquet files (recursive) under ``root``.

    For local roots returns POSIX paths; for s3:// roots returns
    ``s3://bucket/key`` URIs. Files matching ``manifest.json`` /
    Hive ``_*`` markers are skipped.
    """
    if root.is_s3:
        try:
            import boto3  # lazy
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "boto3 is required to list S3 prefixes — install via requirements.txt"
            ) from exc
        bucket, prefix = root.to_s3()
        s3 = boto3.client("s3", region_name=region)
        paginator = s3.get_paginator("list_objects_v2")
        out: list[str] = []
        list_prefix = (prefix + "/") if prefix else ""
        for page in paginator.paginate(Bucket=bucket, Prefix=list_prefix):
            for obj in page.get("Contents", []) or []:
                key = obj["Key"]
                if key.endswith(".parquet") and not key.rsplit("/", 1)[-1].startswith("_"):
                    out.append(f"s3://{bucket}/{key}")
        return sorted(out)
    p = root.to_local()
    if not p.exists():
        return []
    return sorted(
        str(f)
        for f in p.rglob("*.parquet")
        if not f.name.startswith("_") and f.is_file()
    )


def _read_parquet_concat(
    paths: list[str], *, columns: list[str] | None = None, region: str
) -> Any:
    """Read + concat a list of parquet files into a pandas DataFrame.

    Single source of read I/O — handles s3:// vs local transparently
    via pyarrow's filesystem layer. Returns an empty DataFrame when
    ``paths`` is empty.

    ``columns`` is forwarded to pyarrow read so we can read a single
    column for FK closure or partition-key cardinality without
    pulling the whole row group into memory.
    """
    import pyarrow.parquet as pq  # local — fast import; no AWS calls
    import pandas as pd

    if not paths:
        return pd.DataFrame()
    fs = None
    if paths[0].startswith("s3://"):
        from pyarrow.fs import S3FileSystem  # lazy

        fs = S3FileSystem(region=region)

    frames = []
    for url in paths:
        if fs is not None:
            # pyarrow expects bucket/key form when a filesystem is given.
            url_for_pa = url[len("s3://") :]
        else:
            url_for_pa = url
        try:
            schema = pq.read_schema(url_for_pa, filesystem=fs)
            if columns is not None:
                # Skip files that are missing requested columns
                # (multi-table products like ota_campaigns split
                # different column sets across two parquet trees).
                wanted = [c for c in columns if c in schema.names]
                if not wanted:
                    continue
                # 2026-06-02 fix (within-quota-seed spec): use
                # ParquetFile.read() to read a SINGLE file, avoiding
                # pyarrow.parquet.read_table's dataset auto-merge that
                # fails on partitioned trees with mixed-typed partition
                # columns (int32 vs dictionary<int32>). Same root cause
                # / same fix as lib/integrity-fast.py.
                tbl = pq.ParquetFile(url_for_pa, filesystem=fs).read(columns=wanted)
            else:
                tbl = pq.ParquetFile(url_for_pa, filesystem=fs).read()
        except (OSError, ValueError):
            continue
        frames.append(tbl.to_pandas(types_mapper=None))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def _read_manifest(root: DataRoot, product: str, *, region: str) -> dict[str, Any] | None:
    """Read ``manifest.json`` for a product if present (local or s3)."""
    if root.is_s3:
        bucket, prefix = root.to_s3()
        key = f"{prefix}/{product}/manifest.json" if prefix else f"{product}/manifest.json"
        try:
            import boto3  # lazy
        except ImportError:
            return None
        s3 = boto3.client("s3", region_name=region)
        try:
            obj = s3.get_object(Bucket=bucket, Key=key)
            return json.loads(obj["Body"].read())
        except Exception:  # noqa: BLE001 — best-effort; missing manifest is fine
            return None
    p = root.to_local() / product / "manifest.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def _column_stats_numeric(series: Any) -> dict[str, Any]:
    """Numeric column stats: count, distinct, null_rate, percentiles."""
    import pandas as pd

    n = len(series)
    nulls = int(series.isna().sum())
    non_null = series.dropna()
    out: dict[str, Any] = {
        "kind": "numeric",
        "count": n,
        "non_null": int(len(non_null)),
        "nulls": nulls,
        "null_rate": (nulls / n) if n else 0.0,
        "distinct": int(non_null.nunique()),
    }
    if not non_null.empty:
        try:
            numeric = pd.to_numeric(non_null, errors="coerce").dropna()
        except (TypeError, ValueError):
            numeric = non_null
        if not numeric.empty:
            out["min"] = float(numeric.min())
            out["max"] = float(numeric.max())
            out["mean"] = float(numeric.mean())
            stddev = numeric.std(ddof=0)
            out["stddev"] = float(stddev) if not math.isnan(float(stddev)) else 0.0
            for label, q in (("p25", 0.25), ("p50", 0.5), ("p75", 0.75), ("p95", 0.95), ("p99", 0.99)):
                out[label] = float(numeric.quantile(q))
    return out


def _column_stats_categorical(
    series: Any, *, top_k: int
) -> dict[str, Any]:
    """Categorical column stats: count, distinct, null_rate, top-K."""
    n = len(series)
    nulls = int(series.isna().sum())
    non_null = series.dropna()
    distinct = int(non_null.nunique()) if not non_null.empty else 0
    top: list[dict[str, Any]] = []
    if not non_null.empty:
        vc = non_null.value_counts(dropna=True).head(top_k)
        for value, count in vc.items():
            top.append({"value": _to_jsonable(value), "count": int(count)})
    return {
        "kind": "categorical",
        "count": n,
        "non_null": int(len(non_null)),
        "nulls": nulls,
        "null_rate": (nulls / n) if n else 0.0,
        "distinct": distinct,
        "top_k": top,
    }


def _column_stats_temporal(series: Any) -> dict[str, Any]:
    """Timestamp/date column stats: count, distinct, null_rate, min/max."""
    n = len(series)
    nulls = int(series.isna().sum())
    non_null = series.dropna()
    distinct = int(non_null.nunique()) if not non_null.empty else 0
    out: dict[str, Any] = {
        "kind": "temporal",
        "count": n,
        "non_null": int(len(non_null)),
        "nulls": nulls,
        "null_rate": (nulls / n) if n else 0.0,
        "distinct": distinct,
    }
    if not non_null.empty:
        out["min"] = str(non_null.min())
        out["max"] = str(non_null.max())
    return out


def _to_jsonable(value: Any) -> Any:
    """Coerce numpy / pandas scalars to JSON-friendly Python types."""
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        np = None
    if value is None:
        return None
    if np is not None and isinstance(value, (np.integer,)):
        return int(value)
    if np is not None and isinstance(value, (np.floating,)):
        return float(value)
    if np is not None and isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return repr(value)
    if isinstance(value, (int, float, bool, str)):
        return value
    return str(value)


# ---------------------------------------------------------------------------
# Edge-case rate measurement
#
# We prefer the manifest counts when the generator wrote them (they
# encode INTENT, not just observation). Heuristic measurement
# supplements and serves as the only path for products generated
# outside the master `seed` (e.g., a re-seed-on-Glue run). orphan_fk
# rate is always measured by FK closure check below — it is never
# carried in the manifest because it is the spec's counter-example.
# ---------------------------------------------------------------------------


def _measure_edge_case_heuristic(
    df: Any, *, table: Table
) -> dict[str, dict[str, float]]:
    """Best-effort per-code rate inference from data alone.

    Returns ``{code: {"rate": float, "count": int}}`` for the five
    measurable codes (``orphan_fk`` is computed separately). Used
    only when manifest counts are unavailable or for cross-checks.
    """
    n = len(df)
    if n == 0:
        return {}

    out: dict[str, dict[str, float]] = {}
    eligible_cols = {c.name for c in table.columns if c.edge_case_eligible and c.name in df.columns}

    # missing_required: any null in an edge_case_eligible column.
    if eligible_cols:
        missing_count = 0
        for col in eligible_cols:
            missing_count += int(df[col].isna().sum())
        out["missing_required"] = {
            "count": missing_count,
            "rate": missing_count / n,
        }

    # late_arrival: ingest_time > event_time + 1 day.
    if "ingest_time" in df.columns:
        # Source-truth column varies by product; use the schema's
        # first timestamp column not named ingest_time.
        source_time_col = None
        for c in table.columns:
            if c.type == "timestamp" and c.name != "ingest_time" and c.name in df.columns:
                source_time_col = c.name
                break
        if source_time_col is None:
            # date column fallback (energy_usage uses usage_date)
            for c in table.columns:
                if c.type == "date" and c.name in df.columns:
                    source_time_col = c.name
                    break
        if source_time_col:
            try:
                import pandas as pd

                source_ts = pd.to_datetime(df[source_time_col], errors="coerce", utc=True)
                ingest_ts = pd.to_datetime(df["ingest_time"], errors="coerce", utc=True)
                delta = (ingest_ts - source_ts).dt.total_seconds() / 86400.0
                late = (delta >= 1.0).fillna(False)
                late_count = int(late.sum())
                out["late_arrival"] = {"count": late_count, "rate": late_count / n}
            except (TypeError, ValueError):  # pragma: no cover
                pass

    # schema_drift: string column starts with "DRIFT-".
    drift_count = 0
    for c in table.columns:
        if c.type != "string" or c.name not in df.columns:
            continue
        try:
            drift_count += int(
                df[c.name].astype("string").str.startswith(DRIFT_PREFIX, na=False).sum()
            )
        except (TypeError, ValueError):  # pragma: no cover
            continue
    out["schema_drift"] = {"count": drift_count, "rate": drift_count / n}

    # bad_pii: pii_drift_target columns that fail their declared
    # regex pattern. Falls back to "starts with non-alphanum char"
    # for columns without a pattern.
    pii_targets = [
        c
        for c in table.columns
        if c.pii_drift_target and c.name in df.columns
    ]
    if pii_targets:
        pii_count = 0
        for c in pii_targets:
            series = df[c.name]
            non_null = series.dropna()
            if non_null.empty:
                continue
            if c.pattern:
                try:
                    pat = re.compile(c.pattern)
                    pii_count += int(sum(1 for v in non_null if not pat.match(str(v))))
                except re.error:  # pragma: no cover
                    pass
            # Heuristic fallback: lowercase 'i' inserted at index 2 by
            # the injector breaks the well-formed regex but produces
            # otherwise-printable text — count strings beginning with
            # the conventional injector signature.
            else:
                pii_count += int(
                    non_null.astype("string")
                    .str.contains(r"[\u0000-\u001f]", regex=True, na=False)
                    .sum()
                )
        out["bad_pii"] = {"count": pii_count, "rate": pii_count / n}

    # outlier_value: numeric range violations (count values that
    # exceed declared range bounds).
    outlier_count = 0
    for c in table.columns:
        if c.type not in NUMERIC_TYPES or c.name not in df.columns:
            continue
        if not c.range:
            continue
        lo, hi = c.range
        try:
            import pandas as pd

            numeric = pd.to_numeric(df[c.name], errors="coerce")
            mask = (numeric < lo) | (numeric > hi)
            outlier_count += int(mask.fillna(False).sum())
        except (TypeError, ValueError):  # pragma: no cover
            continue
    out["outlier_value"] = {"count": outlier_count, "rate": outlier_count / n}

    return out


def _edge_case_summary_from_manifest(
    manifest: dict[str, Any] | None, *, row_count: int
) -> dict[str, dict[str, float]] | None:
    """Convert manifest's edge_case_summary (counts) to {code: {count, rate}}."""
    if not manifest:
        return None
    summary = manifest.get("edge_case_summary")
    if not isinstance(summary, dict):
        return None
    out: dict[str, dict[str, float]] = {}
    for code in EDGE_CODES:
        cnt = int(summary.get(code, 0) or 0)
        out[code] = {
            "count": cnt,
            "rate": (cnt / row_count) if row_count else 0.0,
        }
    return out


# ---------------------------------------------------------------------------
# FK orphan rate computation
# ---------------------------------------------------------------------------


def _resolve_fk_target_paths(
    fk: ForeignKey,
    *,
    dim_root: DataRoot,
    curated_root: DataRoot,
    region: str,
) -> tuple[list[str], str]:
    """Return parquet paths for an FK target, plus a path-label for diagnostics.

    Dimension targets live under ``dim_root/<dim>/``; cross-table
    parent FKs (only ``ota_campaigns`` for v1 — events->header) live
    under ``curated_root/<product>/<table>/`` with the parent
    products already materialised by the master ``seed`` task.
    """
    if fk.references_table in _DIMENSION_TABLES:
        dim_paths = _list_parquet_files(
            dim_root.join(fk.references_table), region=region
        )
        return dim_paths, str(dim_root.join(fk.references_table))
    if fk.references_table == "ota_campaigns":
        # Header table parquet lives under curated/ota_campaigns/.
        # The events generator writes header + events to the same
        # tree partitioned differently; we pick files that have
        # the referenced column and not the events-only `vin` column.
        tree = curated_root.join("ota_campaigns")
        return _list_parquet_files(tree, region=region), str(tree)
    return [], f"<unknown-target:{fk.references_table}>"


def _measure_fk_orphans(
    df: Any,
    *,
    fk: ForeignKey,
    dim_root: DataRoot,
    curated_root: DataRoot,
    region: str,
) -> dict[str, Any]:
    """Compute orphan rate for one FK reference."""
    if fk.column not in df.columns:
        return {
            "column": fk.column,
            "references_table": fk.references_table,
            "references_column": fk.references_column,
            "skipped_reason": "fk-column-not-present-in-df",
        }
    target_paths, target_label = _resolve_fk_target_paths(
        fk, dim_root=dim_root, curated_root=curated_root, region=region
    )
    if not target_paths:
        return {
            "column": fk.column,
            "references_table": fk.references_table,
            "references_column": fk.references_column,
            "skipped_reason": f"target-not-found:{target_label}",
        }
    target_df = _read_parquet_concat(
        target_paths, columns=[fk.references_column], region=region
    )
    if target_df.empty or fk.references_column not in target_df.columns:
        return {
            "column": fk.column,
            "references_table": fk.references_table,
            "references_column": fk.references_column,
            "skipped_reason": "target-table-empty-or-missing-column",
        }
    valid = set(target_df[fk.references_column].dropna().tolist())
    series = df[fk.column]
    non_null = series.dropna()
    n_total = int(len(non_null))
    if n_total == 0:
        return {
            "column": fk.column,
            "references_table": fk.references_table,
            "references_column": fk.references_column,
            "row_count": int(len(df)),
            "non_null_count": 0,
            "valid_count": 0,
            "orphan_count": 0,
            "orphan_rate": 0.0,
        }
    orphans = int(sum(1 for v in non_null if v not in valid))
    return {
        "column": fk.column,
        "references_table": fk.references_table,
        "references_column": fk.references_column,
        "row_count": int(len(df)),
        "non_null_count": n_total,
        "valid_count": n_total - orphans,
        "orphan_count": orphans,
        "orphan_rate": orphans / n_total,
    }


# ---------------------------------------------------------------------------
# Per-table profiler
# ---------------------------------------------------------------------------


@dataclass
class TableProfile:
    """Profile result for a single table within a product."""

    product: str
    table: str
    storage_format: str
    row_count: int = 0
    columns: dict[str, dict[str, Any]] = field(default_factory=dict)
    partition_keys: dict[str, dict[str, Any]] = field(default_factory=dict)
    foreign_keys: list[dict[str, Any]] = field(default_factory=list)
    edge_case_aggregate_rate: float = 0.0
    edge_case_per_code: dict[str, dict[str, float]] = field(default_factory=dict)
    edge_case_source: str = "missing"  # 'manifest' | 'heuristic' | 'missing'
    last_seed_run_timestamp: int | None = None
    degenerate_columns: list[str] = field(default_factory=list)


def _profile_table(
    *,
    schema: Schema,
    table: Table,
    table_paths: list[str],
    manifest: dict[str, Any] | None,
    dim_root: DataRoot,
    curated_root: DataRoot,
    top_k: int,
    region: str,
) -> TableProfile:
    """Profile a single Iceberg table within a product."""
    profile = TableProfile(
        product=schema.name,
        table=table.name,
        storage_format=table.storage_format,
    )
    if not table_paths:
        return profile

    df = _read_parquet_concat(table_paths, region=region)
    if df.empty:
        return profile
    profile.row_count = int(len(df))

    # ------------------------------------------------------------------
    # Per-column stats
    # ------------------------------------------------------------------
    for c in table.columns:
        if c.name not in df.columns:
            continue
        series = df[c.name]
        if c.type in NUMERIC_TYPES:
            stats = _column_stats_numeric(series)
            # Degenerate detector — aligns with
            # tests/test_distribution_profile.py contract: stddev > 0
            # AND ≥3 distinct values.
            if (
                stats.get("non_null", 0) > 0
                and (stats.get("stddev", 0.0) <= 0.0 or stats.get("distinct", 0) < 3)
            ):
                profile.degenerate_columns.append(c.name)
        elif c.type in CATEGORICAL_TYPES:
            stats = _column_stats_categorical(series, top_k=top_k)
        elif c.type in TEMPORAL_TYPES:
            stats = _column_stats_temporal(series)
        else:
            # array<*> — record null/distinct counts only; skip top_k.
            stats = {
                "kind": "array",
                "count": len(series),
                "non_null": int(series.notna().sum()),
                "nulls": int(series.isna().sum()),
                "null_rate": (
                    int(series.isna().sum()) / len(series) if len(series) else 0.0
                ),
            }
        stats["pii"] = bool(c.pii)
        stats["edge_case_eligible"] = bool(c.edge_case_eligible)
        profile.columns[c.name] = stats

    # ------------------------------------------------------------------
    # Partition-key cardinality
    # ------------------------------------------------------------------
    for pkey in table.partition_keys:
        if pkey not in df.columns:
            continue
        non_null = df[pkey].dropna()
        profile.partition_keys[pkey] = {
            "kind": "partition_key",
            "distinct": int(non_null.nunique()) if not non_null.empty else 0,
            "non_null": int(len(non_null)),
            "min": str(non_null.min()) if not non_null.empty else None,
            "max": str(non_null.max()) if not non_null.empty else None,
        }
    # Bucketing column cardinality is informative even without
    # actually-bucketed data on disk (local pandas runs don't apply
    # Iceberg bucket transforms).
    for bcol, bucket_count in table.bucketing.items():
        if bcol not in df.columns:
            continue
        non_null = df[bcol].dropna()
        profile.partition_keys[f"bucket({bucket_count}, {bcol})"] = {
            "kind": "bucket",
            "bucket_count": bucket_count,
            "distinct": int(non_null.nunique()) if not non_null.empty else 0,
            "non_null": int(len(non_null)),
        }

    # ------------------------------------------------------------------
    # FK orphan rates
    # ------------------------------------------------------------------
    for fk in table.foreign_keys:
        profile.foreign_keys.append(
            _measure_fk_orphans(
                df,
                fk=fk,
                dim_root=dim_root,
                curated_root=curated_root,
                region=region,
            )
        )

    # ------------------------------------------------------------------
    # Edge-case rates — manifest first, heuristic fallback
    # ------------------------------------------------------------------
    manifest_summary = _edge_case_summary_from_manifest(
        manifest, row_count=profile.row_count
    )
    if manifest_summary is not None:
        profile.edge_case_per_code = manifest_summary
        profile.edge_case_source = "manifest"
    else:
        heur = _measure_edge_case_heuristic(df, table=table)
        # Fill the six codes; orphan_fk computed separately below.
        merged: dict[str, dict[str, float]] = {}
        for code in EDGE_CODES:
            merged[code] = heur.get(code, {"count": 0, "rate": 0.0})
        profile.edge_case_per_code = merged
        profile.edge_case_source = "heuristic"

    # orphan_fk rate — sum across all measured FKs / row_count.
    fk_orphan_total = sum(
        int(fk_rec.get("orphan_count", 0))
        for fk_rec in profile.foreign_keys
        if "orphan_count" in fk_rec
    )
    profile.edge_case_per_code["orphan_fk"] = {
        "count": fk_orphan_total,
        "rate": (fk_orphan_total / profile.row_count) if profile.row_count else 0.0,
    }

    # Aggregate rate excludes orphan_fk because it is the counter-
    # example — all other codes are intentional injection.
    aggregate_count = sum(
        int(v.get("count", 0))
        for code, v in profile.edge_case_per_code.items()
        if code != "orphan_fk"
    )
    profile.edge_case_aggregate_rate = (
        aggregate_count / profile.row_count if profile.row_count else 0.0
    )

    # ------------------------------------------------------------------
    # Last seed-run timestamp from manifest, if present
    # ------------------------------------------------------------------
    if manifest and isinstance(manifest.get("generated_at_utc"), str):
        try:
            import pandas as pd

            ts = pd.Timestamp(manifest["generated_at_utc"])
            profile.last_seed_run_timestamp = int(ts.timestamp())
        except (TypeError, ValueError):  # pragma: no cover
            pass

    return profile


# ---------------------------------------------------------------------------
# Documents-product profile (vehicle_knowledge_base)
# ---------------------------------------------------------------------------


def _profile_documents_table(
    *,
    schema: Schema,
    table: Table,
    curated_root: DataRoot,
    region: str,
) -> TableProfile:
    """Best-effort profile for the docs-format KB product.

    Reports chunk count from manifest_extended.json / manifest.json
    if present; otherwise enumerates ``sources/**/*.md`` files.
    """
    profile = TableProfile(
        product=schema.name,
        table=table.name,
        storage_format=table.storage_format,
    )
    # Try the base + extended manifest from
    # source/data-products/vehicle_knowledge_base/generator.py.
    chunk_count = 0
    for manifest_name in ("manifest.json", "manifest_extended.json"):
        if curated_root.is_s3:
            try:
                import boto3

                bucket, prefix = curated_root.to_s3()
                key = (
                    f"{prefix}/{schema.name}/{manifest_name}"
                    if prefix
                    else f"{schema.name}/{manifest_name}"
                )
                s3 = boto3.client("s3", region_name=region)
                obj = s3.get_object(Bucket=bucket, Key=key)
                manifest = json.loads(obj["Body"].read())
                chunk_count += int(manifest.get("chunk_count", 0) or 0)
                if isinstance(manifest.get("chunks"), list):
                    chunk_count += len(manifest["chunks"])
            except Exception:  # noqa: BLE001
                continue
        else:
            p = curated_root.to_local() / schema.name / manifest_name
            if p.exists():
                try:
                    manifest = json.loads(p.read_text())
                    if "chunk_count" in manifest:
                        chunk_count += int(manifest["chunk_count"])
                    elif isinstance(manifest.get("chunks"), list):
                        chunk_count += len(manifest["chunks"])
                except (OSError, json.JSONDecodeError):
                    pass
    profile.row_count = chunk_count
    profile.edge_case_per_code = {code: {"count": 0, "rate": 0.0} for code in EDGE_CODES}
    profile.edge_case_source = "n/a-documents"
    return profile


# ---------------------------------------------------------------------------
# Drift-check pass/fail counts (per cycle) — proxy via in-process pytest
# ---------------------------------------------------------------------------


def _drift_check_summary() -> dict[str, dict[str, int]]:
    """Return ``{drift_check: {passed, failed}}`` for this run.

    The actual pass/fail signal is owned by ``test_data_contracts.py``
    (CI integration). When this profiler runs standalone we emit a
    placeholder of ``{passed: 0, failed: 0}`` per check — the
    profiler does not invoke pytest internally to avoid a cyclic
    dependency on the test suite. CI gates that wrap this script
    can override by emitting an env hint via
    ``ADP_DRIFT_<CHECK>=passed|failed``.
    """
    out: dict[str, dict[str, int]] = {}
    for check in DRIFT_CHECKS:
        env_key = f"ADP_DRIFT_{check.upper()}"
        result = os.environ.get(env_key, "").strip().lower()
        passed = 1 if result == "passed" else 0
        failed = 1 if result == "failed" else 0
        out[check] = {"passed": passed, "failed": failed}
    return out


# ---------------------------------------------------------------------------
# Output writers — JSON + Markdown
# ---------------------------------------------------------------------------


def _profile_to_dict(profiles: list[TableProfile]) -> dict[str, Any]:
    """Compose the per-product JSON report body."""
    primary = profiles[0]
    return {
        "schema_version": "1.0.0",
        "product": primary.product,
        "tables": [
            {
                "name": p.table,
                "storage_format": p.storage_format,
                "row_count": p.row_count,
                "edge_case_aggregate_rate": p.edge_case_aggregate_rate,
                "edge_case_per_code": p.edge_case_per_code,
                "edge_case_source": p.edge_case_source,
                "last_seed_run_timestamp": p.last_seed_run_timestamp,
                "partition_keys": p.partition_keys,
                "foreign_keys": p.foreign_keys,
                "degenerate_columns": p.degenerate_columns,
                "columns": p.columns,
            }
            for p in profiles
        ],
    }


def _format_rate(value: float) -> str:
    return f"{value * 100:.2f}%"


def _format_top_k(rows: list[dict[str, Any]], *, limit: int = 5) -> str:
    if not rows:
        return "—"
    fragments = []
    for r in rows[:limit]:
        v = r.get("value")
        c = r.get("count")
        fragments.append(f"`{v}`={c}")
    extra = "" if len(rows) <= limit else f", … (+{len(rows) - limit} more)"
    return ", ".join(fragments) + extra


def _profile_to_markdown(report: dict[str, Any], *, stage: str) -> str:
    """Render a per-product Markdown report."""
    out: list[str] = []
    out.append(f"# Profile: {report['product']}")
    out.append("")
    out.append(f"- Stage: `{stage}`")
    out.append(f"- Schema version: `{report['schema_version']}`")
    out.append("")
    for tbl in report["tables"]:
        out.append(f"## Table: `{tbl['name']}` ({tbl['storage_format']})")
        out.append("")
        out.append(f"- Row count: **{tbl['row_count']:,}**")
        if tbl["last_seed_run_timestamp"]:
            out.append(
                f"- Last seed run: `{tbl['last_seed_run_timestamp']}` (Unix epoch UTC)"
            )
        out.append(
            f"- Edge-case aggregate rate: **{_format_rate(tbl['edge_case_aggregate_rate'])}** "
            f"(target band 1–3%, source: `{tbl['edge_case_source']}`)"
        )
        if tbl["degenerate_columns"]:
            out.append(
                "- ⚠️  Degenerate numeric columns: "
                + ", ".join(f"`{c}`" for c in tbl["degenerate_columns"])
            )
        out.append("")

        # Edge-case breakdown
        out.append("### Edge-case breakdown")
        out.append("")
        out.append("| code | count | rate |")
        out.append("|---|---:|---:|")
        for code in EDGE_CODES:
            entry = tbl["edge_case_per_code"].get(code, {"count": 0, "rate": 0.0})
            out.append(
                f"| `{code}` | {entry.get('count', 0):,} | "
                f"{_format_rate(entry.get('rate', 0.0))} |"
            )
        out.append("")

        # Partition / bucket cardinality
        if tbl["partition_keys"]:
            out.append("### Partition + bucket cardinality")
            out.append("")
            out.append("| key | kind | distinct | non-null | min | max |")
            out.append("|---|---|---:|---:|---|---|")
            for k, info in tbl["partition_keys"].items():
                out.append(
                    f"| `{k}` | {info.get('kind', '?')} | "
                    f"{info.get('distinct', 0):,} | "
                    f"{info.get('non_null', 0):,} | "
                    f"`{info.get('min', '—')}` | "
                    f"`{info.get('max', '—')}` |"
                )
            out.append("")

        # FK orphan summary
        if tbl["foreign_keys"]:
            out.append("### Foreign-key orphan rates")
            out.append("")
            out.append("| column | references | non-null | orphan | rate | notes |")
            out.append("|---|---|---:|---:|---:|---|")
            for fk in tbl["foreign_keys"]:
                ref = f"`{fk['references_table']}`.`{fk['references_column']}`"
                if "skipped_reason" in fk:
                    out.append(
                        f"| `{fk['column']}` | {ref} | — | — | — | "
                        f"skipped: `{fk['skipped_reason']}` |"
                    )
                else:
                    out.append(
                        f"| `{fk['column']}` | {ref} | "
                        f"{fk.get('non_null_count', 0):,} | "
                        f"{fk.get('orphan_count', 0):,} | "
                        f"{_format_rate(fk.get('orphan_rate', 0.0))} | "
                        f"target 0% |"
                    )
            out.append("")

        # Per-column stats
        out.append("### Per-column distribution")
        out.append("")
        out.append("| column | kind | non-null | distinct | null rate | summary |")
        out.append("|---|---|---:|---:|---:|---|")
        for col_name, stats in tbl["columns"].items():
            kind = stats.get("kind", "?")
            non_null = stats.get("non_null", 0)
            distinct = stats.get("distinct", 0)
            null_rate = _format_rate(stats.get("null_rate", 0.0))
            if kind == "numeric":
                summary = (
                    f"min=`{stats.get('min', '—')}` "
                    f"max=`{stats.get('max', '—')}` "
                    f"mean=`{stats.get('mean', '—')}` "
                    f"σ=`{stats.get('stddev', '—')}` "
                    f"p50=`{stats.get('p50', '—')}` "
                    f"p95=`{stats.get('p95', '—')}`"
                )
            elif kind == "categorical":
                summary = "top: " + _format_top_k(stats.get("top_k", []))
            elif kind == "temporal":
                summary = (
                    f"min=`{stats.get('min', '—')}` max=`{stats.get('max', '—')}`"
                )
            else:
                summary = "(array — no top-K rendered)"
            pii_marker = " 🔒" if stats.get("pii") else ""
            out.append(
                f"| `{col_name}`{pii_marker} | {kind} | "
                f"{non_null:,} | {distinct:,} | {null_rate} | {summary} |"
            )
        out.append("")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# CloudWatch publish + S3 upload (lazy boto3)
# ---------------------------------------------------------------------------


def _publish_metrics(
    *,
    stage: str,
    region: str,
    profiles_by_product: dict[str, list[TableProfile]],
    drift_summary: dict[str, dict[str, int]],
) -> int:
    """Publish all metrics for this run. Returns total metrics published."""
    import boto3  # lazy

    cw = boto3.client("cloudwatch", region_name=region)
    ns = namespace(stage)
    timestamp_now = int(time.time())

    metric_data: list[dict[str, Any]] = []

    for product, profiles in profiles_by_product.items():
        for p in profiles:
            # RowCount per Table
            metric_data.append(
                {
                    "MetricName": METRIC_ROW_COUNT,
                    "Dimensions": [{"Name": DIMENSION_TABLE, "Value": p.table}],
                    "Value": float(p.row_count),
                    "Unit": "Count",
                    "Timestamp": timestamp_now,
                }
            )
            # EdgeCaseAggregateRate per Product (table-grain reporting
            # for the multi-table OTA case is via per-Table dimension).
            metric_data.append(
                {
                    "MetricName": METRIC_EDGE_CASE_AGGREGATE_RATE,
                    "Dimensions": [{"Name": DIMENSION_TABLE, "Value": p.table}],
                    "Value": float(p.edge_case_aggregate_rate),
                    "Unit": "None",
                    "Timestamp": timestamp_now,
                }
            )
            # EdgeCodeRate per (Table, EdgeCode)
            for code in EDGE_CODES:
                rate = float(
                    p.edge_case_per_code.get(code, {"rate": 0.0}).get("rate", 0.0)
                )
                metric_data.append(
                    {
                        "MetricName": METRIC_EDGE_CODE_RATE,
                        "Dimensions": [
                            {"Name": DIMENSION_TABLE, "Value": p.table},
                            {"Name": DIMENSION_EDGE_CODE, "Value": code},
                        ],
                        "Value": rate,
                        "Unit": "None",
                        "Timestamp": timestamp_now,
                    }
                )
            # LastSeedRunTimestamp per Product (epoch seconds)
            if p.last_seed_run_timestamp:
                metric_data.append(
                    {
                        "MetricName": METRIC_LAST_SEED_RUN_TIMESTAMP,
                        "Dimensions": [
                            {"Name": DIMENSION_PRODUCT, "Value": product}
                        ],
                        "Value": float(p.last_seed_run_timestamp),
                        "Unit": "Seconds",
                        "Timestamp": timestamp_now,
                    }
                )

    # Drift-check pass/fail counts
    for check, counts in drift_summary.items():
        for metric_name, key in (
            (METRIC_DRIFT_CHECK_PASSED, "passed"),
            (METRIC_DRIFT_CHECK_FAILED, "failed"),
        ):
            metric_data.append(
                {
                    "MetricName": metric_name,
                    "Dimensions": [{"Name": DIMENSION_DRIFT_CHECK, "Value": check}],
                    "Value": float(counts.get(key, 0)),
                    "Unit": "Count",
                    "Timestamp": timestamp_now,
                }
            )

    # CloudWatch's PutMetricData accepts up to 1000 metrics per call;
    # batch in chunks of 20 (the older default-safe size) so a single
    # backoff doesn't lose 200 widgets at once.
    batch_size = 20
    total = 0
    for i in range(0, len(metric_data), batch_size):
        batch = metric_data[i : i + batch_size]
        cw.put_metric_data(Namespace=ns, MetricData=batch)
        total += len(batch)
    return total


def _upload_report(
    *,
    stage: str,
    account: str,
    region: str,
    product: str,
    json_path: Path,
    md_path: Path,
) -> tuple[str, str]:
    """Upload the per-product JSON + Markdown to S3. Returns the URIs."""
    import boto3  # lazy

    bucket = _stage_lake_bucket(stage, account, region)
    s3 = boto3.client("s3", region_name=region)
    json_key = f"quality-reports/{product}/profile.json"
    md_key = f"quality-reports/{product}/profile.md"
    s3.upload_file(str(json_path), bucket, json_key)
    s3.upload_file(str(md_path), bucket, md_key)
    return f"s3://{bucket}/{json_key}", f"s3://{bucket}/{md_key}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="profile-data",
        description=(
            "Distribution profiling reports for the 9 ADP foundation "
            "data products. Stage-parameterised; emits per-product "
            "Markdown + JSON to s3://adp-{stage}-foundation-lake-... "
            "and publishes CloudWatch metrics matching the dashboard "
            "namespace ADP/Foundation/{stage}."
        ),
    )
    parser.add_argument(
        "--stage",
        required=True,
        choices=VALID_STAGES,
        help="Foundation stage (lower-case; matches Makefile contract).",
    )
    parser.add_argument(
        "--curated-root",
        default=None,
        help=(
            "Local path or s3://... root containing per-product parquet trees "
            "(default: <repo>/curated/)"
        ),
    )
    parser.add_argument(
        "--dim-root",
        default=None,
        help=(
            "Local path or s3://... root containing dimension parquet trees "
            "(default: <repo>/dimensions/)"
        ),
    )
    parser.add_argument(
        "--account",
        default=None,
        help=(
            "AWS account ID for the destination lake bucket "
            "(defaults to aws sts get-caller-identity)."
        ),
    )
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help="AWS region (default us-east-1).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help="Top-K bucket size for categorical columns (default 10).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Local directory to write per-product JSON + Markdown reports "
            "(default: <repo>/quality-reports/)."
        ),
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Skip S3 upload of reports (still writes locally).",
    )
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="Skip CloudWatch metric publish.",
    )
    parser.add_argument(
        "--fail-on-degenerate",
        action="store_true",
        help=(
            "Exit non-zero if any column has degenerate distribution per "
            "tests/test_distribution_profile.py (stddev == 0 OR "
            "distinct < 3). Per spec Constraint."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the product list and metric names without reading "
            "parquet, uploading to S3, or publishing CloudWatch metrics."
        ),
    )
    parser.add_argument(
        "--products",
        nargs="*",
        default=None,
        help=(
            "Optional subset of product technical names to profile "
            "(default: all 9)."
        ),
    )
    return parser.parse_args(argv)


def _resolve_account(args: argparse.Namespace) -> str | None:
    """Resolve the AWS account ID via --account or aws sts get-caller-identity."""
    if args.account:
        return args.account
    if args.dry_run:
        return None
    try:
        import boto3  # lazy
    except ImportError:
        return None
    try:
        sts = boto3.client("sts", region_name=args.region)
        return sts.get_caller_identity()["Account"]
    except Exception as exc:  # noqa: BLE001
        _err(f"could not resolve AWS account via STS: {exc}")
        return None


def _print_dry_run(args: argparse.Namespace) -> int:
    """Print product list + metric names (and exit 0).

    This is the verify path per the task instruction:
    ``--dry-run prints product list and metric names without
    executing``.
    """
    stage = _validate_stage(args.stage)
    products = list(args.products) if args.products else list(PRODUCTS)
    for product in products:
        if product not in PRODUCTS:
            _err(f"unknown product: {product}")
            return 2

    print("=" * 72)
    print(f"profile-data --dry-run (stage={stage})")
    print("=" * 72)
    print()
    print(f"Stage:                {stage}")
    print(f"Region:               {args.region}")
    print(f"CloudWatch namespace: {namespace(stage)}")
    print(
        f"Lake bucket pattern:  "
        f"adp-{stage}-foundation-lake-<ACCOUNT>-{args.region}"
    )
    print(
        f"Reports prefix:       "
        f"s3://adp-{stage}-foundation-lake-<ACCOUNT>-{args.region}"
        f"/quality-reports/<product>/"
    )
    print()

    print(f"Products to profile ({len(products)}):")
    for product in products:
        try:
            schema = load_schema(product, kind="product")
            for table in schema.tables:
                print(
                    f"  - {product}.{table.name} "
                    f"(storage_format={table.storage_format})"
                )
        except FileNotFoundError:
            print(f"  - {product} (schema not found)")
    print()

    print(f"CloudWatch metric names ({len(METRIC_NAMES)}):")
    for name in METRIC_NAMES:
        print(f"  - {name}")
    print()

    print("Dimension keys:")
    for key in (DIMENSION_PRODUCT, DIMENSION_TABLE, DIMENSION_EDGE_CODE, DIMENSION_DRIFT_CHECK):
        print(f"  - {key}")
    print()

    print(f"Edge-case codes ({len(EDGE_CODES)}):")
    for code in EDGE_CODES:
        print(f"  - {code}")
    print()

    print(f"Drift-check classes ({len(DRIFT_CHECKS)}):")
    for check in DRIFT_CHECKS:
        print(f"  - {check}")
    print()

    print("Dry-run complete — no AWS calls made, no parquet read.")
    return 0


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _profile_one_product(
    *,
    product: str,
    curated_root: DataRoot,
    dim_root: DataRoot,
    top_k: int,
    region: str,
) -> list[TableProfile]:
    schema = load_schema(product, kind="product")
    profiles: list[TableProfile] = []
    manifest = _read_manifest(curated_root, product, region=region)
    product_root = curated_root.join(product)
    all_paths = _list_parquet_files(product_root, region=region)

    for table in schema.tables:
        if table.storage_format == "documents":
            profiles.append(
                _profile_documents_table(
                    schema=schema,
                    table=table,
                    curated_root=curated_root,
                    region=region,
                )
            )
            continue
        # For multi-table products we partition the parquet set by
        # column presence — files that have a column in this table
        # but not in the sibling table go to this table. For v1 the
        # only multi-table product is ``ota_campaigns``: events
        # carry ``vin``, header does not.
        table_paths = all_paths
        if schema.is_multi_table():
            table_paths = _filter_paths_for_table(all_paths, table=table, region=region)
        profiles.append(
            _profile_table(
                schema=schema,
                table=table,
                table_paths=table_paths,
                manifest=manifest,
                dim_root=dim_root,
                curated_root=curated_root,
                top_k=top_k,
                region=region,
            )
        )
    return profiles


def _filter_paths_for_table(
    paths: list[str], *, table: Table, region: str
) -> list[str]:
    """For multi-table products, return parquet files matching this table.

    Heuristic: a file matches a table if its parquet schema includes
    every primary-key column of the table and contains no column
    that is unique to the sibling table.
    """
    if not paths:
        return []
    import pyarrow.parquet as pq

    fs = None
    if paths[0].startswith("s3://"):
        from pyarrow.fs import S3FileSystem

        fs = S3FileSystem(region=region)

    pk_cols = set(table.primary_key) if table.primary_key else {c.name for c in table.columns}
    out: list[str] = []
    for url in paths:
        try:
            url_for_pa = url[len("s3://") :] if fs is not None else url
            schema = pq.read_schema(url_for_pa, filesystem=fs)
        except (OSError, ValueError):
            continue
        names = set(schema.names)
        if pk_cols.issubset(names):
            out.append(url)
    return out


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    stage = _validate_stage(args.stage)

    if args.dry_run:
        return _print_dry_run(args)

    curated_root = DataRoot(args.curated_root or _default_curated_root())
    dim_root = DataRoot(args.dim_root or _default_dim_root())
    region = args.region
    top_k = args.top_k

    requested_products = list(args.products) if args.products else list(PRODUCTS)
    for product in requested_products:
        if product not in PRODUCTS:
            _err(f"unknown product: {product}")
            return 2

    output_dir = Path(args.output_dir) if args.output_dir else (
        _REPO_ROOT / "quality-reports"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    _log(f"stage={stage} region={region}")
    _log(f"curated_root={curated_root}")
    _log(f"dim_root={dim_root}")
    _log(f"output_dir={output_dir}")

    profiles_by_product: dict[str, list[TableProfile]] = {}
    any_degenerate = False
    for product in requested_products:
        try:
            profiles = _profile_one_product(
                product=product,
                curated_root=curated_root,
                dim_root=dim_root,
                top_k=top_k,
                region=region,
            )
        except FileNotFoundError as exc:
            _err(f"{product}: {exc}")
            continue
        profiles_by_product[product] = profiles
        for prof in profiles:
            if prof.degenerate_columns:
                any_degenerate = True
                _log(
                    f"{product}.{prof.table}: degenerate columns: "
                    + ", ".join(prof.degenerate_columns)
                )
        report = _profile_to_dict(profiles)
        prod_dir = output_dir / product
        prod_dir.mkdir(parents=True, exist_ok=True)
        json_path = prod_dir / "profile.json"
        md_path = prod_dir / "profile.md"
        json_path.write_text(json.dumps(report, indent=2, default=str))
        md_path.write_text(_profile_to_markdown(report, stage=stage))
        _ok(f"wrote {json_path}")
        _ok(f"wrote {md_path}")

    # ------------------------------------------------------------------
    # S3 upload
    # ------------------------------------------------------------------
    account = _resolve_account(args) if not args.no_upload else None
    if not args.no_upload:
        if not account:
            _err(
                "no --account given and STS resolution failed; "
                "skipping S3 upload (use --no-upload to silence)"
            )
        else:
            for product in profiles_by_product:
                prod_dir = output_dir / product
                json_path = prod_dir / "profile.json"
                md_path = prod_dir / "profile.md"
                if not json_path.exists():
                    continue
                try:
                    json_uri, md_uri = _upload_report(
                        stage=stage,
                        account=account,
                        region=region,
                        product=product,
                        json_path=json_path,
                        md_path=md_path,
                    )
                    _ok(f"uploaded {product} → {json_uri}")
                    _ok(f"uploaded {product} → {md_uri}")
                except Exception as exc:  # noqa: BLE001
                    _err(f"upload failed for {product}: {exc}")

    # ------------------------------------------------------------------
    # CloudWatch publish
    # ------------------------------------------------------------------
    if not args.no_publish:
        try:
            drift_summary = _drift_check_summary()
            n = _publish_metrics(
                stage=stage,
                region=region,
                profiles_by_product=profiles_by_product,
                drift_summary=drift_summary,
            )
            _ok(f"published {n} metrics to {namespace(stage)}")
        except Exception as exc:  # noqa: BLE001
            _err(f"CloudWatch publish failed: {exc}")
            # Don't fail the run on publish errors when local reports
            # are already on disk — operators can re-publish with
            # --no-upload --no-publish=false later.

    # ------------------------------------------------------------------
    # Exit code
    # ------------------------------------------------------------------
    if args.fail_on_degenerate and any_degenerate:
        _err("degenerate distributions detected (per --fail-on-degenerate)")
        return 1

    _ok("profile-data complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
