"""
Daily Tire Health Check — batch prediction for slow leak detection.

Runs once per day via EventBridge schedule. Queries last 7 days of tire telemetry,
computes pressure trends, calls SageMaker batch transform for ambiguous cases,
and writes predictive warnings to the maintenance-alerts table.

Why daily and not real-time:
  A slow leak drops 0.5-1.2 PSI/day. The window from "detectable trend" to
  "hard alert at 28 PSI" is 3-7 days. Checking daily gives 4+ days of warning.
  Checking every 15 minutes gives the same warning — the extra granularity
  doesn't help for a condition that changes over days.

  Cost: ~$0.02/day (batch transform) vs $83/month (real-time endpoint).
  At 50 vehicles with ~2 slow leaks/year, real-time costs $1,000/year
  to save $2,000-3,400. Daily batch is effectively free.
"""

import boto3
import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

# ---------------------------------------------------------------------------
# Required configuration — fail closed with a clear message.
#
# Why no defaults: the original defaults were AWS_REGION="us-east-2" and
# DEPLOYMENT_STAGE="prod".  Nothing in this portfolio is us-east-2 + prod;
# the CMS staging tables are in us-west-2.  A fail-safe default plus the
# wrong value produced a component that reported success while reading nothing
# (the orphan-endpoint pattern — three occurrences in this portfolio).
# Spec § D2; decisions.md 2026-08-10.
# ---------------------------------------------------------------------------

def _require_env(name: str) -> str:
    """Return os.environ[name] or raise ValueError naming the missing variable."""
    value = os.environ.get(name)
    if not value:
        raise ValueError(
            f"Required environment variable '{name}' is not set. "
            f"Set it to the correct value before deploying — "
            f"see docs/DEPLOYMENT.md § Per-Stage Parameters."
        )
    return value


# Region where the CMS DynamoDB tables live (us-west-2 for staging).
# Distinct from AWS_REGION (where this Lambda runs — us-east-1 for ADP).
CMS_TABLE_REGION: str = _require_env("CMS_TABLE_REGION")

# CMS deployment stage whose tables this Lambda reads/writes (e.g. "staging").
CMS_STAGE: str = _require_env("CMS_STAGE")

LOOKBACK_DAYS = 7
MIN_READINGS = 10  # Need at least 10 readings to compute a trend

# The four tire-pressure attributes this Lambda analyses.
TIRE_ATTRS = ("tire_pressure_fl", "tire_pressure_fr", "tire_pressure_rl", "tire_pressure_rr")

# ---------------------------------------------------------------------------
# Pagination safety bounds (issue 2026-08-10-daily-tire-check-unpaginated-query-truncation).
#
# Reading the window to completion is the correct behaviour and it is cheap:
# measured 2026-08-10 across 54 staging vehicles, the full 7-day window is
# 976,228 items / 160 pages / ~$0.0013 per run, worst single vehicle 22 pages.
#
# These bounds exist so that growth in fleet size or retention cannot silently
# convert a correct read into a 300s timeout.  Both are LOGGED and COUNTED when
# they bind — an unannounced truncation is the defect being fixed here, so a
# bound that trips quietly would reintroduce it in a new place.
# ---------------------------------------------------------------------------
MAX_PAGES_PER_VEHICLE = 60      # ~3x the measured worst case (22)
MIN_REMAINING_MILLIS = 30_000   # leave headroom to write alerts and return

# DynamoDB client scoped to the CMS table region (cross-region from this Lambda).
ddb = boto3.resource("dynamodb", region_name=CMS_TABLE_REGION)

# SSM client uses the Lambda's own runtime region (ADP account SSM parameters).
ssm = boto3.client("ssm")


def _remaining_millis(context) -> float:
    """Milliseconds left in this invocation, or +inf when run outside Lambda."""
    getter = getattr(context, "get_remaining_time_in_millis", None)
    if getter is None:
        return float("inf")
    try:
        return float(getter())
    except Exception:
        return float("inf")


