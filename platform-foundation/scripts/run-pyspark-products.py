#!/usr/bin/env python3
"""ADP PySpark via Glue — one-shot orchestration script.

Spec: ``.kiro/specs/2026-06-09-adp-pyspark-glue-products/``

Runs the 2 PySpark generators (``vehicle_telemetry_aggregated`` and
``energy_usage``) as one-shot Glue 5.1 jobs against the deployed
foundation lake bucket. Patterned after ``scripts/run-spark-spike.sh``
but uses boto3 (Python) for full lifecycle control + structured logging.

Usage::

    # Stage scripts + create jobs (no run):
    python3 scripts/run-pyspark-products.py --stage staging --product both --action stage

    # Run a staged job (sample tier, 10M rows / 90 days):
    python3 scripts/run-pyspark-products.py --stage staging --product telemetry --action run

    # Stage + run in one shot:
    python3 scripts/run-pyspark-products.py --stage staging --product both --action stage-and-run

    # Tear down (deletes Glue jobs; keeps role + scripts in S3):
    python3 scripts/run-pyspark-products.py --stage staging --product both --action teardown

The persistent IAM role (``adp-{stage}-foundation-spark-etl-role-{region}``)
must already exist — deploy ``adp-{stage}-foundation-data-products`` first.

Per spec Constraint #5 (sample tier ≤ $1) and Constraint #6 (30-min
wall-clock cap), this script does NOT raise the row count beyond the
default 10,000,000. The same code path with larger ``--rows`` is the
production-scale upgrade path (P3 follow-up).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Iterable

import boto3
from botocore.exceptions import ClientError

# ----------------------------------------------------------------------------
# Constants — locked per spec decisions / `~/.kiro/steering/cross-region-namespace.md`
# ----------------------------------------------------------------------------

VALID_STAGES = ("staging", "prod")
VALID_PRODUCTS = ("telemetry", "energy", "both")
VALID_ACTIONS = ("stage", "run", "stage-and-run", "teardown")

# Map of internal product key -> (kebab-case slug, source dir, db slug).
PRODUCT_INFO = {
    "telemetry": {
        "slug": "vehicle-telemetry-aggregated",
        "src_dir": "vehicle_telemetry_aggregated",
        "db": "vehicle_telemetry_aggregated",
    },
    "energy": {
        "slug": "energy-usage",
        "src_dir": "energy_usage",
        "db": "energy_usage",
    },
}

# Default sample-tier (locked per spec Constraint #5).
DEFAULT_ROWS = 10_000_000
DEFAULT_DAYS = 90
DEFAULT_PARTITIONS = 64
DEFAULT_SEED = 42
DEFAULT_WORKERS = 2
DEFAULT_WORKER_TYPE = "G.1X"
DEFAULT_TIMEOUT_MIN = 30  # Per spec Constraint #6.

LOG_PREFIX = "[run-pyspark-products]"


# ----------------------------------------------------------------------------
# Logging helpers (match spike-harness convention).
# ----------------------------------------------------------------------------


def log(msg: str) -> None:
    """Stderr-prefixed log."""
    print(f"{LOG_PREFIX} {msg}", file=sys.stderr, flush=True)


def err(msg: str) -> None:
    """Error-tagged log."""
    print(f"{LOG_PREFIX} ERROR: {msg}", file=sys.stderr, flush=True)


# ----------------------------------------------------------------------------
# Argparse + CLI.
# ----------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser. Exposed for testing."""
    parser = argparse.ArgumentParser(
        prog="run-pyspark-products.py",
        description=(
            "Run the 2 PySpark generators (vehicle_telemetry_aggregated, "
            "energy_usage) as one-shot Glue 5.1 jobs."
        ),
    )
    parser.add_argument(
        "--stage", required=True, choices=VALID_STAGES,
        help="Deployment stage. Lowercase only.",
    )
    parser.add_argument(
        "--product", default="both", choices=VALID_PRODUCTS,
        help="Which product(s) to act on (default: both).",
    )
    parser.add_argument(
        "--rows", type=int, default=DEFAULT_ROWS,
        help=(
            f"Rows to generate per product (default: {DEFAULT_ROWS:,} — "
            "sample tier per spec Constraint #5)."
        ),
    )
    parser.add_argument(
        "--days", type=int, default=DEFAULT_DAYS,
        help=f"Rolling window in days (default: {DEFAULT_DAYS}).",
    )
    parser.add_argument(
        "--partitions", type=int, default=DEFAULT_PARTITIONS,
        help=f"Spark partitions (default: {DEFAULT_PARTITIONS}; matches spike).",
    )
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED,
        help=f"Generator seed (default: {DEFAULT_SEED}; deterministic).",
    )
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS,
        help=f"Glue worker count (default: {DEFAULT_WORKERS}; sample tier).",
    )
    parser.add_argument(
        "--worker-type", default=DEFAULT_WORKER_TYPE,
        choices=("G.1X", "G.2X", "G.4X", "G.8X"),
        help=f"Glue worker type (default: {DEFAULT_WORKER_TYPE}).",
    )
    parser.add_argument(
        "--timeout-min", type=int, default=DEFAULT_TIMEOUT_MIN,
        help=(
            f"Glue job timeout in minutes (default: {DEFAULT_TIMEOUT_MIN}; "
            "spec Constraint #6 cost-budget guard)."
        ),
    )
    parser.add_argument(
        "--region", default=os.environ.get("AWS_REGION", "us-east-1"),
        help="AWS region (default: AWS_REGION env or us-east-1).",
    )
    parser.add_argument(
        "--account", default=None,
        help=(
            "AWS account ID (default: live `aws sts get-caller-identity`). "
            "DO NOT pass real account IDs in tests; use the AWS docs "
            "placeholder 123456789012."
        ),
    )
    parser.add_argument(
        "--action", default="stage-and-run", choices=VALID_ACTIONS,
        help="What to do (default: stage-and-run).",
    )
    parser.add_argument(
        "--wait", action=argparse.BooleanOptionalAction, default=True,
        help="Poll until terminal state on `run` (default: --wait).",
    )
    parser.add_argument(
        "--poll-interval-sec", type=int, default=30,
        help="Polling interval seconds (default: 30).",
    )
    return parser


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return _build_parser().parse_args(argv)


