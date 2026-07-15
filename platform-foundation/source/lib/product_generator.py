"""Shared helpers for ADP foundation Group 3 product generators.

Provides:

- ``EdgeCaseInjector`` — applies the six edge-case codes per
  ``docs/tech.md`` "Edge-Case Taxonomy" with calibrated rates.
- ``write_partitioned_parquet`` — writes a pandas DataFrame as
  partitioned parquet (one file per partition value) using the
  pyarrow schema from a ``schema_loader.Table``.
- ``write_manifest`` — writes ``manifest.json`` capturing seed,
  row count, edge-case codes, generation timestamp, and SHA-256
  over the parquet bytes.
- ``upload_to_s3`` — uploads a local directory tree to an
  ``s3://...`` prefix (used when ``--output-root s3://...``).
- ``register_iceberg_table`` — builds the Athena DDL via
  ``schema_loader.Table.iceberg_ddl`` and submits it to Athena
  via ``boto3``. Idempotent; ignores AlreadyExistsException.

All functions are pure (no module-level side effects) and importable
without AWS credentials. AWS calls happen only when explicitly
invoked.

Used by every Group 3 product generator.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Allow direct execution (`python source/lib/product_generator.py ...`)
# as well as import (`from product_generator import ...`).
_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from schema_loader import Schema, Table, load_schema  # noqa: E402


# ---------------------------------------------------------------------------
# Edge-case taxonomy (docs/tech.md). Six codes, calibrated rates.
# orphan_fk target rate is 0% — production data has zero orphan FKs.
# ---------------------------------------------------------------------------

EDGE_CASE_CODES = (
    "missing_required",
    "late_arrival",
    "schema_drift",
    "bad_pii",
    "orphan_fk",
    "outlier_value",
)

EDGE_CASE_RATES: dict[str, float] = {
    "missing_required": 0.0075,
    "late_arrival": 0.005,
    "schema_drift": 0.0035,
    "bad_pii": 0.002,
    "orphan_fk": 0.0,  # counter-example
    "outlier_value": 0.004,
}


@dataclass
class EdgeCaseInjector:
    """Applies edge-case injections to a pandas DataFrame.

    Operates in-place on the DataFrame copies passed in (caller controls
    pre-injection snapshot). Records the injection summary so the
    manifest can capture rates.

    The injector chooses cells to perturb deterministically from the
    seed; same seed → same perturbations.
    """

    seed: int
    table: Table
    rates: dict[str, float] = None  # type: ignore

    def __post_init__(self) -> None:
        if self.rates is None:
            self.rates = dict(EDGE_CASE_RATES)
        self._rng = np.random.default_rng(self.seed + 9001)
        self.summary: dict[str, int] = {code: 0 for code in EDGE_CASE_CODES}

    def _eligible_columns(self) -> list[str]:
        return [c.name for c in self.table.columns if c.edge_case_eligible]

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply edge-case codes to ``df`` and return the perturbed frame.

        The DataFrame is modified by reference for performance.

        Each branch gates on its own column-set (per cycle-3 fix:
        ``bad_pii`` no longer requires an ``edge_case_eligible`` column —
        it has its own ``pii_drift_target`` set, so an early return on
        empty ``eligible`` would mask it).
        """
        n = len(df)
        if n == 0:
            return df
        eligible = self._eligible_columns()

        # missing_required: set a sample of edge_case_eligible columns to NaN
        miss_n = int(n * self.rates["missing_required"])
        if miss_n > 0 and eligible:
            idx = self._rng.choice(n, size=miss_n, replace=False)
            cols = self._rng.choice(eligible, size=miss_n)
            for i, col in zip(idx, cols):
                # Only set null if the column is nullable in the schema.
                col_obj = self.table.column_by_name(str(col))
                if col_obj is not None and col_obj.nullable:
                    df.iat[i, df.columns.get_loc(col)] = None
            self.summary["missing_required"] = miss_n

        # late_arrival: shift ingest_time forward 1-3 days for a sample
        if "ingest_time" in df.columns:
            late_n = int(n * self.rates["late_arrival"])
            if late_n > 0:
                idx = self._rng.choice(n, size=late_n, replace=False)
                shifts = self._rng.integers(1, 4, size=late_n).astype("int64")
                for i, s in zip(idx, shifts):
                    if pd.notna(df.at[i, "ingest_time"]):
                        df.at[i, "ingest_time"] = df.at[i, "ingest_time"] + pd.Timedelta(days=int(s))
                self.summary["late_arrival"] = late_n

        # schema_drift: prepend "DRIFT-" to a sample of string-eligible cells.
        # Per 2026-06-02 fix (within-quota-seed spec, decisions.md "STOP at
        # Group 2"): exclude FK columns from the candidate set. The
        # symmetric fix was applied to ``bad_pii`` in closed-spec review
        # cycle 3 but missed for ``schema_drift`` — bleeding produced
        # ``DRIFT-CUST-…``/``DRIFT-STN-…`` orphans in charging_sessions
        # (67,819 customer_id orphans @ 0.34%, matches drift target rate).
        # README.md contract: "schema_drift 0.35% on enum columns",
        # "orphan_fk 0.00% (counter-example, never injected)".
        drift_n = int(n * self.rates["schema_drift"])
        if drift_n > 0:
            fk_columns = {fk.column for fk in self.table.foreign_keys}
            string_eligible = [
                c for c in eligible
                if (col := self.table.column_by_name(c)) is not None
                and col.type == "string"
                and c not in fk_columns
            ]
            if string_eligible:
                idx = self._rng.choice(n, size=drift_n, replace=False)
                cols = self._rng.choice(string_eligible, size=drift_n)
                for i, col in zip(idx, cols):
                    cur = df.iat[i, df.columns.get_loc(col)]
                    if pd.notna(cur):
                        df.iat[i, df.columns.get_loc(col)] = f"DRIFT-{cur}"
                self.summary["schema_drift"] = drift_n

        # bad_pii: malform a sample of NON-FK pii_drift_target columns.
        # Per review.md cycle 3 Warning: corrupting FK columns (vin /
        # customer_id / dealer_id / station_id / campaign_id) folded
        # bad_pii into orphan_fk and broke spec Constraints #5 + #6.
        # Now we restrict the corruption candidate set to columns the
        # schema explicitly tags ``pii_drift_target: true`` — by
        # convention these are non-FK PII text columns (e.g.,
        # customer_360.email, customer_interactions.notes,
        # service_records.complaint_text). When the table has zero
        # such columns, this branch is a no-op and the summary stays
        # at 0 — the structural-zero contract.
        pii_n = int(n * self.rates["bad_pii"])
        if pii_n > 0:
            pii_drift_columns = [
                c.name
                for c in self.table.columns
                if c.pii_drift_target and c.name in df.columns
            ]
            if pii_drift_columns:
                idx = self._rng.choice(n, size=pii_n, replace=False)
                cols = self._rng.choice(pii_drift_columns, size=pii_n)
                for i, col in zip(idx, cols):
                    cur = df.iat[i, df.columns.get_loc(col)]
                    if pd.notna(cur) and isinstance(cur, str) and len(cur) > 1:
                        # Insert an invalid char (lowercase 'i') that
                        # breaks any well-formed-PII regex check at the
                        # data-contracts layer.
                        df.iat[i, df.columns.get_loc(col)] = cur[:1] + "i" + cur[2:]
                self.summary["bad_pii"] = pii_n
            # else: no pii_drift_target column on this table — skip
            # silently. summary["bad_pii"] stays 0.

        # orphan_fk: target = 0%. We don't inject; the production rate is 0
        # by construction. The summary stays at 0.
        self.summary["orphan_fk"] = 0

        # outlier_value: place a value 5-10x outside range for a sample of numeric columns
        out_n = int(n * self.rates["outlier_value"])
        if out_n > 0:
            num_eligible = [
                c for c in eligible
                if (col := self.table.column_by_name(c)) is not None
                and col.type in ("int", "bigint", "double") and col.range is not None
            ]
            if num_eligible:
                idx = self._rng.choice(n, size=out_n, replace=False)
                cols = self._rng.choice(num_eligible, size=out_n)
                for i, col in zip(idx, cols):
                    col_obj = self.table.column_by_name(str(col))
                    assert col_obj is not None and col_obj.range is not None
                    lo, hi = col_obj.range
                    # 5-10x above hi. Coerce to int when target dtype is
                    # Int32/Int64-backed (pandas integer extension dtypes raise
                    # TypeError on float .iat assignment — Group 3 smoke regression).
                    multiplier = float(self._rng.uniform(5.0, 10.0))
                    new_val = (
                        int(float(hi) * multiplier)
                        if col_obj.type in ("int", "bigint")
                        else float(hi) * multiplier
                    )
                    df.iat[i, df.columns.get_loc(col)] = new_val
                self.summary["outlier_value"] = out_n

        return df


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def write_partitioned_parquet(
    df: pd.DataFrame,
    *,
    table: Table,
    output_dir: Path,
    partition_col: str | None = None,
) -> list[Path]:
    """Write a DataFrame as parquet, partitioned by ``partition_col``.

    Returns the list of parquet files written.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []

    # Build pyarrow schema from the Table.
    fields = []
    for c in table.columns:
        if c.type == "decimal":
            assert c.decimal_precision is not None and c.decimal_scale is not None
            ty: pa.DataType = pa.decimal128(c.decimal_precision, c.decimal_scale)
        elif c.type == "string":
            ty = pa.string()
        elif c.type == "int":
            ty = pa.int32()
        elif c.type == "bigint":
            ty = pa.int64()
        elif c.type == "double":
            ty = pa.float64()
        elif c.type == "boolean":
            ty = pa.bool_()
        elif c.type == "timestamp":
            ty = pa.timestamp("us", tz="UTC")
        elif c.type == "date":
            ty = pa.date32()
        elif c.type == "array<string>":
            ty = pa.list_(pa.string())
        elif c.type == "array<int>":
            ty = pa.list_(pa.int32())
        else:
            raise ValueError(f"Unsupported type {c.type}")
        fields.append(pa.field(c.name, ty, nullable=c.nullable))
    schema = pa.schema(fields)

    if partition_col is None or partition_col not in df.columns:
        # Single-file write
        out_path = output_dir / "data.parquet"
        try:
            arrow_tbl = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
        except Exception:
            arrow_tbl = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_table(arrow_tbl, out_path, compression="zstd")
        files.append(out_path)
        return files

    # Partitioned write: one file per partition value.
    for part_value, part_df in df.groupby(partition_col, dropna=False):
        part_str = (
            "__null__" if pd.isna(part_value) else str(part_value)
        )
        part_dir = output_dir / f"{partition_col}={part_str}"
        part_dir.mkdir(parents=True, exist_ok=True)
        out_path = part_dir / "data.parquet"
        try:
            arrow_tbl = pa.Table.from_pandas(part_df, schema=schema, preserve_index=False)
        except Exception:
            arrow_tbl = pa.Table.from_pandas(part_df, preserve_index=False)
        pq.write_table(arrow_tbl, out_path, compression="zstd")
        files.append(out_path)
    return files


def write_manifest(
    *,
    output_dir: Path,
    product: str,
    table: str,
    seed: int,
    row_count: int,
    edge_case_summary: dict[str, int],
    elapsed_seconds: float,
    files: list[Path],
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write ``manifest.json`` capturing generation metadata + file checksums."""
    output_dir.mkdir(parents=True, exist_ok=True)
    file_records = []
    for f in files:
        if not f.exists():
            continue
        sha = hashlib.sha256()
        with f.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                sha.update(chunk)
        file_records.append(
            {
                "relpath": str(f.relative_to(output_dir)),
                "size_bytes": f.stat().st_size,
                "sha256": sha.hexdigest(),
            }
        )
    manifest = {
        "product": product,
        "table": table,
        "seed": seed,
        "row_count": row_count,
        "edge_case_summary": edge_case_summary,
        "edge_case_aggregate_rate": (
            sum(edge_case_summary.values()) / row_count if row_count > 0 else 0.0
        ),
        "elapsed_seconds": round(elapsed_seconds, 2),
        "generated_at_utc": pd.Timestamp.utcnow().isoformat(),
        "files": file_records,
    }
    if extra:
        manifest.update(extra)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
    return manifest_path


