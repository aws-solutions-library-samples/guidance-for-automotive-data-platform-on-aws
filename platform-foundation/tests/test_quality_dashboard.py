"""Pre-deploy validation for the data quality / observability dashboard.

Satisfies the Group 5 task verify:

    `aws cloudwatch get-dashboard --dashboard-name
    adp-staging-foundation-data-quality --region us-east-1` returns
    valid JSON (or, if pre-deploy: dashboard JSON parses and references
    valid metric names).

Pre-deploy mode — no AWS credentials required.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make ``from quality_dashboard.metrics import ...`` work without installing
# the package — mirror the conftest pattern that adds source/lib/ to sys.path.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_QUALITY_DIR = _REPO_ROOT / "source"
if str(_QUALITY_DIR) not in sys.path:
    sys.path.insert(0, str(_QUALITY_DIR))

# The package directory is ``source/quality-dashboard/`` (kebab-case in
# the spec'd path — matches existing ``data-products/`` and
# ``athena-queries/`` siblings). Python doesn't import kebab-case
# package names, so we add the directory itself and import its
# submodules directly.
_PKG_DIR = _REPO_ROOT / "source" / "quality-dashboard"
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

import dashboard as dashboard_mod  # noqa: E402
import metrics as metrics_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Namespace + dashboard-name contract
# ---------------------------------------------------------------------------


class TestNamespaceContract:
    """The user's Group 5 directive specifies the namespace + dashboard name."""

    def test_staging_namespace(self) -> None:
        assert metrics_mod.namespace("staging") == "ADP/Foundation/staging"

    def test_prod_namespace(self) -> None:
        assert metrics_mod.namespace("prod") == "ADP/Foundation/prod"

    def test_invalid_stage_rejected(self) -> None:
        with pytest.raises(ValueError, match="staging"):
            metrics_mod.namespace("dev")
        with pytest.raises(ValueError):
            metrics_mod.namespace("")

    def test_dashboard_name_staging(self) -> None:
        assert (
            metrics_mod.dashboard_name("staging")
            == "adp-staging-foundation-data-quality"
        )

    def test_dashboard_name_prod(self) -> None:
        assert (
            metrics_mod.dashboard_name("prod") == "adp-prod-foundation-data-quality"
        )


# ---------------------------------------------------------------------------
# Catalog completeness
# ---------------------------------------------------------------------------


class TestCatalog:
    def test_nine_products(self) -> None:
        # 9 products in the foundation catalog per spec.md "Data product
        # catalog" — this is the contract the dashboard renders against.
        assert len(metrics_mod.PRODUCTS) == 9
        assert len(set(metrics_mod.PRODUCTS)) == 9  # unique

    def test_ten_tables(self) -> None:
        # 9 products + multi-table OTA split → 10 (product, table) pairs.
        assert len(metrics_mod.TABLES) == 10

    def test_ota_campaigns_split(self) -> None:
        ota_tables = [t for p, t in metrics_mod.TABLES if p == "ota_campaigns"]
        assert ota_tables == ["ota_campaigns", "ota_campaign_events"]

    def test_six_edge_codes(self) -> None:
        assert len(metrics_mod.EDGE_CODES) == 6
        # Codes match docs/tech.md edge-case taxonomy and
        # source/lib/product_generator.py EDGE_CASE_CODES tuple.
        assert set(metrics_mod.EDGE_CODES) == {
            "missing_required",
            "late_arrival",
            "schema_drift",
            "bad_pii",
            "orphan_fk",
            "outlier_value",
        }

    def test_three_drift_checks(self) -> None:
        # spec.md "Drift-detection test design" defines 3 checks.
        assert len(metrics_mod.DRIFT_CHECKS) == 3
        assert set(metrics_mod.DRIFT_CHECKS) == {
            "TestKeyFormats",
            "TestVSSColumnPresence",
            "TestPartitionConventions",
        }

    def test_products_match_schema_dirs(self) -> None:
        """Catalog matches the on-disk schema YAMLs.

        Hard fail if a product is added to the schema YAMLs without
        being added to PRODUCTS. The future profile-data.py reads
        PRODUCTS to drive its publish loop, so missing entries =
        missing dashboard widgets.
        """
        schema_dirs = sorted(
            d.name
            for d in (_REPO_ROOT / "source" / "data-products").iterdir()
            if d.is_dir() and (d / "schema.yaml").exists()
        )
        # PRODUCTS may use a different ordering for display reasons,
        # but the SET must match.
        assert set(metrics_mod.PRODUCTS) == set(schema_dirs), (
            f"PRODUCTS catalog drift detected. "
            f"On-disk: {schema_dirs}. "
            f"Catalog: {metrics_mod.PRODUCTS}. "
            f"Update source/quality-dashboard/metrics.py:PRODUCTS."
        )