def _all_vehicle_ids(vehicles_table) -> list:
    """Every vehicleId in the table, following LastEvaluatedKey.

    Previously a single un-paginated scan.  It returned all 54 staging vehicles
    by luck, and would have begun dropping vehicles from the sweep — silently,
    with no error and no log line — as the fleet grew past one 1 MB page.
    """
    ids: list = []
    start_key = None
    while True:
        kwargs = {"ProjectionExpression": "vehicleId"}
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        resp = vehicles_table.scan(**kwargs)
        ids.extend(v["vehicleId"] for v in resp.get("Items", []))
        start_key = resp.get("LastEvaluatedKey")
        if not start_key:
            return ids


def _read_tire_readings(telemetry_table, vehicle_id: str, cutoff: int, context):
    """Read a vehicle's tire-pressure telemetry across the whole lookback window.

    Returns (rows, pages_read, status) where rows contains only the telemetry
    items that carry at least one tire-pressure attribute, and status is
    "complete" or a string naming the bound that truncated the read.

    Two properties matter here, and the original had neither:

    1. **Paginated.**  A single `query()` returns one <=1 MB page.  On
       VEH-1780081115 that was 272 of 4,643 in-window readings.
    2. **Newest-first** (`ScanIndexForward=False`).  DynamoDB pages ascending by
       default, so page 1 was the *oldest* slice of the window — 67 minutes of
       week-old data, which then failed the `time_span_days < 0.1` guard.  The
       guard meant to reject too-short histories was instead rejecting the
       richest history in the fleet, and `current_pressure` would have been a
       nearly-7-day-old reading stamped `computedAt = now`.

       Direction still matters even though the read is now complete: if a safety
       bound below trips, newest-first keeps the most recent readings, so the
       correctness of `current_pressure` no longer depends on finishing.
    """
    rows: list = []
    pages = 0
    start_key = None
    while True:
        kwargs = dict(
            KeyConditionExpression="vehicleId = :v AND #ts > :cutoff",
            ExpressionAttributeNames={"#ts": "timestamp"},
            ExpressionAttributeValues={":v": vehicle_id, ":cutoff": Decimal(str(cutoff))},
            ProjectionExpression=(
                "vehicleId, #ts, tire_pressure_fl, tire_pressure_fr, "
                "tire_pressure_rl, tire_pressure_rr"
            ),
            ScanIndexForward=False,
        )
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        resp = telemetry_table.query(**kwargs)
        pages += 1

        # Keep only tire-bearing rows.  99.2% of this table is OEM1 cloud
        # telemetry that carries no tire pressure; accumulating it would cost
        # memory for nothing.  Truthiness (not `is not None`) deliberately
        # matches the per-tire filter below so this change alters completeness
        # only — never which readings count as valid.
        rows.extend(r for r in resp.get("Items", []) if any(r.get(a) for a in TIRE_ATTRS))

        start_key = resp.get("LastEvaluatedKey")
        if not start_key:
            return rows, pages, "complete"
        if pages >= MAX_PAGES_PER_VEHICLE:
            return rows, pages, f"truncated:page_cap={MAX_PAGES_PER_VEHICLE}"
        if _remaining_millis(context) < MIN_REMAINING_MILLIS:
            return rows, pages, "truncated:time_budget"