# ---------------------------------------------------------------------------
# S3 + Athena helpers (lazy imports — module is importable without boto3)
# ---------------------------------------------------------------------------


def upload_to_s3(local_dir: Path, s3_uri: str, *, region: str = "us-east-1") -> int:
    """Upload every file under ``local_dir`` to ``s3_uri`` (recursive).

    Returns number of files uploaded.
    """
    import boto3

    if not s3_uri.startswith("s3://"):
        raise ValueError(f"s3_uri must start with s3://, got {s3_uri}")
    bucket, prefix = s3_uri.replace("s3://", "").split("/", 1)
    if prefix and not prefix.endswith("/"):
        prefix = prefix + "/"
    s3 = boto3.client("s3", region_name=region)
    count = 0
    for f in local_dir.rglob("*"):
        if not f.is_file():
            continue
        key = prefix + str(f.relative_to(local_dir))
        s3.upload_file(str(f), bucket, key)
        count += 1
    return count


def _athena_run(
    query: str,
    *,
    workgroup: str,
    region: str,
    output_location: str,
    timeout_s: int = 300,
) -> tuple[str, str]:
    """Run an Athena query, return (query_id, final_state)."""
    import boto3

    athena = boto3.client("athena", region_name=region)
    qid = athena.start_query_execution(
        QueryString=query,
        WorkGroup=workgroup,
        ResultConfiguration={"OutputLocation": output_location},
    )["QueryExecutionId"]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = athena.get_query_execution(QueryExecutionId=qid)
        state = resp["QueryExecution"]["Status"]["State"]
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            return qid, state
        time.sleep(2)
    return qid, "TIMEOUT"