# ----------------------------------------------------------------------------
# Resource resolution.
# ----------------------------------------------------------------------------


def _resolve_account(boto3_session: boto3.Session, override: str | None = None) -> str:
    """Return the AWS account ID; live-resolve via STS unless overridden."""
    if override:
        return override
    sts = boto3_session.client("sts")
    return sts.get_caller_identity()["Account"]


def _lake_bucket(stage: str, account: str, region: str) -> str:
    """Compose the foundation lake bucket name (matches foundation_stack.py:120)."""
    return f"adp-{stage}-foundation-lake-{account}-{region}"


def _role_arn(stage: str, account: str, region: str) -> str:
    """Compose the persistent Spark-ETL role ARN (region-suffixed)."""
    return (
        f"arn:aws:iam::{account}:role/"
        f"adp-{stage}-foundation-spark-etl-role-{region}"
    )


def _job_name(stage: str, product_key: str) -> str:
    """Compose the Glue job name (kebab-case slug, stage-scoped)."""
    return f"adp-{stage}-{PRODUCT_INFO[product_key]['slug']}-job"


def _selected_products(arg: str) -> Iterable[str]:
    if arg == "both":
        return ("telemetry", "energy")
    return (arg,)


# ----------------------------------------------------------------------------
# Pre-flight: role exists?
# ----------------------------------------------------------------------------


def _preflight_role(boto3_session: boto3.Session, role_arn: str) -> bool:
    """Return True if the role exists, False otherwise.

    Calling code exits 2 if False — the user must deploy
    ``adp-{stage}-foundation-data-products`` first.
    """
    iam = boto3_session.client("iam")
    role_name = role_arn.rsplit("/", 1)[-1]
    try:
        iam.get_role(RoleName=role_name)
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "NoSuchEntity":
            return False
        raise


# ----------------------------------------------------------------------------
# Stage: upload scripts + create Glue jobs.
# ----------------------------------------------------------------------------


def _project_root() -> Path:
    """Path to the platform-foundation/ project root (this script's parent)."""
    return Path(__file__).resolve().parents[1]


