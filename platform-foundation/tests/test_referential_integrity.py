"""Zero-orphan-FK assertion across all 9 products.

For every product table that declares foreign_keys, every FK value
in the curated parquet must appear in the referenced dimension /
parent table's primary-key column. Spec Constraint #5: zero orphan
VINs, customer_ids, supplier_ids across products.

Tests skip pre-Group-3 with clear reason.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import schema_loader as sl  # noqa: E402


def _dim_path(dimension_root: Path, name: str) -> Path:
    return dimension_root / name / "data.parquet"


def _curated_paths(curated_root: Path, name: str) -> list[Path]:
    """Return all parquet files under ``curated_root/<name>/``."""
    p = curated_root / name
    if not p.exists():
        return []
    return list(p.rglob("*.parquet"))


def _read_parquet_column(parq: Path, col: str):
    """Read a single column from a parquet file without dataset auto-discovery.

    Group-3 generators emit Hive-partitioned trees that include the partition
    column INSIDE the parquet file in addition to the directory path
    (``write_partitioned_parquet`` base-class behavior). ``pq.read_table(path)``
    invokes the dataset machinery, which infers the partition column from the
    path and fails to merge it with the in-file column (``int32`` vs
    ``dictionary<int32>``). Direct ``ParquetFile.read`` bypasses the dataset
    layer and reads the file straight, which is what we want for FK-closure
    integrity checks.
    """
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(str(parq))
    return pf.read(columns=[col]).to_pandas()


def _has_column(parq: Path, col: str) -> bool:
    import pyarrow.parquet as pq

    return col in pq.ParquetFile(str(parq)).schema_arrow.names


# --- Schema-only: every product's FK targets are in the allowed dimension set ---


def test_every_fk_targets_known_dimension(product_names):
    """Static check: every foreign_key.references_table must be a real dimension or
    the ota_campaigns parent — no typos or accidental references."""
    allowed_targets = sl._VALID_DIMENSION_REFS
    for name in product_names:
        s = sl.load_schema(name, kind="product")
        for tbl in s.tables:
            for fk in tbl.foreign_keys:
                assert fk.references_table in allowed_targets, (
                    f"{name}.{tbl.name}.{fk.column} -> "
                    f"{fk.references_table} is not in allowed targets"
                )


def test_every_pii_id_column_has_regex_pattern(product_names):
    """Every column that's an ID-shaped FK should have a regex pattern enforcing
    the format documented in data-contracts.md."""
    id_columns = {"vin", "customer_id", "dealer_id", "supplier_id", "part_number", "station_id"}
    for name in product_names:
        s = sl.load_schema(name, kind="product")
        for tbl in s.tables:
            for c in tbl.columns:
                if c.name in id_columns:
                    assert c.pattern is not None, (
                        f"{name}.{tbl.name}.{c.name} is an ID column but has no regex pattern"
                    )


# --- Data-presence assertions (skipped pre-Group-3) --------------------------


def _to_plain_array(chunked):
    """Combine a ChunkedArray to a single Array, decoding dictionary encoding.

    Keeps everything in Arrow's C++-backed columnar form. Avoids the
    ``set(table.to_pandas()[col])`` path, which materializes a Python
    object ndarray element-by-element (``cast.py:result[i]=obj``) — an
    O(N) hang for the 5M-row ``vins`` / ``customers`` dimensions.
    """
    import pyarrow as pa

    arr = chunked.combine_chunks()
    if pa.types.is_dictionary(arr.type):
        arr = arr.dictionary_decode()
    return arr


def _assert_zero_orphan_for_dimension(
    dimension_root: Path,
    curated_root: Path,
    product_names: list[str],
    *,
    dim_name: str,
    fk_target: str,
    fk_column: str,
    pk_column: str,
) -> None:
    """Shared assertion: every value of ``fk_column`` in any product that
    references ``fk_target`` must be a member of the dimension's PK column.

    This is the single implementation that ``test_zero_orphan_vins`` /
    ``..._customer_ids`` / ``..._dealer_ids`` / ``..._station_ids`` all
    delegate to — keeps the four checks structurally identical so future
    refactors land in one place.

    Performance: the membership test runs entirely in pyarrow.compute
    (``pc.is_in`` against an Arrow value-set), not via a Python ``set`` +
    pandas ``.isin``. The dimension PK columns are 5M rows (``vins``,
    ``customers``); the prior ``set(read_table(...).to_pandas()[col])``
    construction materialized a 5M-element object ndarray and hung past
    180s. The vectorized form is C++-backed and column-projected.
    """
    dim_p = _dim_path(dimension_root, dim_name)
    if not dim_p.exists():
        pytest.skip(f"{dim_name} dimension not generated yet")
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    # Build the value-set ONCE as an Arrow array (no Python set).
    valid_arr = _to_plain_array(
        pq.read_table(str(dim_p), columns=[pk_column]).column(pk_column)
    )

    for product in product_names:
        s = sl.load_schema(product, kind="product")
        for tbl in s.tables:
            if not any(fk.references_table == fk_target for fk in tbl.foreign_keys):
                continue

            # Collect the FK column from every parquet of this product, then run
            # a SINGLE pc.is_in per product. pc.is_in rebuilds the value-set hash
            # table on every call, so calling it per-file rebuilt the 5M-row hash
            # ~4,700× (CPU-bound, >10min). One call per product cuts that to one
            # hash build per product (~6 total) against the concatenated FK column.
            fk_chunks: list = []
            for parq in _curated_paths(curated_root, product):
                if not _has_column(parq, fk_column):
                    continue
                fk_chunks.append(
                    _to_plain_array(
                        pq.ParquetFile(str(parq)).read(columns=[fk_column]).column(fk_column)
                    )
                )
            if not fk_chunks:
                continue

            col = fk_chunks[0] if len(fk_chunks) == 1 else pa.concat_arrays(fk_chunks)
            # orphan = value present (not null) AND not in the valid set.
            is_member = pc.is_in(col, value_set=valid_arr)
            not_na = pc.is_valid(col)
            orphan_mask = pc.and_(pc.invert(is_member), not_na)
            orphan_count = pc.sum(orphan_mask).as_py() or 0
            assert orphan_count == 0, (
                f"{product}: {orphan_count} orphan {fk_column} values "
                f"detected (not in {dim_name})"
            )


@pytest.mark.needs_curated
@pytest.mark.slow
@pytest.mark.timeout(600)
def test_zero_orphan_vins(dimension_root, curated_root, product_names):
    _assert_zero_orphan_for_dimension(
        dimension_root,
        curated_root,
        product_names,
        dim_name="vins",
        fk_target="vins",
        fk_column="vin",
        pk_column="vin",
    )


@pytest.mark.needs_curated
@pytest.mark.slow
@pytest.mark.timeout(600)
def test_zero_orphan_customer_ids(dimension_root, curated_root, product_names):
    _assert_zero_orphan_for_dimension(
        dimension_root,
        curated_root,
        product_names,
        dim_name="customers",
        fk_target="customers",
        fk_column="customer_id",
        pk_column="customer_id",
    )


@pytest.mark.needs_curated
def test_zero_orphan_dealer_ids(dimension_root, curated_root, product_names):
    _assert_zero_orphan_for_dimension(
        dimension_root,
        curated_root,
        product_names,
        dim_name="dealers",
        fk_target="dealers",
        fk_column="dealer_id",
        pk_column="dealer_id",
    )


@pytest.mark.needs_curated
def test_zero_orphan_station_ids(dimension_root, curated_root, product_names):
    _assert_zero_orphan_for_dimension(
        dimension_root,
        curated_root,
        product_names,
        dim_name="charging_stations",
        fk_target="charging_stations",
        fk_column="station_id",
        pk_column="station_id",
    )


@pytest.mark.needs_curated
def test_zero_orphan_campaign_ids_in_events(curated_root):
    """ota_campaign_events.campaign_id must reference an existing ota_campaigns row.

    ota_campaigns is a multi-table product — the header table is the
    canonical-PK source for campaign_id. We resolve the header parquet
    by filtering files under curated/ota_campaigns/ to those that have a
    campaign_id column AND no vin column (the header tells itself apart
    from the events table by missing vin). The events table has both.
    """
    parqs = _curated_paths(curated_root, "ota_campaigns")
    if not parqs:
        pytest.skip("ota_campaigns curated tree not generated yet")

    header_parqs: list[Path] = []
    event_parqs: list[Path] = []
    for parq in parqs:
        import pyarrow.parquet as pq

        names = set(pq.ParquetFile(str(parq)).schema_arrow.names)
        if "campaign_id" not in names:
            continue
        # Header has campaign_id but no vin; events table has both.
        if "vin" in names:
            event_parqs.append(parq)
        else:
            header_parqs.append(parq)

    if not header_parqs:
        pytest.skip("ota_campaigns header parquet not found in curated tree")
    if not event_parqs:
        pytest.skip("ota_campaign_events parquet not found in curated tree")

    valid_ids: set = set()
    for parq in header_parqs:
        df = _read_parquet_column(parq, "campaign_id")
        valid_ids.update(df["campaign_id"].dropna().tolist())

    for parq in event_parqs:
        df = _read_parquet_column(parq, "campaign_id")
        orphans = ~df["campaign_id"].isin(valid_ids) & df["campaign_id"].notna()
        assert orphans.sum() == 0, (
            f"ota_campaign_events/{parq.name}: {orphans.sum()} "
            f"orphan campaign_ids detected (not present in ota_campaigns header)"
        )


# --- Drift-prefix regression guard (Bug 1: schema_drift bleed into FKs) -------


@pytest.mark.needs_curated
def test_no_drift_prefix_in_fk_columns(curated_root, product_names):
    """No FK-column value should ever start with the literal ``DRIFT-`` prefix.

    Regression guard for the schema_drift bleed bug fixed under
    ``2026-06-03-adp-charging-sessions-fk-drift-fix``: prior to the fix,
    ``EdgeCaseInjector.apply()``'s ``schema_drift`` branch sampled from
    ``edge_case_eligible`` columns intersected with string-typed columns,
    with no FK exclusion. Any FK column tagged
    ``edge_case_eligible: true`` (e.g.
    ``charging_sessions.customer_id``) became a valid candidate and
    received the ``"DRIFT-{cur}"`` prefix, producing orphan FKs at
    ~the schema_drift target rate.

    This test is the deterministic, fast-path complement to
    ``test_zero_orphan_*``: it does NOT load dimension PK sets (which
    can be 100MB+ for the ``customers`` dim — ~30s load) and does NOT
    do membership-tests against millions of valid IDs. It only scans
    FK column values for the literal ``DRIFT-`` prefix, which is
    O(rows) per file.

    Catches Bug-1 regression on small slices in seconds. Passes when
    ``test_zero_orphan_*`` passes; runs much faster on small slices,
    so it's the gate of choice for inner-loop development on the
    edge-case injectors.

    Production injector emits ``f"DRIFT-{cur}"`` (case-sensitive,
    literal prefix). Match is anchored to the start of the string.
    """
    import pyarrow.parquet as pq

    # Resolve every (product, table, fk_column) tuple from schema YAMLs.
    # The injector applies edge-case codes to every product; FK columns on
    # any product are equally vulnerable to the same bleed.
    fk_targets: list[tuple[str, str, str]] = []
    for product in product_names:
        s = sl.load_schema(product, kind="product")
        for tbl in s.tables:
            for fk in tbl.foreign_keys:
                fk_targets.append((product, tbl.name, fk.column))

    if not fk_targets:
        pytest.skip("no FK columns declared across products — nothing to scan")

    # Group fk_columns per product so we open each parquet file only
    # once and read all FK columns present in that file in a single
    # pass.
    fk_by_product: dict[str, set[str]] = {}
    for product, _tbl, fk_col in fk_targets:
        fk_by_product.setdefault(product, set()).add(fk_col)

    total_files_scanned = 0
    for product, fk_cols in fk_by_product.items():
        for parq in _curated_paths(curated_root, product):
            schema_names = set(pq.ParquetFile(str(parq)).schema_arrow.names)
            present = sorted(fk_cols & schema_names)
            if not present:
                continue
            df = pq.ParquetFile(str(parq)).read(columns=present).to_pandas()
            total_files_scanned += 1
            for col in present:
                # ``DRIFT-`` is a literal ASCII prefix; no regex needed.
                # ``str.startswith`` on pandas StringDtype handles NA via
                # ``na=False`` (FK NAs are legitimate per nullable schema).
                hits = df[col].astype("string").str.startswith("DRIFT-", na=False)
                hit_count = int(hits.sum())
                assert hit_count == 0, (
                    f"{product}/{parq.name}: {hit_count} value(s) in FK "
                    f"column '{col}' start with 'DRIFT-' — schema_drift "
                    f"injector regressed; FK columns must be excluded "
                    f"from the candidate set in EdgeCaseInjector.apply"
                )

    if total_files_scanned == 0:
        pytest.skip("no parquet files with FK columns found in curated tree")