def register_iceberg_table(
    schema: Schema,
    table: Table,
    *,
    s3_data_root: str,
    region: str = "us-east-1",
    workgroup: str = "primary",
    athena_output: str | None = None,
) -> tuple[str, str]:
    """Create the Iceberg table in Athena via DDL.

    Idempotent — uses ``CREATE TABLE IF NOT EXISTS``-style by catching
    AlreadyExistsException via Athena's error mapping (the DDL itself
    does NOT include IF NOT EXISTS because Iceberg DDL syntax doesn't
    support it on Athena Engine V3 for CTAS-style creates; we wrap in
    error tolerance).

    ``s3_data_root`` is the S3 prefix where the parquet for THIS table
    lives. Example:
    ``s3://adp-foundation-lake-<acct>-us-east-1/curated/charging_sessions/``.

    Returns (query_id, state).
    """
    if athena_output is None:
        athena_output = s3_data_root.rstrip("/") + "/athena-results/"
    if not s3_data_root.endswith("/"):
        s3_data_root = s3_data_root + "/"

    db = schema.iceberg_database()
    ddl = table.iceberg_ddl(database=db, location=s3_data_root)
    qid, state = _athena_run(
        ddl,
        workgroup=workgroup,
        region=region,
        output_location=athena_output,
    )
    if state == "FAILED":
        # Inspect failure — ignore "table already exists"
        import boto3

        athena = boto3.client("athena", region_name=region)
        reason = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"][
            "Status"
        ].get("StateChangeReason", "")
        if "already exists" in reason.lower() or "AlreadyExistsException" in reason:
            return qid, "SUCCEEDED_IDEMPOTENT"
        raise RuntimeError(f"Athena DDL failed: {reason}")
    return qid, state