def _upload_scripts(
    boto3_session: boto3.Session,
    *,
    bucket: str,
    region: str,
    products: Iterable[str],
) -> None:
    """Upload generator scripts + product_generator lib to S3."""
    s3 = boto3_session.client("s3", region_name=region)
    root = _project_root()

    # Generator scripts (one per selected product).
    for p in products:
        info = PRODUCT_INFO[p]
        local = root / "source" / "data-products" / info["src_dir"] / "generator.py"
        if not local.exists():
            raise FileNotFoundError(f"Generator missing: {local}")
        key = f"scripts/{info['src_dir']}/generator.py"
        log(f"  uploading {local.name} -> s3://{bucket}/{key}")
        s3.upload_file(str(local), bucket, key)

    # Shared libs (EDGE_CASE_RATES + helpers + schema_loader).
    # `product_generator.py` imports `schema_loader.py` at module level
    # (see `source/lib/product_generator.py:48`); both files MUST live in
    # the same Glue worker directory so the relative import works. We
    # upload BOTH and pass BOTH in `--extra-py-files`. (Discovered via
    # ModuleNotFoundError on first telemetry Glue run 2026-06-11; logged
    # in spec decisions.md.)
    for lib_file in ("product_generator.py", "schema_loader.py"):
        lib_local = root / "source" / "lib" / lib_file
        if not lib_local.exists():
            raise FileNotFoundError(f"Lib missing: {lib_local}")
        s3.upload_file(str(lib_local), bucket, f"scripts/lib/{lib_file}")
        log(f"  uploaded lib -> s3://{bucket}/scripts/lib/{lib_file}")

    # Dimensions: only upload if not already present (idempotency contract).
    vins_local = root / "dimensions" / "vins" / "data.parquet"
    vins_key = "dimensions/vins/data.parquet"
    try:
        s3.head_object(Bucket=bucket, Key=vins_key)
        log(f"  dimensions/vins/data.parquet already present (skip upload)")
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            if vins_local.exists():
                s3.upload_file(str(vins_local), bucket, vins_key)
                log(f"  uploaded vins -> s3://{bucket}/{vins_key}")
            else:
                err(
                    f"vins/data.parquet missing on bucket AND locally; "
                    f"run `make seed-dimensions STAGE=...` first"
                )
                raise
        else:
            raise


def _create_glue_job(
    boto3_session: boto3.Session,
    *,
    region: str,
    job_name: str,
    role_arn: str,
    bucket: str,
    product_src_dir: str,
    workers: int,
    worker_type: str,
    timeout_min: int,
) -> None:
    """Idempotent delete + create of a Glue 5.1 job.

    Per the spike-harness pattern (run-spark-spike.sh:91-114), we
    delete-then-create rather than try-update — keeps the lifecycle
    simple and surfaces drift via re-create.
    """
    glue = boto3_session.client("glue", region_name=region)
    log(f"  delete-then-create {job_name} (idempotent)")
    try:
        glue.delete_job(JobName=job_name)
        log(f"    deleted existing {job_name}; sleeping 15s for IAM consistency")
        time.sleep(15)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") != "EntityNotFoundException":
            raise
        log(f"    no existing job named {job_name} (clean slate)")

    script_location = f"s3://{bucket}/scripts/{product_src_dir}/generator.py"
    glue.create_job(
        Name=job_name,
        Role=role_arn,
        Command={
            "Name": "glueetl",
            "ScriptLocation": script_location,
            "PythonVersion": "3",
        },
        DefaultArguments={
            "--datalake-formats": "iceberg",
            "--enable-metrics": "true",
            "--enable-continuous-cloudwatch-log": "true",
            "--enable-spark-ui": "false",
            "--TempDir": f"s3://{bucket}/tmp/",
            "--extra-py-files": (
                f"s3://{bucket}/scripts/lib/product_generator.py,"
                f"s3://{bucket}/scripts/lib/schema_loader.py"
            ),
            # PyYAML is a transitive dep of schema_loader.py (NOT bundled in
            # Glue 5.1 stdlib). Install via --additional-python-modules so the
            # generator's `import yaml` line resolves at runtime. Discovered
            # via second telemetry Glue failure 2026-06-11; logged in
            # decisions.md.
            "--additional-python-modules": "pyyaml==6.0.2",
            # Glue 5.1 breaking change mitigation + Iceberg+Glue Catalog config
            # block (per spec Risks table contingency). Multi-conf format:
            # space-separated `--conf` prefixes — Glue parses each into a
            # separate Spark conf. Order: (1) S3A endpoint region — required,
            # else S3A defaults to us-east-2 and writes time out; (2-6) define
            # `glue_catalog` Spark catalog as Iceberg-backed by AWS Glue
            # Catalog — required because Glue 5.1's `--datalake-formats=iceberg`
            # magic does NOT auto-define the catalog name, only the classpath.
            # Without (2-6) `df.writeTo("glue_catalog.<db>.<table>")` raises
            # AnalysisException and the generator falls back to plain parquet
            # (table not registered → contract queries fail). Discovered via
            # third telemetry Glue run 2026-06-11; logged in decisions.md.
            "--conf": (
                f"spark.hadoop.fs.s3a.endpoint.region={region}"
                f" --conf spark.sql.catalog.glue_catalog=org.apache.iceberg.spark.SparkCatalog"
                f" --conf spark.sql.catalog.glue_catalog.warehouse=s3://{bucket}/curated/"
                f" --conf spark.sql.catalog.glue_catalog.catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog"
                f" --conf spark.sql.catalog.glue_catalog.io-impl=org.apache.iceberg.aws.s3.S3FileIO"
                f" --conf spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions"
                # Iceberg V2 bucketed writes are memory-hungry off-heap.
                # Bump container overhead to prevent YARN kill during shuffle
                # (root cause of MetadataFetchFailedException seen 2026-06-11).
                f" --conf spark.executor.memoryOverhead=6g"
                # More shuffle partitions = less data per task = less off-heap
                # pressure per executor.
                f" --conf spark.sql.shuffle.partitions=400"
            ),
        },
        ExecutionProperty={"MaxConcurrentRuns": 1},
        GlueVersion="5.1",
        NumberOfWorkers=workers,
        WorkerType=worker_type,
        Timeout=timeout_min,
    )
    log(f"  created {job_name}")


