"""Metric contract for the ADP Foundation data quality dashboard.

Single source of truth. Both the dashboard
(``quality_dashboard.dashboard``) and the future profiling pipeline
(``platform-foundation/scripts/profile-data.py``, Group 6) MUST import
names from this module. A typo at one end fails the test in
``platform-foundation/tests/test_quality_dashboard.py`` rather than
silently emitting an empty widget.

Namespace
---------

CloudWatch metric namespace is ``ADP/Foundation/{stage}`` per the user's
Group 5 directive (matches the dashboard name format
``adp-{stage}-foundation-data-quality``). Stage-specific namespaces
keep staging metrics from contaminating prod dashboards and let IAM
``cloudwatch:Namespace`` filters scope publish access per stage.

Dimensions
----------

- ``Product`` (or ``Table`` when a product materialises >1 Iceberg
  table — see :data:`TABLES`). Values are the snake_case technical
  names from the schema YAMLs.
- ``EdgeCode`` — one of the six taxonomy codes from
  ``docs/tech.md`` (and ``EDGE_CASE_RATES`` in
  ``source/lib/product_generator.py``).
- ``DriftCheck`` — pytest class names from spec.md "Drift-detection
  test design" (``TestKeyFormats``, ``TestVSSColumnPresence``,
  ``TestPartitionConventions``).

Metrics
-------

- :data:`METRIC_ROW_COUNT` — row count per Iceberg table (or chunk
  count for ``vehicle_knowledge_base``). Statistic: Maximum.
  Published once per seed/profile run as a Sum-style sample.
- :data:`METRIC_EDGE_CASE_AGGREGATE_RATE` — per-product overall
  edge-case injection fraction. Statistic: Average. Should land in
  [0.01, 0.03] per the spec.
- :data:`METRIC_EDGE_CODE_RATE` — per-product, per-EdgeCode
  injection fraction. Statistic: Average.
- :data:`METRIC_LAST_SEED_RUN_TIMESTAMP` — Unix epoch seconds of the
  most recent successful seed run, per product. Statistic: Maximum.
- :data:`METRIC_DRIFT_CHECK_PASSED` / :data:`METRIC_DRIFT_CHECK_FAILED`
  — count of pass/fail events per drift-check class per cycle.
  Statistic: Sum. Published by ``test_data_contracts.py`` via the
  CI integration in Group 6.

All metric values are unitless except :data:`METRIC_LAST_SEED_RUN_TIMESTAMP`
(seconds — Unix epoch).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Namespace
# ---------------------------------------------------------------------------

#: Base namespace prefix. Combined with stage to form the full namespace.
NAMESPACE_PREFIX = "ADP/Foundation"


def namespace(stage: str) -> str:
    """Return the per-stage CloudWatch metric namespace.

    Per the user's Group 5 directive, the namespace format is
    ``ADP/Foundation/{stage}`` and the dashboard format is
    ``adp-{stage}-foundation-data-quality``.

    Examples
    --------
    >>> namespace("staging")
    'ADP/Foundation/staging'
    >>> namespace("prod")
    'ADP/Foundation/prod'
    """
    if stage not in ("staging", "prod"):
        raise ValueError(
            f"stage must be 'staging' or 'prod' (got {stage!r}); "
            "see staging-prod-design.md §1"
        )
    return f"{NAMESPACE_PREFIX}/{stage}"


# ---------------------------------------------------------------------------
# Dimension names
# ---------------------------------------------------------------------------

DIMENSION_PRODUCT = "Product"
DIMENSION_TABLE = "Table"
DIMENSION_EDGE_CODE = "EdgeCode"
DIMENSION_DRIFT_CHECK = "DriftCheck"


# ---------------------------------------------------------------------------
# Metric names
# ---------------------------------------------------------------------------

METRIC_ROW_COUNT = "RowCount"
METRIC_EDGE_CASE_AGGREGATE_RATE = "EdgeCaseAggregateRate"
METRIC_EDGE_CODE_RATE = "EdgeCodeRate"
METRIC_LAST_SEED_RUN_TIMESTAMP = "LastSeedRunTimestamp"
METRIC_DRIFT_CHECK_PASSED = "DriftCheckPassed"
METRIC_DRIFT_CHECK_FAILED = "DriftCheckFailed"


# ---------------------------------------------------------------------------
# Catalog of valid dimension values (single source of truth — used by both
# the dashboard builder and the metric publisher)
# ---------------------------------------------------------------------------

#: 9 data products in the foundation catalog.
#:
#: Order matches the spec.md "Data product catalog" listing — used as
#: the ordering convention for dashboard widgets so operators see a
#: stable layout across stages.
PRODUCTS: tuple[str, ...] = (
    "vehicle_telemetry_aggregated",
    "vehicle_identity",
    "charging_sessions",
    "energy_usage",
    "ota_campaigns",
    "customer_360",
    "customer_interactions",
    "service_records",
    "vehicle_knowledge_base",
)

#: Iceberg / KB tables with their owning product. ``ota_campaigns`` is
#: the only multi-table product in v1 (header + per-VIN events).
#: ``vehicle_knowledge_base`` materialises as KB chunks rather than an
#: Iceberg table — :data:`METRIC_ROW_COUNT` reports chunk count for it.
TABLES: tuple[tuple[str, str], ...] = (
    ("vehicle_telemetry_aggregated", "vehicle_telemetry_aggregated"),
    ("vehicle_identity", "vehicle_identity"),
    ("charging_sessions", "charging_sessions"),
    ("energy_usage", "energy_usage"),
    ("ota_campaigns", "ota_campaigns"),
    ("ota_campaigns", "ota_campaign_events"),
    ("customer_360", "customer_360"),
    ("customer_interactions", "customer_interactions"),
    ("service_records", "service_records"),
    ("vehicle_knowledge_base", "vehicle_knowledge_base"),
)

#: Six edge-case codes from ``docs/tech.md`` and the
#: ``EDGE_CASE_CODES`` tuple in ``source/lib/product_generator.py``.
#: Order matches that module so dashboard rendering is consistent.
EDGE_CODES: tuple[str, ...] = (
    "missing_required",
    "late_arrival",
    "schema_drift",
    "bad_pii",
    "orphan_fk",
    "outlier_value",
)

#: Drift-detection test classes from spec.md §"Drift-detection test
#: design". Pass/fail counts published per cycle by the
#: integrity-assertion task in Group 6.
DRIFT_CHECKS: tuple[str, ...] = (
    "TestKeyFormats",
    "TestVSSColumnPresence",
    "TestPartitionConventions",
)


# ---------------------------------------------------------------------------
# All metric names (for use in tests / catalog inspection)
# ---------------------------------------------------------------------------

METRIC_NAMES: tuple[str, ...] = (
    METRIC_ROW_COUNT,
    METRIC_EDGE_CASE_AGGREGATE_RATE,
    METRIC_EDGE_CODE_RATE,
    METRIC_LAST_SEED_RUN_TIMESTAMP,
    METRIC_DRIFT_CHECK_PASSED,
    METRIC_DRIFT_CHECK_FAILED,
)


# ---------------------------------------------------------------------------
# Dashboard-name convention
# ---------------------------------------------------------------------------


def dashboard_name(stage: str) -> str:
    """Compose the dashboard name ``adp-{stage}-foundation-data-quality``.

    Examples
    --------
    >>> dashboard_name("staging")
    'adp-staging-foundation-data-quality'
    >>> dashboard_name("prod")
    'adp-prod-foundation-data-quality'
    """
    if stage not in ("staging", "prod"):
        raise ValueError(
            f"stage must be 'staging' or 'prod' (got {stage!r}); "
            "see staging-prod-design.md §1"
        )
    return f"adp-{stage}-foundation-data-quality"
