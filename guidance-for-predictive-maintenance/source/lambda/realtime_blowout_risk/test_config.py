"""
Config tests for realtime_blowout_risk — RED phase.

Spec: .kiro/specs/2026-08-10-adp-tire-prediction-batch-only-deploy/spec.md § D2

These tests assert:
  1. CMS_TABLE_REGION is required — absence must raise an error naming the variable.
  2. CMS_STAGE is required — absence must raise an error naming the variable.
  3. No 'us-east-2' default survives in the module (source-level assertion).
  4. No 'prod' default survives in the module (source-level assertion).

The spec explicitly applies these requirements to realtime_blowout_risk even though
it is not deployed in the batch-only staging plan, so the two Lambdas cannot drift.

RED PHASE: tests 1-4 FAIL against the current main.py because:
  - main.py uses os.environ.get("AWS_REGION", "us-east-2") instead of requiring CMS_TABLE_REGION
  - main.py uses os.environ.get("DEPLOYMENT_STAGE", "prod") instead of requiring CMS_STAGE

Do NOT edit main.py in this task — the RED state is intentional.
"""

import ast
import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


LAMBDA_DIR = Path(__file__).parent
MAIN_PY = LAMBDA_DIR / "main.py"


def _load_module_with_env(env: dict) -> types.ModuleType:
    """Load realtime_blowout_risk/main.py as a fresh module with a specific env.

    Uses importlib.util.spec_from_file_location so there is no dependency on
    the directory having an __init__.py — the Lambda is a standalone script.
    boto3 is mocked so no AWS calls are made during import.
    """
    module_name = f"_realtime_blowout_risk_main_{id(env)}"

    mock_boto3 = MagicMock()
    mock_boto3.resource.return_value = MagicMock()
    mock_boto3.client.return_value = MagicMock()

    spec = importlib.util.spec_from_file_location(module_name, MAIN_PY)
    module = importlib.util.module_from_spec(spec)

    with patch.dict(os.environ, env, clear=True):
        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            spec.loader.exec_module(module)

    return module


class TestRealtimeBlowoutRiskForbiddenDefaults(unittest.TestCase):
    """Assert that forbidden hard-coded defaults do not exist in source.

    These are source-level assertions using the AST — they fail as long as
    the bad defaults are present, regardless of the runtime environment.
    """

    def _parse_module(self) -> ast.Module:
        return ast.parse(MAIN_PY.read_text(), filename=str(MAIN_PY))

    def _collect_environ_get_calls(self, tree: ast.Module) -> list[dict]:
        """Return all os.environ.get(name, default) call sites with their args."""
        results = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "environ"
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == "os"
            ):
                args = node.args
                try:
                    key = ast.literal_eval(args[0]) if args else None
                    default = ast.literal_eval(args[1]) if len(args) > 1 else None
                except (ValueError, TypeError):
                    key = None
                    default = None
                results.append(
                    {"key": key, "default": default, "lineno": node.lineno}
                )
        return results

    def test_no_us_east_2_default_in_source(self):
        """No os.environ.get call may use 'us-east-2' as its default value.

        RED: fails because main.py has os.environ.get("AWS_REGION", "us-east-2").
        GREEN: passes once the default is removed and CMS_TABLE_REGION is required.
        """
        tree = self._parse_module()
        calls = self._collect_environ_get_calls(tree)
        bad = [c for c in calls if c["default"] == "us-east-2"]
        self.assertEqual(
            [],
            bad,
            msg=(
                f"Found os.environ.get call(s) with default 'us-east-2' at "
                f"line(s) {[c['lineno'] for c in bad]}. "
                "The CMS table region must come from the required CMS_TABLE_REGION "
                "env var with no default. Nothing in this portfolio is "
                "us-east-2 — it is an orphan-endpoint region that caused a "
                "four-month silent failure."
            ),
        )

    def test_no_prod_default_in_source(self):
        """No os.environ.get call may use 'prod' as its default value.

        RED: fails because main.py has os.environ.get("DEPLOYMENT_STAGE", "prod").
        GREEN: passes once the default is removed and CMS_STAGE is required.
        """
        tree = self._parse_module()
        calls = self._collect_environ_get_calls(tree)
        bad = [c for c in calls if c["default"] == "prod"]
        self.assertEqual(
            [],
            bad,
            msg=(
                f"Found os.environ.get call(s) with default 'prod' at "
                f"line(s) {[c['lineno'] for c in bad]}. "
                "The CMS stage must come from the required CMS_STAGE env var "
                "with no default. A fail-safe default plus the wrong value "
                "produces a component that reports success while reading nothing."
            ),
        )