def _do_stage(boto3_session: boto3.Session, args: argparse.Namespace) -> int:
    """Stage scripts + create Glue jobs."""
    account = _resolve_account(boto3_session, args.account)
    region = args.region
    bucket = _lake_bucket(args.stage, account, region)
    role_arn = _role_arn(args.stage, account, region)

    if not _preflight_role(boto3_session, role_arn):
        err(
            f"Persistent role missing: {role_arn}. "
            f"Deploy adp-{args.stage}-foundation-data-products first."
        )
        return 2

    log(f"Stage: account={account} region={region} bucket={bucket}")
    log(f"Role: {role_arn}")

    products = list(_selected_products(args.product))
    log(f"Uploading scripts for {products} ...")
    _upload_scripts(boto3_session, bucket=bucket, region=region, products=products)

    for p in products:
        info = PRODUCT_INFO[p]
        job_name = _job_name(args.stage, p)
        _create_glue_job(
            boto3_session,
            region=region,
            job_name=job_name,
            role_arn=role_arn,
            bucket=bucket,
            product_src_dir=info["src_dir"],
            workers=args.workers,
            worker_type=args.worker_type,
            timeout_min=args.timeout_min,
        )
    log("Stage complete.")
    return 0


# ----------------------------------------------------------------------------
# Run: start_job_run + poll + validate.
# ----------------------------------------------------------------------------


