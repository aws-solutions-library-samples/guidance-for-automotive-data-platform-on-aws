"""Build the CloudWatch dashboard body for ADP Foundation data quality.

Per the user's Group 5 directive:

* Dashboard name: ``adp-{stage}-foundation-data-quality``
* Metric namespace: ``ADP/Foundation/{stage}``

The dashboard surfaces:

1. **Per-product row counts** — one bar widget showing the latest
   ``RowCount`` per Iceberg table (10 entries — 9 products plus the
   ota_campaigns split). KB chunks are reported on the same widget.
2. **Edge-case aggregate rate per product** — one widget showing each
   product's overall edge-case fraction. The 1–3% target band is
   visible in the y-axis annotation so operators can spot drift.
3. **Per-EdgeCode rate per product** — one widget per edge-case code
   (six total) showing the per-product rate breakdown so an isolated
   ``bad_pii`` regression on one product is visible.
4. **Drift-detection summary** — pass/fail counts per
   ``DriftCheck`` for the latest cycle.
5. **Last-regenerated timestamp** — the most recent successful seed
   run timestamp per product (Unix epoch seconds — readable in the
   CloudWatch console tooltip as a human-readable date/time).

The dashboard body is a JSON-serialisable dict matching CloudWatch's
documented schema:
https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/CloudWatch-Dashboard-Body-Structure.html

Two delivery paths are supported:

* **JSON-only (descopable)** — :func:`build_dashboard_body` returns
  the dict; the deploy script ``scripts/deploy-quality-dashboard.sh``
  calls ``aws cloudwatch put-dashboard``. No CDK stack required.
* **CDK construct** — :class:`QualityDashboard` wraps the body in a
  ``CfnDashboard`` resource for inclusion in a future stack.

CLI
---

::

    # Emit the dashboard body to stdout (or to a file via redirect)
    python platform-foundation/source/quality-dashboard/dashboard.py \\
        --stage staging > /tmp/dashboard.json

    # Apply via aws cli (driven by scripts/deploy-quality-dashboard.sh)
    aws cloudwatch put-dashboard \\
        --dashboard-name adp-staging-foundation-data-quality \\
        --dashboard-body file:///tmp/dashboard.json \\
        --region us-east-1 --no-cli-pager
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Iterable

# The containing directory uses kebab-case (``quality-dashboard``)
# matching siblings ``data-products/`` and ``athena-queries/``, so
# it is NOT a Python package. ``dashboard.py`` and ``metrics.py``
# are loaded as top-level modules — the test fixture and the CLI
# both add this directory to ``sys.path``. When this module is
# imported as a script, Python's argv handling already adds its
# parent directory to ``sys.path``; when imported by the test, the
# test's conftest does the same.
import os as _os
import sys as _sys

_THIS_DIR = _os.path.dirname(_os.path.abspath(__file__))
if _THIS_DIR not in _sys.path:
    _sys.path.insert(0, _THIS_DIR)

from metrics import (  # noqa: E402
    DIMENSION_DRIFT_CHECK,
    DIMENSION_EDGE_CODE,
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
    dashboard_name,
    namespace,
)


# ---------------------------------------------------------------------------
# Layout constants (CloudWatch grid is 24 columns wide)
# ---------------------------------------------------------------------------

GRID_WIDTH = 24
HEADER_HEIGHT = 3
ROW_COUNT_HEIGHT = 8
EDGE_CASE_HEIGHT = 6
DRIFT_HEIGHT = 6
TIMESTAMP_HEIGHT = 6


# ---------------------------------------------------------------------------
# Widget builders
# ---------------------------------------------------------------------------


def _header_widget(stage: str, region: str) -> dict[str, Any]:
    """Top-of-dashboard markdown explaining what the dashboard monitors."""
    ns = namespace(stage)
    md = (
        f"# ADP Foundation — Data Quality (`{stage}`)\n\n"
        f"**Namespace:** `{ns}` &nbsp;|&nbsp; "
        f"**Region:** `{region}` &nbsp;|&nbsp; "
        f"**Owner:** platform-team\n\n"
        f"Metrics published by `scripts/profile-data.py` (Group 6) and the "
        f"drift-detection test suite (`tests/test_data_contracts.py`). "
        f"Per-product row counts, edge-case injection rates, drift-check "
        f"pass/fail per cycle, and last-seed-run timestamps. "
        f"Edge-case rates are expected in the **1–3%** band per product; "
        f"`orphan_fk` rate is **0%** by design (counter-example, never "
        f"injected). For taxonomy: `docs/tech.md` § Edge-Case Taxonomy. "
        f"Runbook: `platform-foundation/source/quality-dashboard/README.md`."
    )
    return {
        "type": "text",
        "x": 0,
        "y": 0,
        "width": GRID_WIDTH,
        "height": HEADER_HEIGHT,
        "properties": {"markdown": md},
    }


def _metric_dim(*pairs: tuple[str, str]) -> list[str]:
    """Compose a CloudWatch metric dimension list ``[name1, value1, ...]``."""
    flat: list[str] = []
    for k, v in pairs:
        flat.extend([k, v])
    return flat


def _row_count_widget(stage: str, region: str, y: int) -> dict[str, Any]:
    """Bar chart with the latest ``RowCount`` per table.

    Uses ``view: bar`` + ``stat: Maximum`` over a 30-day window so the
    widget shows the most-recent published row count per table even
    when the seed cadence is irregular.
    """
    ns = namespace(stage)
    metrics: list[list[Any]] = []
    for product, table in TABLES:
        # Render label as "<product>" when product == table, otherwise
        # "<product>.<table>" so the multi-table OTA case is unambiguous.
        label = table if product == table else f"{product}.{table}"
        metrics.append(
            [
                ns,
                METRIC_ROW_COUNT,
                DIMENSION_TABLE,
                table,
                {"label": label},
            ]
        )
    return {
        "type": "metric",
        "x": 0,
        "y": y,
        "width": GRID_WIDTH,
        "height": ROW_COUNT_HEIGHT,
        "properties": {
            "view": "bar",
            "stacked": False,
            "title": "Row count per table (latest)",
            "region": region,
            "stat": "Maximum",
            "period": 86400,  # 1 day — seeds run on-demand, not on a schedule
            "metrics": metrics,
            "yAxis": {"left": {"min": 0, "showUnits": False}},
            "liveData": False,
        },
    }


def _edge_case_aggregate_widget(stage: str, region: str, y: int) -> dict[str, Any]:
    """Bar chart of the aggregate edge-case rate per product.

    Annotated with horizontal lines at 0.01 and 0.03 (the 1–3% target
    band per spec) so an out-of-band product is visually obvious.
    """
    ns = namespace(stage)
    metrics: list[list[Any]] = []
    for product in PRODUCTS:
        metrics.append(
            [
                ns,
                METRIC_EDGE_CASE_AGGREGATE_RATE,
                DIMENSION_TABLE,
                product,
                {"label": product},
            ]
        )
    return {
        "type": "metric",
        "x": 0,
        "y": y,
        "width": GRID_WIDTH // 2,
        "height": EDGE_CASE_HEIGHT,
        "properties": {
            "view": "bar",
            "stacked": False,
            "title": "Edge-case aggregate rate per product (target 1–3%)",
            "region": region,
            "stat": "Average",
            "period": 86400,
            "metrics": metrics,
            "yAxis": {
                "left": {"min": 0, "max": 0.05, "showUnits": False, "label": "rate"}
            },
            "annotations": {
                "horizontal": [
                    {"label": "low band (1%)", "value": 0.01},
                    {"label": "high band (3%)", "value": 0.03},
                ]
            },
            "liveData": False,
        },
    }


def _edge_code_widget(
    stage: str, region: str, y: int, x: int, width: int, height: int, code: str
) -> dict[str, Any]:
    """Per-EdgeCode breakdown across products (one widget per code)."""
    ns = namespace(stage)
    metrics: list[list[Any]] = []
    # Show each product as a separate metric so operators can see
    # which product is the outlier.
    for product in PRODUCTS:
        metrics.append(
            [
                ns,
                METRIC_EDGE_CODE_RATE,
                DIMENSION_TABLE,
                product,
                DIMENSION_EDGE_CODE,
                code,
                {"label": product},
            ]
        )
    title_suffix = " (target 0%)" if code == "orphan_fk" else ""
    return {
        "type": "metric",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "properties": {
            "view": "bar",
            "stacked": False,
            "title": f"EdgeCodeRate · {code}{title_suffix}",
            "region": region,
            "stat": "Average",
            "period": 86400,
            "metrics": metrics,
            "yAxis": {"left": {"min": 0, "showUnits": False}},
            "liveData": False,
        },
    }


def _drift_check_widget(stage: str, region: str, y: int) -> dict[str, Any]:
    """Drift-detection pass/fail summary table.

    One row per drift check, two columns per check (pass count, fail
    count) summed over the last 30 days.
    """
    ns = namespace(stage)
    metrics: list[list[Any]] = []
    for check in DRIFT_CHECKS:
        metrics.append(
            [
                ns,
                METRIC_DRIFT_CHECK_PASSED,
                DIMENSION_DRIFT_CHECK,
                check,
                {"label": f"{check} · passed"},
            ]
        )
        metrics.append(
            [
                ns,
                METRIC_DRIFT_CHECK_FAILED,
                DIMENSION_DRIFT_CHECK,
                check,
                {"label": f"{check} · failed", "color": "#d13212"},
            ]
        )
    return {
        "type": "metric",
        "x": 0,
        "y": y,
        "width": GRID_WIDTH // 2,
        "height": DRIFT_HEIGHT,
        "properties": {
            "view": "singleValue",
            "stacked": False,
            "title": "Drift-detection cycle summary (sum, last 30d)",
            "region": region,
            "stat": "Sum",
            "period": 2592000,  # 30 days — count cycles
            "metrics": metrics,
            "setPeriodToTimeRange": True,
            "sparkline": True,
            "liveData": False,
        },
    }


def _last_seed_widget(stage: str, region: str, y: int, x: int) -> dict[str, Any]:
    """Single-value widget showing the most-recent seed-run timestamp.

    Per product. Value is Unix epoch seconds; CloudWatch console
    renders it as a number with the timestamp tooltip.
    """
    ns = namespace(stage)
    metrics: list[list[Any]] = []
    for product in PRODUCTS:
        metrics.append(
            [
                ns,
                METRIC_LAST_SEED_RUN_TIMESTAMP,
                DIMENSION_TABLE,
                product,
                {"label": product},
            ]
        )
    return {
        "type": "metric",
        "x": x,
        "y": y,
        "width": GRID_WIDTH // 2,
        "height": TIMESTAMP_HEIGHT,
        "properties": {
            "view": "singleValue",
            "stacked": False,
            "title": "Last seed-run timestamp per product (Unix epoch sec)",
            "region": region,
            "stat": "Maximum",
            "period": 86400,
            "metrics": metrics,
            "setPeriodToTimeRange": True,
            "sparkline": False,
            "liveData": False,
        },
    }


# ---------------------------------------------------------------------------
# Top-level body builder
# ---------------------------------------------------------------------------


def build_dashboard_body(stage: str, region: str = "us-east-1") -> dict[str, Any]:
    """Assemble the full CloudWatch dashboard body for ``stage``.

    The body is a Python dict; serialise with :func:`json.dumps` and
    pass to ``aws cloudwatch put-dashboard --dashboard-body
    file://...``.

    Layout (row offsets in dashboard grid units):

    * 0..3   header
    * 3..11  row count per table
    * 11..17 edge-case aggregate (left) + drift summary (right)
    * 17..23 last seed-run timestamp (full-width, two cols of single-value)
    * 23..   per-EdgeCode breakdown grid (3x2: 6 codes)
    """
    if stage not in ("staging", "prod"):
        raise ValueError(
            f"stage must be 'staging' or 'prod' (got {stage!r})"
        )

    widgets: list[dict[str, Any]] = []

    # Header
    widgets.append(_header_widget(stage, region))

    # Row counts (full width)
    y = HEADER_HEIGHT
    widgets.append(_row_count_widget(stage, region, y))
    y += ROW_COUNT_HEIGHT

    # Edge-case aggregate (left half) + drift summary (right half) on same row
    widgets.append(_edge_case_aggregate_widget(stage, region, y))
    drift = _drift_check_widget(stage, region, y)
    drift["x"] = GRID_WIDTH // 2
    widgets.append(drift)
    y += EDGE_CASE_HEIGHT

    # Last seed-run timestamp split into two halves so the 9 products
    # render in two readable columns.
    widgets.append(_last_seed_widget(stage, region, y, 0))
    # Right half — same metrics, but limited; for now duplicate the
    # widget on both halves so operators see all 9 with sparkline-off
    # singleValue tiles. CloudWatch caps singleValue tiles at ~12
    # metrics per widget; 9 fits cleanly in one widget, so the right
    # half hosts a sparkline-on copy for trend visibility.
    sparkline_copy = _last_seed_widget(stage, region, y, GRID_WIDTH // 2)
    sparkline_copy["properties"]["sparkline"] = True
    sparkline_copy["properties"]["title"] = "Last seed-run trend (sparkline)"
    widgets.append(sparkline_copy)
    y += TIMESTAMP_HEIGHT

    # Per-EdgeCode breakdown grid: 3 columns × 2 rows = 6 codes.
    edge_widget_w = GRID_WIDTH // 3
    edge_widget_h = 6
    for i, code in enumerate(EDGE_CODES):
        col = i % 3
        row = i // 3
        widgets.append(
            _edge_code_widget(
                stage,
                region,
                y + row * edge_widget_h,
                col * edge_widget_w,
                edge_widget_w,
                edge_widget_h,
                code,
            )
        )

    return {"widgets": widgets}


# ---------------------------------------------------------------------------
# Validation helpers (used by the unit test for the pre-deploy verify path)
# ---------------------------------------------------------------------------


def referenced_metric_names(body: dict[str, Any]) -> set[str]:
    """Return the set of CloudWatch metric names referenced by ``body``."""
    out: set[str] = set()
    for widget in body.get("widgets", []):
        if widget.get("type") != "metric":
            continue
        for entry in widget.get("properties", {}).get("metrics", []):
            # CloudWatch metric entries are flat lists:
            #   [namespace, metric_name, dim_key, dim_val, ..., {opts}]
            if isinstance(entry, list) and len(entry) >= 2:
                out.add(entry[1])
    return out


def referenced_namespaces(body: dict[str, Any]) -> set[str]:
    """Return the set of namespaces referenced by ``body``."""
    out: set[str] = set()
    for widget in body.get("widgets", []):
        if widget.get("type") != "metric":
            continue
        for entry in widget.get("properties", {}).get("metrics", []):
            if isinstance(entry, list) and len(entry) >= 1:
                out.add(entry[0])
    return out


# ---------------------------------------------------------------------------
# CDK construct (optional delivery path)
# ---------------------------------------------------------------------------

try:  # pragma: no cover — exercised only when CDK is on the venv path
    from aws_cdk import aws_cloudwatch as _cw
    from constructs import Construct as _Construct

    class QualityDashboard(_Construct):  # type: ignore[misc]
        """CDK construct: builds the CloudWatch dashboard for one stage.

        The construct issues a single ``CfnDashboard`` resource
        (``Type: AWS::CloudWatch::Dashboard``) with the body from
        :func:`build_dashboard_body`. cdk-nag is a no-op for
        CfnDashboard.

        Usage
        -----

        ::

            from quality_dashboard.dashboard import QualityDashboard

            QualityDashboard(self, "DataQuality", stage="staging")
        """

        def __init__(
            self,
            scope: _Construct,
            construct_id: str,
            *,
            stage: str,
            region: str = "us-east-1",
        ) -> None:
            super().__init__(scope, construct_id)
            body = build_dashboard_body(stage, region=region)
            self.dashboard = _cw.CfnDashboard(
                self,
                "Resource",
                dashboard_name=dashboard_name(stage),
                dashboard_body=json.dumps(body),
            )

except ImportError:  # pragma: no cover — CDK is optional for this module
    QualityDashboard = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quality-dashboard",
        description=(
            "Build the ADP Foundation data-quality CloudWatch dashboard "
            "body. Emits JSON to stdout (or to --output)."
        ),
    )
    parser.add_argument(
        "--stage",
        required=True,
        choices=["staging", "prod"],
        help="Foundation stage. Drives namespace + dashboard name.",
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region (default: us-east-1; foundation pin).",
    )
    parser.add_argument(
        "--output",
        default="-",
        help=(
            "Output path for the JSON body. '-' (default) writes to "
            "stdout. Use a file path to redirect."
        ),
    )
    parser.add_argument(
        "--print-name",
        action="store_true",
        help=(
            "Instead of emitting the body, print the dashboard name "
            "for the given stage and exit."
        ),
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_argparser().parse_args(list(argv) if argv is not None else None)

    if args.print_name:
        print(dashboard_name(args.stage))
        return 0

    body = build_dashboard_body(args.stage, region=args.region)
    text = json.dumps(body, indent=2, sort_keys=False)

    if args.output == "-":
        sys.stdout.write(text)
        sys.stdout.write("\n")
    else:
        with open(args.output, "w") as f:
            f.write(text)
            f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