# ---------------------------------------------------------------------------
# Base generator
# ---------------------------------------------------------------------------


class ProductGenerator:
    """Base class for fact-table generators.

    Subclasses provide:
    - ``product_name`` (class attribute)
    - ``generate_table(table, scale, seed, dimensions)`` returning a
      ``pd.DataFrame`` for a single table.

    The base class handles edge-case injection, parquet writing,
    manifest writing, and (optionally) Athena table registration.
    """

    product_name: str = ""  # override

    # Optional: extra dimensions to load that aren't FK-referenced (e.g., parts
    # used in service_records.parts_used array<string> column without a hard FK).
    extra_dimensions: tuple[str, ...] = ()

    def __init__(
        self,
        *,
        seed: int = 42,
        scale: float = 1.0,
        output_root: str = "",
        region: str = "us-east-1",
    ):
        self.seed = seed
        self.scale = scale
        self.output_root = output_root  # local path or s3://...
        self.region = region
        self.schema = load_schema(self.product_name, kind="product")

    # Subclass MUST implement.
    def generate_table(
        self,
        table: Table,
        *,
        seed: int,
        scale: float,
        dimensions: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        raise NotImplementedError

    # Hook for products that need cross-table coordination (e.g., ota_campaigns).
    def post_generate(
        self, frames: dict[str, pd.DataFrame]
    ) -> dict[str, pd.DataFrame]:  # noqa: D401
        return frames

    def load_dimensions(self, dim_root: Path, names: list[str]) -> dict[str, pd.DataFrame]:
        """Load named dimensions from ``dim_root``."""
        out: dict[str, pd.DataFrame] = {}
        for n in names:
            p = dim_root / n / "data.parquet"
            if not p.exists():
                raise FileNotFoundError(f"Dimension parquet missing: {p}")
            out[n] = pq.read_table(str(p)).to_pandas()
        return out

    def run(
        self,
        *,
        dim_root: Path,
        local_workdir: Path | None = None,
        register_iceberg: bool = False,
        s3_lake_bucket: str | None = None,
    ) -> dict[str, Any]:
        """Top-level generation entry. Returns a summary dict."""
        if local_workdir is None:
            if self.output_root and not self.output_root.startswith("s3://"):
                # Local mode: write directly under <output_root>/<product_name>/
                local_workdir = Path(self.output_root) / self.product_name
            else:
                # S3 mode: stage in /tmp, then upload
                local_workdir = Path("/tmp") / f"adp-curated-{self.product_name}-{self.seed}"
        local_workdir.mkdir(parents=True, exist_ok=True)

        # Determine which dimensions this product needs (from FKs + extras).
        needed: set[str] = set()
        for tbl in self.schema.tables:
            for fk in tbl.foreign_keys:
                if fk.references_table in (
                    "vins", "customers", "dealers", "suppliers", "parts",
                    "charging_stations", "time_calendar",
                ):
                    needed.add(fk.references_table)
        needed.update(self.extra_dimensions)
        if needed:
            print(f"[{self.product_name}] loading dimensions: {sorted(needed)}")
            dimensions = self.load_dimensions(dim_root, sorted(needed))
        else:
            dimensions = {}

        all_frames: dict[str, pd.DataFrame] = {}
        for tbl in self.schema.tables:
            t0 = time.time()
            print(f"[{self.product_name}] generating {tbl.name} (scale={self.scale}) ...")
            df = self.generate_table(
                tbl, seed=self.seed, scale=self.scale, dimensions=dimensions
            )
            print(f"[{self.product_name}]   {len(df):,} rows in {time.time() - t0:.1f}s")
            all_frames[tbl.name] = df

        # Cross-table post-processing
        all_frames = self.post_generate(all_frames)

        summary: dict[str, Any] = {
            "product": self.product_name,
            "tables": {},
        }
        for tbl in self.schema.tables:
            df = all_frames[tbl.name]
            t0 = time.time()
            injector = EdgeCaseInjector(seed=self.seed, table=tbl)
            df = injector.apply(df)

            partition_col = tbl.partition_keys[0] if tbl.partition_keys else None
            tbl_dir = local_workdir / tbl.name
            tbl_dir.mkdir(parents=True, exist_ok=True)
            files = write_partitioned_parquet(
                df, table=tbl, output_dir=tbl_dir, partition_col=partition_col
            )
            elapsed = time.time() - t0
            manifest_path = write_manifest(
                output_dir=tbl_dir,
                product=self.product_name,
                table=tbl.name,
                seed=self.seed,
                row_count=len(df),
                edge_case_summary=injector.summary,
                elapsed_seconds=elapsed,
                files=files,
            )
            summary["tables"][tbl.name] = {
                "row_count": len(df),
                "files_written": len(files),
                "manifest": str(manifest_path),
                "edge_case_summary": injector.summary,
            }

            if self.output_root.startswith("s3://"):
                target = (
                    self.output_root.rstrip("/")
                    + f"/{self.product_name}/{tbl.name}/"
                )
                print(f"[{self.product_name}] uploading {tbl.name} to {target} ...")
                n_uploaded = upload_to_s3(tbl_dir, target, region=self.region)
                summary["tables"][tbl.name]["s3_upload_count"] = n_uploaded

            if register_iceberg and tbl.storage_format == "iceberg" and s3_lake_bucket:
                s3_data_root = (
                    f"s3://{s3_lake_bucket}/curated/{self.product_name}/{tbl.name}/"
                )
                print(f"[{self.product_name}] registering Iceberg table {self.schema.iceberg_database()}.{tbl.name} ...")
                qid, state = register_iceberg_table(
                    self.schema,
                    tbl,
                    s3_data_root=s3_data_root,
                    region=self.region,
                )
                summary["tables"][tbl.name]["athena_query_id"] = qid
                summary["tables"][tbl.name]["athena_state"] = state

        return summary


__all__ = [
    "EDGE_CASE_CODES",
    "EDGE_CASE_RATES",
    "EdgeCaseInjector",
    "ProductGenerator",
    "register_iceberg_table",
    "upload_to_s3",
    "write_manifest",
    "write_partitioned_parquet",
]