def _run_one(
    boto3_session: boto3.Session,
    *,
    stage: str,
    region: str,
    bucket: str,
    product_key: str,
    rows: int,
    days: int,
    partitions: int,
    seed: int,
    wait: bool,
    poll_interval_sec: int,
) -> int:
    """Start one Glue run + (optionally) wait for terminal state."""
    glue = boto3_session.client("glue", region_name=region)
    info = PRODUCT_INFO[product_key]
    job_name = _job_name(stage, product_key)
    output_root = (
        f"s3://{bucket}/curated/{info['src_dir']}/{info['src_dir']}/"
    )
    table_name = (
        f"glue_catalog.adp_{stage}_{info['db']}.{info['db']}"
    )
    args_payload = {
        "--rows": str(rows),
        "--days": str(days),
        "--partitions": str(partitions),
        "--seed": str(seed),
        "--vins-source": f"s3://{bucket}/dimensions/vins/data.parquet",
        "--output-root": output_root,
        "--table-name": table_name,
    }
    log(f"Starting {job_name} ...")
    log(f"  args={args_payload}")
    response = glue.start_job_run(JobName=job_name, Arguments=args_payload)
    run_id = response["JobRunId"]
    log(f"  run id: {run_id}")

    if not wait:
        log("  --no-wait set; returning success without polling")
        return 0

    started = time.time()
    state = "STARTING"
    while True:
        try:
            jr = glue.get_job_run(JobName=job_name, RunId=run_id)["JobRun"]
        except ClientError as e:
            err(f"  get_job_run failed: {e}")
            return 1
        state = jr["JobRunState"]
        elapsed = int(time.time() - started)
        log(f"  [STATE elapsed={elapsed}s] state={state}")
        if state in ("SUCCEEDED", "FAILED", "TIMEOUT", "STOPPED"):
            break
        time.sleep(poll_interval_sec)

    elapsed = int(time.time() - started)
    if state == "SUCCEEDED":
        log(f"{job_name} SUCCEEDED in {elapsed}s")
        return 0

    # Failure path: pull error message + tail CloudWatch logs.
    err_msg = jr.get("ErrorMessage", "(no ErrorMessage)")
    err(f"{job_name} terminated state={state} after {elapsed}s")
    err(f"  ErrorMessage: {err_msg}")
    failure_log = f"/tmp/glue-failure-{product_key}-{run_id}.log"
    try:
        logs_client = boto3_session.client("logs", region_name=region)
        # Glue 4.0 routes both /aws-glue/jobs/output and /aws-glue/jobs/error.
        with open(failure_log, "w") as f:
            f.write(f"=== Glue Job Failure: {job_name} ===\n")
            f.write(f"  run id: {run_id}\n")
            f.write(f"  state: {state}\n")
            f.write(f"  elapsed: {elapsed}s\n")
            f.write(f"  ErrorMessage: {err_msg}\n\n")
            for log_group in ("/aws-glue/jobs/output", "/aws-glue/jobs/error"):
                f.write(f"\n=== {log_group} ===\n")
                try:
                    events = logs_client.get_log_events(
                        logGroupName=log_group,
                        logStreamName=run_id,
                        limit=200,
                        startFromHead=False,
                    )
                    for e in events.get("events", [])[-200:]:
                        f.write(e.get("message", "") + "\n")
                except ClientError as ce:
                    f.write(f"  (could not fetch: {ce})\n")
        err(f"  CloudWatch tail saved to {failure_log}")
    except Exception as exc:  # noqa: BLE001
        err(f"  failed to dump CloudWatch logs: {exc}")

    if state == "TIMEOUT":
        err(
            "  TIMEOUT — spike extrapolation has drifted; STOP per spec "
            "Constraint #6 before launching next product."
        )
    return 1


def _do_run(boto3_session: boto3.Session, args: argparse.Namespace) -> int:
    account = _resolve_account(boto3_session, args.account)
    region = args.region
    bucket = _lake_bucket(args.stage, account, region)
    products = list(_selected_products(args.product))
    log(f"Run: bucket={bucket} products={products}")
    rc = 0
    for p in products:
        result = _run_one(
            boto3_session,
            stage=args.stage,
            region=region,
            bucket=bucket,
            product_key=p,
            rows=args.rows,
            days=args.days,
            partitions=args.partitions,
            seed=args.seed,
            wait=args.wait,
            poll_interval_sec=args.poll_interval_sec,
        )
        if result != 0:
            rc = result
            # Per spec Constraint #6: stop on first failure rather than
            # spending compute on a downstream run that may also fail.
            break
    return rc


# ----------------------------------------------------------------------------
# Teardown: delete Glue jobs (KEEP role + scripts).
# ----------------------------------------------------------------------------


def _do_teardown(boto3_session: boto3.Session, args: argparse.Namespace) -> int:
    glue = boto3_session.client("glue", region_name=args.region)
    products = list(_selected_products(args.product))
    log(f"Teardown: deleting {len(products)} Glue job(s) ...")
    for p in products:
        job_name = _job_name(args.stage, p)
        try:
            glue.delete_job(JobName=job_name)
            log(f"  deleted {job_name}")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "EntityNotFoundException":
                log(f"  {job_name} already absent (idempotent)")
            else:
                err(f"  unexpected error deleting {job_name}: {e}")
                return 1
    log(
        "Teardown complete. Persistent IAM role + S3 scripts PRESERVED "
        "per OQ #3."
    )
    return 0


# ----------------------------------------------------------------------------
# Main.
# ----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    boto3_session = boto3.Session()

    if args.action == "stage":
        return _do_stage(boto3_session, args)
    if args.action == "run":
        return _do_run(boto3_session, args)
    if args.action == "stage-and-run":
        rc = _do_stage(boto3_session, args)
        if rc != 0:
            return rc
        return _do_run(boto3_session, args)
    if args.action == "teardown":
        return _do_teardown(boto3_session, args)
    err(f"Unknown action: {args.action}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