class TestRealtimeBlowoutRiskRequiredConfig(unittest.TestCase):
    """Assert that CMS_TABLE_REGION and CMS_STAGE are required env vars.

    RED: tests fail because the module uses AWS_REGION/DEPLOYMENT_STAGE with
    silent defaults and never inspects CMS_TABLE_REGION / CMS_STAGE.
    """

    def test_cms_table_region_required_raises_when_absent(self):
        """Loading the module without CMS_TABLE_REGION must raise an error
        whose message names the missing variable.

        RED: fails because the module silently defaults to 'us-east-2'.
        GREEN: passes once the module raises with 'CMS_TABLE_REGION' in the message.
        """
        with self.assertRaises(
            (KeyError, ValueError, EnvironmentError, RuntimeError),
            msg=(
                "Expected an exception when CMS_TABLE_REGION is absent, but "
                "none was raised. The module must fail closed — a missing "
                "CMS_TABLE_REGION should raise, not silently use 'us-east-2'."
            ),
        ) as ctx:
            _load_module_with_env({"CMS_STAGE": "staging"})

        error_text = str(ctx.exception)
        self.assertIn(
            "CMS_TABLE_REGION",
            error_text,
            msg=(
                f"Exception raised ({type(ctx.exception).__name__}: {error_text}) "
                "but the message does not name 'CMS_TABLE_REGION'. The error must "
                "name the missing variable so operators know exactly what to set."
            ),
        )

    def test_cms_stage_required_raises_when_absent(self):
        """Loading the module without CMS_STAGE must raise an error whose
        message names the missing variable.

        RED: fails because the module silently defaults to 'prod'.
        GREEN: passes once the module raises with 'CMS_STAGE' in the message.
        """
        with self.assertRaises(
            (KeyError, ValueError, EnvironmentError, RuntimeError),
            msg=(
                "Expected an exception when CMS_STAGE is absent, but none was "
                "raised. The module must fail closed — a missing CMS_STAGE "
                "should raise, not silently use 'prod'."
            ),
        ) as ctx:
            _load_module_with_env({"CMS_TABLE_REGION": "us-west-2"})

        error_text = str(ctx.exception)
        self.assertIn(
            "CMS_STAGE",
            error_text,
            msg=(
                f"Exception raised ({type(ctx.exception).__name__}: {error_text}) "
                "but the message does not name 'CMS_STAGE'. The error must "
                "name the missing variable so operators know exactly what to set."
            ),
        )

    def test_both_required_vars_present_does_not_raise(self):
        """When both CMS_TABLE_REGION and CMS_STAGE are set, module load succeeds.

        This is the positive control — verifies the fail-closed pattern does not
        block correctly-configured deployments. Must pass both before and after
        the fix (before: passes trivially; after: passes because the vars are set).
        """
        try:
            _load_module_with_env(
                {
                    "CMS_TABLE_REGION": "us-west-2",
                    "CMS_STAGE": "staging",
                }
            )
        except (KeyError, ValueError, EnvironmentError, RuntimeError) as exc:
            self.fail(
                f"Module raised {type(exc).__name__}: {exc} when both "
                "CMS_TABLE_REGION='us-west-2' and CMS_STAGE='staging' were set. "
                "Import must succeed when required vars are present."
            )


if __name__ == "__main__":
    unittest.main()
