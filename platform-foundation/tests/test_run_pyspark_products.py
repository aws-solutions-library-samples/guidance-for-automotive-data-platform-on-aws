"""Hermetic unit tests for run-pyspark-products.py orchestration script.

Spec: `.kiro/specs/2026-06-09-adp-pyspark-glue-products/tasks.md` Group 3 T3.2

10 test cases covering:
1. Argparse + CLI validation
2. Account resolution (override vs. STS call)
3. Resource name composition (bucket, role ARN, job name)
4. Product selection (both / single)
5. IAM role preflight check (exists / not found)
6. S3 script upload with idempotency
7. Glue job creation (idempotent delete-then-create)
8. Job run without polling
9. Job run with polling to success
10. Teardown job deletion
"""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

# Import the script under test as a module
script_path = Path(__file__).parent.parent / "scripts" / "run-pyspark-products.py"
spec = importlib.util.spec_from_file_location("run_pyspark_products", script_path)
rpp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rpp)


# =============================================================================
# Test 1: Argparse + CLI validation
# =============================================================================
def test_argparse_parses_all_required_args():
    """Verify _build_parser() constructs CLI with all required options."""
    parser = rpp._build_parser()
    assert parser.prog == "run-pyspark-products.py"
    
    # Parse a valid command
    args = parser.parse_args([
        "--stage", "staging",
        "--product", "telemetry",
        "--action", "stage",
    ])
    assert args.stage == "staging"
    assert args.product == "telemetry"
    assert args.action == "stage"
    assert args.workers == rpp.DEFAULT_WORKERS
    assert args.timeout_min == rpp.DEFAULT_TIMEOUT_MIN


# =============================================================================
# Test 2: Account resolution (override vs. live STS call)
# =============================================================================
def test_resolve_account_with_override():
    """_resolve_account returns override when provided."""
    session = MagicMock()
    account = rpp._resolve_account(session, override="123456789012")
    assert account == "123456789012"
    # Verify no STS call was made
    session.client.assert_not_called()


def test_resolve_account_calls_sts_without_override():
    """_resolve_account calls STS when override is None."""
    session = MagicMock()
    sts_mock = MagicMock()
    sts_mock.get_caller_identity.return_value = {"Account": "123456789012"}
    session.client.return_value = sts_mock
    
    account = rpp._resolve_account(session, override=None)
    
    assert account == "123456789012"
    session.client.assert_called_once_with("sts")
    sts_mock.get_caller_identity.assert_called_once()


# =============================================================================
# Test 3: Resource name composition (bucket, role ARN, job name)
# =============================================================================
def test_resource_composition_names():
    """Verify resource naming functions compose correct identifiers."""
    stage = "staging"
    account = "123456789012"
    region = "us-east-1"
    
    # Lake bucket
    bucket = rpp._lake_bucket(stage, account, region)
    assert bucket == "adp-staging-foundation-lake-123456789012-us-east-1"
    
    # Role ARN (region-suffixed per spec Constraint)
    arn = rpp._role_arn(stage, account, region)
    assert arn == "arn:aws:iam::123456789012:role/adp-staging-foundation-spark-etl-role-us-east-1"
    
    # Glue job names (kebab-case)
    assert rpp._job_name(stage, "telemetry") == "adp-staging-vehicle-telemetry-aggregated-job"
    assert rpp._job_name(stage, "energy") == "adp-staging-energy-usage-job"


# =============================================================================
# Test 4: Product selection logic (both / single)
# =============================================================================
def test_selected_products_both_and_single():
    """_selected_products returns correct product(s) per arg."""
    # "both" returns both
    products = list(rpp._selected_products("both"))
    assert products == ["telemetry", "energy"]
    
    # Single product returns only that one
    assert list(rpp._selected_products("telemetry")) == ["telemetry"]
    assert list(rpp._selected_products("energy")) == ["energy"]


# =============================================================================
# Test 5: IAM role preflight check (exists / not found)
# =============================================================================
def test_preflight_role_checks_existence():
    """_preflight_role returns True/False based on IAM role existence."""
    session = MagicMock()
    iam_mock = MagicMock()
    session.client.return_value = iam_mock
    
    # Role exists
    iam_mock.get_role.return_value = {"Role": {"RoleName": "test-role"}}
    assert rpp._preflight_role(session, "arn:aws:iam::123456789012:role/test-role") is True
    
    # Role not found (NoSuchEntity)
    error_response = {"Error": {"Code": "NoSuchEntity"}}
    iam_mock.get_role.side_effect = ClientError(error_response, "GetRole")
    assert rpp._preflight_role(session, "arn:aws:iam::123456789012:role/missing") is False