# ---------------------------------------------------------------------------
# Dashboard body — JSON parses, schema is valid, metrics resolve
# ---------------------------------------------------------------------------


@pytest.fixture(params=["staging", "prod"])
def stage(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def body(stage: str) -> dict:
    return dashboard_mod.build_dashboard_body(stage, region="us-east-1")


class TestDashboardBody:
    def test_body_is_dict(self, body: dict) -> None:
        assert isinstance(body, dict)

    def test_body_has_widgets(self, body: dict) -> None:
        assert "widgets" in body
        assert isinstance(body["widgets"], list)
        assert len(body["widgets"]) > 0

    def test_body_serialises_to_json(self, body: dict) -> None:
        # CloudWatch put-dashboard requires the body to be JSON. If
        # the builder ever emits a non-serialisable object (e.g., a
        # Path or datetime) this fails the pre-deploy gate.
        text = json.dumps(body)
        assert "widgets" in text

    def test_body_under_size_limit(self, body: dict) -> None:
        # CloudWatch dashboard body limit is 100 KB.
        text = json.dumps(body)
        assert len(text.encode("utf-8")) < 102_400, (
            f"Dashboard body exceeds 100 KB limit: {len(text.encode())} bytes"
        )

    def test_every_widget_has_required_fields(self, body: dict) -> None:
        for i, widget in enumerate(body["widgets"]):
            assert "type" in widget, f"widget[{i}] missing type"
            assert widget["type"] in ("metric", "text", "log", "alarm"), (
                f"widget[{i}] has unknown type {widget['type']!r}"
            )
            for key in ("x", "y", "width", "height"):
                assert key in widget, f"widget[{i}] missing {key}"
                assert isinstance(widget[key], int)
            assert "properties" in widget

    def test_widgets_within_grid_width(self, body: dict) -> None:
        # CloudWatch dashboards are 24 columns wide. A widget that
        # extends past column 24 renders broken.
        for i, widget in enumerate(body["widgets"]):
            right_edge = widget["x"] + widget["width"]
            assert right_edge <= 24, (
                f"widget[{i}] extends past grid (x={widget['x']}, "
                f"width={widget['width']})"
            )


class TestMetricReferences:
    def test_namespace_per_stage_only(self, body: dict, stage: str) -> None:
        # Every metric widget references the per-stage namespace —
        # no cross-stage contamination.
        nss = dashboard_mod.referenced_namespaces(body)
        assert nss == {metrics_mod.namespace(stage)}, (
            f"expected only {{ADP/Foundation/{stage}}}, got {nss}"
        )

    def test_metric_names_in_catalog(self, body: dict) -> None:
        # Every metric name referenced by the dashboard is in
        # METRIC_NAMES — catches typos at pre-deploy.
        names = dashboard_mod.referenced_metric_names(body)
        unknown = names - set(metrics_mod.METRIC_NAMES)
        assert not unknown, (
            f"dashboard references unknown metric names: {unknown}; "
            f"known: {metrics_mod.METRIC_NAMES}"
        )

    def test_all_metric_names_used(self, body: dict) -> None:
        # The 6 metric names defined in metrics.py must ALL appear in
        # the dashboard. If a future PR drops a metric from the
        # catalog without removing the widget, this test holds the
        # contract; if a metric is added to the catalog without a
        # widget, this test holds that contract too.
        names = dashboard_mod.referenced_metric_names(body)
        missing = set(metrics_mod.METRIC_NAMES) - names
        assert not missing, (
            f"metric names defined in catalog but not used by dashboard: "
            f"{missing}"
        )

    def test_dimension_values_in_catalog(self, body: dict) -> None:
        """Every dimension value in the body is from the published catalog.

        Catches typos like ``Product=vehicle_telemetry_aggreggated``
        before they ship.
        """
        valid_tables = {t for _, t in metrics_mod.TABLES}
        valid_products_or_tables = valid_tables | set(metrics_mod.PRODUCTS)
        valid_edge_codes = set(metrics_mod.EDGE_CODES)
        valid_drift_checks = set(metrics_mod.DRIFT_CHECKS)

        for widget in body["widgets"]:
            if widget.get("type") != "metric":
                continue
            for entry in widget["properties"].get("metrics", []):
                if not isinstance(entry, list):
                    continue
                # Walk dim_key, dim_val pairs after the (namespace,
                # metric_name) prefix and before any trailing options
                # dict.
                i = 2
                while i < len(entry) - 1:
                    if isinstance(entry[i], dict):
                        break
                    dim_key = entry[i]
                    dim_val = entry[i + 1]
                    if isinstance(dim_val, dict):
                        break
                    if dim_key in (metrics_mod.DIMENSION_PRODUCT, metrics_mod.DIMENSION_TABLE):
                        assert dim_val in valid_products_or_tables, (
                            f"unknown {dim_key}={dim_val}"
                        )
                    elif dim_key == metrics_mod.DIMENSION_EDGE_CODE:
                        assert dim_val in valid_edge_codes, (
                            f"unknown EdgeCode={dim_val}"
                        )
                    elif dim_key == metrics_mod.DIMENSION_DRIFT_CHECK:
                        assert dim_val in valid_drift_checks, (
                            f"unknown DriftCheck={dim_val}"
                        )
                    i += 2


# ---------------------------------------------------------------------------
# Required widget categories — the user's Group 5 directive lists 5 sections
# ---------------------------------------------------------------------------


class TestRequiredWidgetCategories:
    """Each of the five categories the user enumerated must be present."""

    def test_per_product_row_count_widget(self, body: dict) -> None:
        names = dashboard_mod.referenced_metric_names(body)
        assert metrics_mod.METRIC_ROW_COUNT in names

    def test_edge_case_aggregate_widget(self, body: dict) -> None:
        names = dashboard_mod.referenced_metric_names(body)
        assert metrics_mod.METRIC_EDGE_CASE_AGGREGATE_RATE in names

    def test_per_edge_code_breakdown(self, body: dict) -> None:
        # 6 widgets — one per EdgeCode — each referencing
        # METRIC_EDGE_CODE_RATE with a different EdgeCode dimension.
        edge_widgets = []
        for widget in body["widgets"]:
            if widget.get("type") != "metric":
                continue
            for entry in widget["properties"].get("metrics", []):
                if (
                    isinstance(entry, list)
                    and len(entry) >= 2
                    and entry[1] == metrics_mod.METRIC_EDGE_CODE_RATE
                ):
                    edge_widgets.append(widget)
                    break
        assert len(edge_widgets) >= 6, (
            f"expected ≥6 EdgeCodeRate widgets, got {len(edge_widgets)}"
        )

    def test_drift_detection_summary(self, body: dict) -> None:
        names = dashboard_mod.referenced_metric_names(body)
        assert metrics_mod.METRIC_DRIFT_CHECK_PASSED in names
        assert metrics_mod.METRIC_DRIFT_CHECK_FAILED in names

    def test_last_seed_run_timestamp(self, body: dict) -> None:
        names = dashboard_mod.referenced_metric_names(body)
        assert metrics_mod.METRIC_LAST_SEED_RUN_TIMESTAMP in names

    def test_header_text_widget(self, body: dict) -> None:
        text_widgets = [w for w in body["widgets"] if w.get("type") == "text"]
        assert len(text_widgets) >= 1
        # Header should reference the stage and namespace.
        md = text_widgets[0]["properties"]["markdown"]
        assert "Data Quality" in md
        assert "Namespace" in md or "namespace" in md.lower()


# ---------------------------------------------------------------------------
# CLI smoke test — `python dashboard.py --stage staging --print-name`
# ---------------------------------------------------------------------------


class TestCli:
    def test_print_name_staging(self, capsys: pytest.CaptureFixture) -> None:
        rc = dashboard_mod.main(["--stage", "staging", "--print-name"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "adp-staging-foundation-data-quality" in captured.out

    def test_emit_body_staging(self, capsys: pytest.CaptureFixture) -> None:
        rc = dashboard_mod.main(["--stage", "staging"])
        assert rc == 0
        captured = capsys.readouterr()
        # Body emitted to stdout — must be valid JSON.
        parsed = json.loads(captured.out)
        assert "widgets" in parsed

    def test_emit_body_to_file(self, tmp_path: Path) -> None:
        out = tmp_path / "dash.json"
        rc = dashboard_mod.main(["--stage", "prod", "--output", str(out)])
        assert rc == 0
        assert out.exists()
        parsed = json.loads(out.read_text())
        assert "widgets" in parsed