def handler(event=None, context=None):
    """Lambda handler — triggered by EventBridge daily schedule."""
    telemetry_table = ddb.Table(f"cms-{CMS_STAGE}-storage-telemetry")
    alerts_table = ddb.Table(f"cms-{CMS_STAGE}-storage-maintenance-alerts")
    vehicles_table = ddb.Table(f"cms-{CMS_STAGE}-storage-vehicles")

    cutoff = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)
    now = int(datetime.now(timezone.utc).timestamp() * 1000)

    # ---------------------------------------------------------------------------
    # Provenance: fetch model version from SSM at run start (§ D3).
    # The training pipeline writes the model name to /tire-maintenance/model-name
    # after every successful training job.  Reading it here binds each alert to
    # the exact model that produced it — a non-empty value proves the pipeline
    # has run at least once; an SSMParameterNotFound means it has not.
    # ---------------------------------------------------------------------------
    computed_at = datetime.now(timezone.utc).isoformat()
    try:
        model_version: str = ssm.get_parameter(Name="/tire-maintenance/model-name")["Parameter"]["Value"]
    except Exception as exc:
        # Fail loud: if we cannot identify the model, we must not write
        # unattributed rows — AND we must not report success to EventBridge.
        # Returning cleanly here would record a successful invocation for a run
        # that wrote zero alerts, which is the exact failure mode this spec
        # exists to eliminate (spec § D3; review cycle 1 Critical).
        # Raising increments the Lambda error metric, fires CloudWatch alarms,
        # and makes the dead-letter queue receive the event — all recoverable.
        # A nightly job that fails loudly is recoverable; one that fails
        # quietly is what produced this issue in the first place.
        raise RuntimeError(
            f"Cannot fetch model version from SSM (/tire-maintenance/model-name): {exc}. "
            f"The training pipeline must complete at least once before this Lambda "
            f"can write provenance-attributed alerts."
        ) from exc

    # Get all vehicles (paginated — see _all_vehicle_ids)
    vehicles = _all_vehicle_ids(vehicles_table)
    print(f"Checking {len(vehicles)} vehicles for tire pressure trends...")

    # ---------------------------------------------------------------------------
    # Skip accounting (issue 2026-08-10-daily-tire-check-unpaginated-query-truncation).
    #
    # Every path that discards a vehicle or a tire now records WHY.  The most
    # informative signal in the 2026-08-10 investigation was a *missing* log
    # line: the two vehicles that mattered were dropped by silent `continue`s,
    # so the run reported "no anomalies" and looked identical to a healthy fleet.
    # A skip that cannot be counted cannot be alarmed on.
    # ---------------------------------------------------------------------------
    skips: dict = {}
    pages_read = 0
    truncated: list = []

    def _skip(reason: str) -> None:
        skips[reason] = skips.get(reason, 0) + 1

    warnings = []
    for vid in vehicles:
        # Query the full lookback window, newest-first
        try:
            items, pages, status = _read_tire_readings(telemetry_table, vid, cutoff, context)
        except Exception as exc:
            # Previously `except Exception: continue` with no logging, which made
            # a throttle, an AccessDeniedException and a healthy vehicle produce
            # identical output — silence.  Log it, count it, and let the
            # all-vehicles-failed check below decide whether the run is trustworthy.
            print(f"  {vid}: QUERY FAILED ({type(exc).__name__}: {exc})")
            _skip("query_error")
            continue

        pages_read += pages
        if status != "complete":
            # A bound tripped.  Say so — this is the class of defect being fixed.
            print(f"  {vid}: WARNING read {status} after {pages} pages; trend may be partial")
            truncated.append(f"{vid}:{status}")

        if len(items) < MIN_READINGS:
            _skip("below_min_readings_vehicle")
            print(f"  {vid}: {len(items)} tire readings in {LOOKBACK_DAYS}d "
                  f"(<{MIN_READINGS}) across {pages} page(s) -> skipped")
            continue

        # Surface how stale the freshest reading is.  The window admits readings
        # up to LOOKBACK_DAYS old, so "current_pressure" can legitimately be days
        # behind; per the Tier 2 artifact contract staleness is surfaced, not
        # hidden.  Measured 2026-08-10: the freshest real tire reading in staging
        # was 142h old, so this is not a hypothetical.
        newest_ts = max(int(r["timestamp"]) for r in items)
        newest_age_hours = (now - newest_ts) / (1000 * 3600)

        # Compute pressure trend per tire
        for tire in TIRE_ATTRS:
            readings = [(int(r["timestamp"]), float(r[tire])) for r in items if r.get(tire)]
            if len(readings) < MIN_READINGS:
                _skip("below_min_readings_tire")
                continue

            readings.sort()
            pressures = [p for _, p in readings]
            timestamps = [t for t, _ in readings]

            # Simple linear regression for trend
            n = len(pressures)
            x = list(range(n))
            x_mean = sum(x) / n
            y_mean = sum(pressures) / n
            num = sum((x[i] - x_mean) * (pressures[i] - y_mean) for i in range(n))
            den = sum((x[i] - x_mean) ** 2 for i in range(n))
            slope = num / den if den != 0 else 0

            # slope is PSI per reading. Convert to PSI per day.
            time_span_days = (timestamps[-1] - timestamps[0]) / (1000 * 86400)
            if time_span_days < 0.1:  # Need at least ~2 hours of data
                _skip("span_too_short")
                print(f"  {vid} {tire.replace('tire_pressure_', '').upper()}: "
                      f"{len(readings)} readings span only {time_span_days:.3f}d "
                      f"(<0.1) -> skipped")
                continue
            slope_per_day = slope * (n / time_span_days)

            current_pressure = pressures[-1]
            tire_label = tire.replace("tire_pressure_", "").upper()

            print(f"  {vid} {tire_label}: {len(readings)} readings over {time_span_days:.2f}d, "
                  f"slope={slope_per_day:.2f} PSI/day, current={current_pressure:.1f} "
                  f"(newest reading {newest_age_hours:.1f}h old)")

            # Alert if pressure is dropping > 0.3 PSI/day and current pressure < 30
            if not (slope_per_day < -0.3 and current_pressure < 30):
                _skip("no_qualifying_trend")
            if slope_per_day < -0.3 and current_pressure < 30:
                days_to_threshold = (current_pressure - 28) / abs(slope_per_day) if slope_per_day < 0 else 999

                # ---------------------------------------------------------------------------
                # trendMagnitude: the normalised pressure-drop rate (PSI/day), signed.
                #   Stored as a Decimal for DynamoDB compatibility.  This is what the
                #   pipeline actually computes — a trend rate, not a probability.  Keeping
                #   it as a separate field with an accurate name means consumers can decide
                #   their own thresholds without being misled by the field name.
                #   (Review cycle 1 Warning: the original `confidence = min(1.0, |slope|/2.0)`
                #   put this value into a field named confidence, which is a data-contract
                #   defect — a consumer thresholding on "confidence" would discard slow leaks.)
                # ---------------------------------------------------------------------------
                trend_magnitude = Decimal(str(round(slope_per_day, 4)))

                # ---------------------------------------------------------------------------
                # confidence: categorical data-sufficiency score derived from how many
                #   readings the trend was fitted over, against MIN_READINGS.
                #
                #   Mapping (against MIN_READINGS = 10):
                #     high   — 2× MIN_READINGS or more (≥20 readings): robust trend
                #     medium — 1.5× MIN_READINGS to <2× (15–19 readings): adequate
                #     low    — MIN_READINGS to <1.5× (10–14 readings): threshold-minimum
                #
                #   Why categorical and why these thresholds:
                #     A numeric value named "confidence" is routinely interpreted as
                #     P(prediction correct), causing consumers to discard low-magnitude
                #     slow leaks — the exact alerts this pipeline exists to produce.
                #     Categorical vocabulary prevents thresholding on the wrong axis.
                #
                #     The vocabulary "high" | "medium" | "low" matches
                #     cvx/agents/tier2/contract.py's VALID_CONFIDENCES — CVX's Tier 2
                #     agent is the eventual consumer of these rows, and a shared vocabulary
                #     eliminates an otherwise-necessary translation layer.
                #     (Spec § D3 as amended; review cycle 1 Warning; decisions.md 2026-08-10.)
                # ---------------------------------------------------------------------------
                if n >= 2 * MIN_READINGS:
                    confidence_level = "high"
                elif n >= int(1.5 * MIN_READINGS):
                    confidence_level = "medium"
                else:
                    confidence_level = "low"

                warnings.append({
                    # ---- existing CMS-consumed attributes (preserved, additive-only) ----
                    "alertId": f"PRED-{uuid.uuid4().hex[:12]}",
                    "vehicleId": vid,
                    "alertType": "prediction.tire_slow_leak",
                    "severity": "WARNING",
                    "description": (
                        f"Tire {tire_label} pressure trending down: {current_pressure:.1f} PSI, "
                        f"losing {abs(slope_per_day):.2f} PSI/day. "
                        f"Predicted to reach 28 PSI threshold in {days_to_threshold:.0f} days."
                    ),
                    "estimatedCost": Decimal("35"),
                    "timestamp": now,
                    "status": "OPEN",
                    "metadata": {
                        "tire_position": tire_label,
                        "current_pressure": Decimal(str(round(current_pressure, 1))),
                        "slope_psi_per_day": Decimal(str(round(slope_per_day, 3))),
                        "days_to_threshold": Decimal(str(round(max(0, days_to_threshold), 1))),
                        "readings_analyzed": n,
                        "trend_span_days": Decimal(str(round(time_span_days, 2))),
                        # How old the freshest reading behind this alert is.  The
                        # 7-day window admits stale data, so an alert stamped
                        # computedAt=now can rest on days-old readings; recording
                        # the age keeps that visible to whoever acts on it.
                        "newest_reading_age_hours": Decimal(str(round(newest_age_hours, 1))),
                        "model": "linear_trend",
                    },
                    # ---- provenance fields (§ D3) ----
                    # source: stable identifier for ML-produced rows; distinguishes from
                    #   "fwe-uds-dtc" (1,145 rows) and unsourced simulator rules (605 rows).
                    "source": "adp-tire-ml",
                    # modelVersion: training pipeline writes this to SSM after each job.
                    #   Zero rows in the 1,750-row table carried this before § D3 — its
                    #   absence made a never-run pipeline indistinguishable from a working one.
                    "modelVersion": model_version,
                    # trendMagnitude: signed PSI/day rate from linear regression (negative = dropping).
                    #   Reports the actual computed quantity; consumers can apply their own thresholds.
                    "trendMagnitude": trend_magnitude,
                    # confidence: categorical data-sufficiency ("high" | "medium" | "low").
                    #   Derived from reading count, not from slope.  Matches VALID_CONFIDENCES
                    #   in cvx/agents/tier2/contract.py for zero-translation CVX consumption.
                    "confidence": confidence_level,
                    # computedAt: ISO-8601 timestamp of when this inference ran.
                    #   Makes staleness visible — Tier 1 agent can say "as of <date>".
                    "computedAt": computed_at,
                })

    # Write warnings
    if warnings:
        with alerts_table.batch_writer() as batch:
            for w in warnings:
                batch.put_item(Item=w)
        print(f"⚠️ {len(warnings)} predictive warnings written")
    else:
        print("✅ No tire pressure anomalies detected")

    # ---------------------------------------------------------------------------
    # Run accounting.  "Zero alerts" is a legitimate result for a healthy fleet
    # and a symptom of a broken read, and before this the two were
    # indistinguishable in the logs.  Publish enough for a reader (or an alarm)
    # to tell them apart: how much was read, and why each candidate was dropped.
    # ---------------------------------------------------------------------------
    print(f"Read {pages_read} telemetry page(s) across {len(vehicles)} vehicle(s). "
          f"Skips: {skips or 'none'}")
    if truncated:
        print(f"⚠️ {len(truncated)} vehicle(s) truncated by a safety bound: {truncated}")

    # A systemic read failure — no vehicle readable — must not report success.
    # Same reasoning as the SSM guard above: a nightly job that fails loudly is
    # recoverable, one that fails quietly is what produced this issue.  A partial
    # failure is surfaced via query_errors rather than raised, so one throttled
    # vehicle cannot abort a sweep of 54.
    if vehicles and skips.get("query_error", 0) == len(vehicles):
        raise RuntimeError(
            f"Telemetry read failed for all {len(vehicles)} vehicles — see the "
            f"per-vehicle QUERY FAILED lines above. Refusing to report a "
            f"successful run that read nothing."
        )

    return {
        "warnings": len(warnings),
        "vehicles_checked": len(vehicles),
        "telemetry_pages_read": pages_read,
        "query_errors": skips.get("query_error", 0),
        "truncated_reads": len(truncated),
        "skips": skips,
    }


if __name__ == "__main__":
    handler()