# =============================================================================
# Test 6: S3 script upload with idempotency
# =============================================================================
@patch.object(rpp, "_project_root")
def test_upload_scripts_calls_s3_upload(mock_root):
    """_upload_scripts uploads generators and lib to S3."""
    root_mock = MagicMock(spec=Path)
    mock_root.return_value = root_mock
    
    # Mock file paths
    gen_tel_path = MagicMock(spec=Path, exists=MagicMock(return_value=True), name="generator.py")
    gen_energy_path = MagicMock(spec=Path, exists=MagicMock(return_value=True), name="generator.py")
    lib_path = MagicMock(spec=Path, exists=MagicMock(return_value=True))
    vins_path = MagicMock(spec=Path, exists=MagicMock(return_value=True))
    
    def path_div_side_effect(*parts):
        paths = {
            ("source", "data-products", "vehicle_telemetry_aggregated", "generator.py"): gen_tel_path,
            ("source", "data-products", "energy_usage", "generator.py"): gen_energy_path,
            ("source", "lib", "product_generator.py"): lib_path,
            ("dimensions", "vins", "data.parquet"): vins_path,
        }
        key = tuple(parts) if isinstance(parts[0], str) else parts
        return paths.get(key, MagicMock(spec=Path, exists=MagicMock(return_value=False)))
    
    root_mock.__truediv__.side_effect = path_div_side_effect
    
    session = MagicMock()
    s3_mock = MagicMock()
    session.client.return_value = s3_mock
    # Simulate vins already on S3
    s3_mock.head_object.return_value = {}
    
    rpp._upload_scripts(
        session,
        bucket="adp-staging-foundation-lake-123456789012-us-east-1",
        region="us-east-1",
        products=["telemetry", "energy"],
    )
    
    # Verify upload_file was called for generators and lib
    assert s3_mock.upload_file.called


# =============================================================================
# Test 7: Glue job creation (idempotent delete-then-create)
# =============================================================================
@patch("time.sleep")  # Skip actual sleep for speed
def test_create_glue_job_deletes_then_creates(mock_sleep):
    """_create_glue_job performs idempotent delete-then-create lifecycle."""
    session = MagicMock()
    glue_mock = MagicMock()
    session.client.return_value = glue_mock
    
    rpp._create_glue_job(
        session,
        region="us-east-1",
        job_name="adp-staging-vehicle-telemetry-aggregated-job",
        role_arn="arn:aws:iam::123456789012:role/adp-staging-foundation-spark-etl-role-us-east-1",
        bucket="adp-staging-foundation-lake-123456789012-us-east-1",
        product_src_dir="vehicle_telemetry_aggregated",
        workers=2,
        worker_type="G.1X",
        timeout_min=30,
    )
    
    # Verify delete was called first
    glue_mock.delete_job.assert_called_once_with(JobName="adp-staging-vehicle-telemetry-aggregated-job")
    
    # Verify create was called with correct parameters
    glue_mock.create_job.assert_called_once()
    call_kwargs = glue_mock.create_job.call_args[1]
    assert call_kwargs["GlueVersion"] == "5.1"
    assert call_kwargs["NumberOfWorkers"] == 2
    assert call_kwargs["WorkerType"] == "G.1X"
    assert call_kwargs["Timeout"] == 30
    assert call_kwargs["DefaultArguments"]["--datalake-formats"] == "iceberg"
    # Glue 5.1 breaking change mitigation: S3A endpoint region must be pinned
    # (default is us-east-2 if unset; would cause cross-region timeouts on
    # our us-east-1 lake bucket). See spec Risks table + decisions.md
    # 2026-06-10 entry for context.
    assert "spark.hadoop.fs.s3a.endpoint.region=" in call_kwargs["DefaultArguments"]["--conf"]


# =============================================================================
# Test 8: Job run without polling (--no-wait)
# =============================================================================
def test_run_one_returns_immediately_without_wait():
    """_run_one returns 0 immediately when wait=False."""
    session = MagicMock()
    glue_mock = MagicMock()
    glue_mock.start_job_run.return_value = {"JobRunId": "run-123"}
    session.client.return_value = glue_mock
    
    result = rpp._run_one(
        session,
        stage="staging",
        region="us-east-1",
        bucket="adp-staging-foundation-lake-123456789012-us-east-1",
        product_key="telemetry",
        rows=10_000_000,
        days=90,
        partitions=64,
        seed=42,
        wait=False,
        poll_interval_sec=30,
    )
    
    assert result == 0
    glue_mock.start_job_run.assert_called_once()
    # Verify we did NOT poll
    glue_mock.get_job_run.assert_not_called()


# =============================================================================
# Test 9: Job run with polling to terminal state (SUCCEEDED)
# =============================================================================
@patch("time.sleep")
def test_run_one_polls_until_terminal_state(mock_sleep):
    """_run_one polls until terminal state (SUCCEEDED returns 0)."""
    session = MagicMock()
    glue_mock = MagicMock()
    glue_mock.start_job_run.return_value = {"JobRunId": "run-123"}
    glue_mock.get_job_run.return_value = {
        "JobRun": {
            "JobRunState": "SUCCEEDED",
            "ErrorMessage": "",
        }
    }
    session.client.return_value = glue_mock
    
    result = rpp._run_one(
        session,
        stage="staging",
        region="us-east-1",
        bucket="adp-staging-foundation-lake-123456789012-us-east-1",
        product_key="telemetry",
        rows=10_000_000,
        days=90,
        partitions=64,
        seed=42,
        wait=True,
        poll_interval_sec=1,
    )
    
    assert result == 0
    glue_mock.get_job_run.assert_called()


# =============================================================================
# Test 10: Teardown job deletion
# =============================================================================
def test_teardown_deletes_selected_jobs():
    """_do_teardown deletes selected Glue jobs and returns 0."""
    session = MagicMock()
    glue_mock = MagicMock()
    session.client.return_value = glue_mock
    
    args = MagicMock()
    args.stage = "staging"
    args.product = "both"
    args.region = "us-east-1"
    
    result = rpp._do_teardown(session, args)
    
    assert result == 0
    # Verify delete was called for both jobs
    assert glue_mock.delete_job.call_count == 2
    calls = glue_mock.delete_job.call_args_list
    job_names = {call[1]["JobName"] for call in calls}
    assert "adp-staging-vehicle-telemetry-aggregated-job" in job_names
    assert "adp-staging-energy-usage-job" in job_names
