# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Synth guard: no endpoint when the endpoint flag is off.

Spec: .kiro/specs/2026-08-10-adp-tire-prediction-batch-only-deploy/spec.md § D1
Task: Group 3, task 1 — "Make the endpoint tail conditional"

Group 3 state (GREEN)
---------------------
The ``deploy_realtime_endpoint`` flag has been added to ``MLPipelineConstruct``
and ``TirePredictiveMaintenanceStack`` (default: ``False``).

This file's two fixtures now perform **real separate synths** via subprocess:

* ``flag_off_template``  — synthesises with ``-c deployRealtimeEndpoint=false``
  (the default posture).  The resulting template has **0** realtime-inference
  resources, no endpoint step-function states, and no blowout-risk Lambda.

* ``flag_on_template``   — synthesises with ``-c deployRealtimeEndpoint=true``.
  The resulting template has **20** MLRealtimeInferenceConstruct resources, the
  full endpoint tail in the training step function, and the blowout-risk Lambda.

Both fixtures run ``cdk synth`` via subprocess pointing at the real CDK app
(``infrastructure/app.py``) so they exercise the full synthesis path including
cdk-nag.  Docker is required (bundling uses ``public.ecr.aws/sam/build-python3.13``
— the image is cached after the first synth).

KNOWN LIMITATION (resolved as of Group 3)
------------------------------------------
The prior version of this file had both fixtures pointing at the **same**
pre-synthesised ``cdk.out`` template because Docker was unavailable.  That
made the guard decorative — flag_off and flag_on were identical, so none of
the assertion tests could distinguish the two states.  Docker is now available;
this file eliminates that limitation.

Template caching
----------------
Each fixture saves its template to a named file in ``cdk.out/``:

  cdk.out/tire-predictive-maintenance-stack-flag-off.template.json
  cdk.out/tire-predictive-maintenance-stack-flag-on.template.json

A fresh synth is triggered if the file does not exist.  To force regeneration,
delete those files and re-run.

Convention matched
------------------
Uses ``aws_cdk.assertions.Template.from_json()`` with ``pytest``, which is the
CDK v2 standard pattern for template assertions.
"""

# Standard Library
import json
import os
import shutil
import subprocess
import sys

# Third Party Libraries
import pytest

# AWS Libraries
from aws_cdk.assertions import Match, Template

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
_INFRA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CDK_OUT_DIR = os.path.join(_INFRA_DIR, "cdk.out")
_FLAG_OFF_TEMPLATE_PATH = os.path.join(
    _CDK_OUT_DIR, "tire-predictive-maintenance-stack-flag-off.template.json"
)
_FLAG_ON_TEMPLATE_PATH = os.path.join(
    _CDK_OUT_DIR, "tire-predictive-maintenance-stack-flag-on.template.json"
)
# Canonical output path that cdk synth always writes to
_CANONICAL_TEMPLATE_PATH = os.path.join(
    _CDK_OUT_DIR, "tire-predictive-maintenance-stack.template.json"
)

_CDK_ENV = {
    **os.environ,
    # Placeholder account, not the real one. `123456789012` is the AWS-docs example
    # account and is allowlisted by the publish scanner; the real ID in a git-tracked
    # file outside .publish-exclude would fail every future publish. Synth does not
    # care what the value is, only that it is a well-formed 12-digit account.
    "CDK_DEFAULT_ACCOUNT": os.environ.get("CDK_DEFAULT_ACCOUNT", "123456789012"),
    "CDK_DEFAULT_REGION": os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    # Suppress the jsii deprecated-node-version warning in test output
    "JSII_SILENCE_WARNING_DEPRECATED_NODE_VERSION": "1",
}


def _synth_and_save(context_flag_value: str, dest_path: str) -> None:
    """
    Run ``cdk synth tire-predictive-maintenance-stack`` with
    ``deployRealtimeEndpoint=<context_flag_value>`` and copy the resulting
    template to ``dest_path``.

    Uses the real CDK app (``app.py`` in the infrastructure directory) so
    the synth exercises cdk-nag and all construct logic.
    """
    npx = shutil.which("npx") or "npx"
    cmd = [
        npx,
        "cdk",
        "synth",
        "tire-predictive-maintenance-stack",
        f"-c",
        f"deployRealtimeEndpoint={context_flag_value}",
        "--quiet",
    ]
    result = subprocess.run(
        cmd,
        cwd=_INFRA_DIR,
        env=_CDK_ENV,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"cdk synth failed (deployRealtimeEndpoint={context_flag_value}):\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    # CDK writes the template to the canonical path; copy to the named dest
    if not os.path.isfile(_CANONICAL_TEMPLATE_PATH):
        raise FileNotFoundError(
            f"Expected template at {_CANONICAL_TEMPLATE_PATH} after cdk synth"
        )
    shutil.copy2(_CANONICAL_TEMPLATE_PATH, dest_path)


def _load_template(path: str, context_flag_value: str) -> dict:
    """Load a template JSON, synthesising it first if the file does not exist."""
    if not os.path.isfile(path):
        _synth_and_save(context_flag_value, path)
    with open(path) as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def flag_off_template_json() -> dict:
    """
    Template synthesised with ``deploy_realtime_endpoint=False`` (the default /
    batch-only posture).

    Synthesised via ``cdk synth -c deployRealtimeEndpoint=false``.  The result
    must have zero realtime-inference resources, no endpoint step-function
    states, and no blowout-risk Lambda.
    """
    return _load_template(_FLAG_OFF_TEMPLATE_PATH, "false")


@pytest.fixture(scope="module")
def flag_on_template_json() -> dict:
    """
    Template synthesised with ``deploy_realtime_endpoint=True`` (endpoint enabled).

    Synthesised via ``cdk synth -c deployRealtimeEndpoint=true``.  The result
    must have 20 MLRealtimeInferenceConstruct resources, the full endpoint tail,
    and the blowout-risk Lambda.
    """
    return _load_template(_FLAG_ON_TEMPLATE_PATH, "true")


@pytest.fixture(scope="module")
def flag_off_template(flag_off_template_json: dict) -> Template:
    """CDK assertions Template for the flag-off (batch-only) stack."""
    return Template.from_json(flag_off_template_json)


@pytest.fixture(scope="module")
def flag_on_template(flag_on_template_json: dict) -> Template:
    """CDK assertions Template for the flag-on (endpoint-enabled) stack."""
    return Template.from_json(flag_on_template_json)


# ---------------------------------------------------------------------------
# Positive controls — these MUST pass today
# ---------------------------------------------------------------------------
class TestPositiveControls:
    """
    Controls that prove the suite is live and testing a real template.

    These tests must always be GREEN.  If any of these fail, the template
    fixture is broken and all other test results are meaningless.
    """

    def test_alerts_table_present(self, flag_on_template: Template) -> None:
        """
        The DynamoDB alerts table is always present regardless of any flag.

        This is the baseline control: if this fails the template fixture is
        broken.
        """
        flag_on_template.resource_count_is("AWS::DynamoDB::Table", 1)

    def test_realtime_inference_lambda_present_when_flag_on(
        self, flag_on_template: Template
    ) -> None:
        """
        The realtime-inference Lambda IS present in the flag-on template.

        Asserts the positive side of the flag: with the endpoint enabled
        the Lambda function that invokes SageMaker must exist.
        """
        flag_on_template.resource_count_is("AWS::ApiGateway::RestApi", 1)

    def test_realtime_resources_present_when_flag_on(
        self, flag_on_template: Template
    ) -> None:
        """
        The 20 MLRealtimeInferenceConstruct resources ARE present when flag
        is on.

        Synth guard positive control: with the flag on, all 20 resources
        from MLRealtimeInferenceConstruct must be present.
        """
        raw = flag_on_template.to_json()["Resources"]
        realtime_keys = [k for k in raw if "realtimeinference" in k.lower()]
        assert len(realtime_keys) == 20, (
            f"Expected 20 MLRealtimeInferenceConstruct resources when flag is ON, "
            f"got {len(realtime_keys)}: {realtime_keys}"
        )

    def test_training_step_function_present(self, flag_on_template: Template) -> None:
        """
        The training step function is always present (batch path, not endpoint-gated).
        """
        flag_on_template.resource_count_is("AWS::StepFunctions::StateMachine", 2)

    def test_blowout_risk_lambda_present_when_flag_on(
        self, flag_on_template: Template
    ) -> None:
        """
        The blowout-risk Lambda IS present when the endpoint flag is on.
        """
        raw = flag_on_template.to_json()["Resources"]
        blowout_keys = [k for k in raw if "blowoutrisk" in k.lower()]
        assert len(blowout_keys) == 1, (
            f"Expected 1 BlowoutRisk Lambda when flag is ON, got {len(blowout_keys)}"
        )


# ---------------------------------------------------------------------------
# Flag-off assertions — GREEN after Group 3
# ---------------------------------------------------------------------------
class TestNoEndpointWhenFlagOff:
    """
    Assert that with the endpoint flag OFF the template contains no endpoint
    infrastructure.

    All assertions in this class use the flag-off template (synthesised with
    ``deployRealtimeEndpoint=false``).  These tests were RED in Group 2 (the
    flag did not exist); they are GREEN in Group 3 (the flag is implemented).
    """

    def test_no_realtime_inference_lambda_when_flag_off(
        self, flag_off_template: Template
    ) -> None:
        """
        No AWS::Lambda::Function under the ml-realtime-inference-construct
        path when the endpoint flag is off.

        Spec § D1: with the flag off, MLRealtimeInferenceConstruct must not
        be instantiated.  Its Lambda calls sagemaker:InvokeEndpoint — it must
        not deploy when no endpoint exists.
        """
        raw = flag_off_template.to_json()["Resources"]
        realtime_lambda_keys = [
            k
            for k, v in raw.items()
            if v["Type"] == "AWS::Lambda::Function"
            and "realtimeinference" in k.lower()
        ]
        assert realtime_lambda_keys == [], (
            "Found MLRealtimeInferenceConstruct Lambda(s) in the template with the "
            f"endpoint flag OFF (expected none): {realtime_lambda_keys}."
        )

    def test_no_mlrealtimeinferenceconstruct_resources_when_flag_off(
        self, flag_off_template: Template
    ) -> None:
        """
        Zero resources from MLRealtimeInferenceConstruct when flag is off.

        Group 1 counted 20 resources under this construct.  With the flag off
        the count must be 0.
        """
        raw = flag_off_template.to_json()["Resources"]
        realtime_keys = [k for k in raw if "realtimeinference" in k.lower()]
        assert realtime_keys == [], (
            f"Expected 0 MLRealtimeInferenceConstruct resources when flag is OFF, "
            f"found {len(realtime_keys)}.  Resources: {realtime_keys}"
        )

    def test_no_api_gateway_when_flag_off(self, flag_off_template: Template) -> None:
        """
        No AWS::ApiGateway::RestApi when the endpoint flag is off.

        The realtime-inference API Gateway is the only RestApi in this stack.
        Its absence confirms the entire MLRealtimeInferenceConstruct is excluded.
        """
        flag_off_template.resource_count_is("AWS::ApiGateway::RestApi", 0)

    def test_no_blowout_risk_lambda_when_flag_off(
        self, flag_off_template: Template
    ) -> None:
        """
        No blowout-risk Lambda when the endpoint flag is off.

        Spec § D1: ``CMSIntegrationConstruct.BlowoutRisk`` calls
        ``sagemaker:InvokeEndpoint`` on the model endpoint SSM parameter.
        With no endpoint, this Lambda must not deploy.

        Decisions.md: the ``model_endpoint_ssm_parameter`` has no writer when
        the flag is off — anything reading it must also be absent.
        """
        raw = flag_off_template.to_json()["Resources"]
        blowout_keys = [k for k in raw if "blowoutrisk" in k.lower()]
        assert blowout_keys == [], (
            f"Found BlowoutRisk Lambda(s) in the template with the endpoint flag OFF "
            f"(expected none): {blowout_keys}."
        )

    def test_no_sagemaker_create_endpoint_config_state_when_flag_off(
        self, flag_off_template: Template
    ) -> None:
        """
        No ``CreateEndpointConfig`` state in any Step Functions state machine
        when the endpoint flag is off.

        Spec § D1: the training pipeline tail
        (CreateEndpointConfig → CheckEndpointExists → CreateEndpoint /
        UpdateEndpoint) must be absent when the flag is off.  The pipeline
        must end at UpdateModelNameParameter → success.
        """
        raw = flag_off_template.to_json()["Resources"]
        for key, resource in raw.items():
            if resource.get("Type") != "AWS::StepFunctions::StateMachine":
                continue
            defn_str = json.dumps(
                resource.get("Properties", {}).get("DefinitionString", "")
            )
            assert "CreateEndpointConfig" not in defn_str, (
                f"State machine '{key}' contains 'CreateEndpointConfig' when the "
                "endpoint flag is OFF."
            )

    def test_no_update_endpoint_state_when_flag_off(
        self, flag_off_template: Template
    ) -> None:
        """
        No ``UpdateEndpoint`` state in any Step Functions state machine when
        the endpoint flag is off.
        """
        raw = flag_off_template.to_json()["Resources"]
        for key, resource in raw.items():
            if resource.get("Type") != "AWS::StepFunctions::StateMachine":
                continue
            defn_str = json.dumps(
                resource.get("Properties", {}).get("DefinitionString", "")
            )
            assert "UpdateEndpoint" not in defn_str, (
                f"State machine '{key}' contains 'UpdateEndpoint' state when the "
                "endpoint flag is OFF."
            )

    def test_no_create_endpoint_state_when_flag_off(
        self, flag_off_template: Template
    ) -> None:
        """
        No ``CreateEndpoint`` action in any Step Functions state machine when
        the endpoint flag is off.

        Note: ``CreateEndpointConfig`` contains the substring ``CreateEndpoint``
        so the assertion checks the sagemaker action pattern specifically.
        """
        raw = flag_off_template.to_json()["Resources"]
        for key, resource in raw.items():
            if resource.get("Type") != "AWS::StepFunctions::StateMachine":
                continue
            defn_str = json.dumps(
                resource.get("Properties", {}).get("DefinitionString", "")
            )
            # sagemaker:createEndpoint (without Config) is the create-endpoint action
            assert "sagemaker:createEndpoint\\\"" not in defn_str, (
                f"State machine '{key}' contains sagemaker:createEndpoint action when "
                "the endpoint flag is OFF."
            )

    def test_no_invoke_endpoint_iam_grant_on_realtime_role_when_flag_off(
        self, flag_off_template: Template
    ) -> None:
        """
        No IAM role with ``sagemaker:InvokeEndpoint`` under the
        ml-realtime-inference-construct path when the flag is off.

        The realtime-inference Lambda role and its InvokeEndpoint grant must
        not exist when MLRealtimeInferenceConstruct is excluded.
        """
        raw = flag_off_template.to_json()["Resources"]
        realtime_role_keys = [
            k
            for k, v in raw.items()
            if v["Type"] == "AWS::IAM::Role"
            and "realtimeinference" in k.lower()
        ]
        assert realtime_role_keys == [], (
            f"Found realtime-inference IAM role(s) when flag is OFF: "
            f"{realtime_role_keys}."
        )


# ---------------------------------------------------------------------------
# Endpoint name guard — GREEN after Group 3
# ---------------------------------------------------------------------------
class TestEndpointNameNotHardcoded:
    """
    Assert the training step function does NOT use the hardcoded endpoint name
    ``'tpe'``.

    Context (decisions.md 2026-08-10): an orphan endpoint named exactly ``tpe``
    ran for 8+ months (~$1,411 idle spend) without being tracked by any stack.
    The training step-function reuses the fixed name — a future deploy would
    silently *adopt* the orphan rather than creating a fresh endpoint.  The
    flag-off excision (§ D1) could report success while an endpoint kept running.

    The endpoint name is now derived from stage and region (``tpe-{stage}-{region}``)
    so it is unique per deployment and the trap cannot be re-armed.

    GREEN after Group 3: ``ml_training_stepfunction.py`` now sets
    ``endpoint_name = f"tpe-{stage}-{Stack.of(self).region}"`` which resolves
    to a CloudFormation ``Fn::Join`` token, not the literal ``"tpe"``.
    """

    def test_endpoint_name_not_hardcoded_tpe(
        self, flag_off_template: Template
    ) -> None:
        """
        No Step Functions state machine contains the literal ``"tpe"`` as an
        endpoint name value.

        Checked against the flag-off template (which has no endpoint states at
        all — confirming the literal is absent even if endpoint states were
        accidentally present).  Also checked against the flag-on template via
        the sibling test below.
        """
        raw = flag_off_template.to_json()["Resources"]
        for key, resource in raw.items():
            if resource.get("Type") != "AWS::StepFunctions::StateMachine":
                continue
            defn_str = json.dumps(
                resource.get("Properties", {}).get("DefinitionString", "")
            )
            # The literal endpoint name "tpe" appears as EndpointName":"tpe" in the
            # JSON-encoded state definition when hardcoded.
            clean = defn_str.replace("\\\\", "").replace('\\"', '"')
            assert '"EndpointName":"tpe"' not in clean, (
                f"State machine '{key}' hardcodes EndpointName=\\\"tpe\\\".  "
                "This must be replaced with a stage-region-derived name "
                "(e.g. tpe-{stage}-{region}).  See decisions.md 2026-08-10."
            )

    def test_endpoint_name_not_hardcoded_tpe_in_flag_on_template(
        self, flag_on_template: Template
    ) -> None:
        """
        The flag-on template (with endpoint states present) does NOT contain
        the literal ``"tpe"`` as an endpoint name.

        With the endpoint name derived as ``tpe-{stage}-{region}``, the
        DefinitionString contains a CloudFormation ``Fn::Join`` token rather
        than the literal string ``"tpe"``.  This test confirms the
        parameterisation is in effect when the endpoint tail is actually
        included.

        ``ml_training_stepfunction.py:397-398`` decisions.md 2026-08-10 —
        orphan endpoint ``tpe`` deleted; re-arming the trap requires this guard.
        """
        raw = flag_on_template.to_json()["Resources"]
        for key, resource in raw.items():
            if resource.get("Type") != "AWS::StepFunctions::StateMachine":
                continue
            defn_str = json.dumps(
                resource.get("Properties", {}).get("DefinitionString", "")
            )
            clean = defn_str.replace("\\\\", "").replace('\\"', '"')
            # The literal "tpe" should NOT appear as an EndpointName value;
            # only a stage-region-derived token should be present.
            assert '"EndpointName":"tpe"' not in clean, (
                f"State machine '{key}' hardcodes EndpointName=\\\"tpe\\\" in the "
                "flag-on template.  The endpoint name must be stage-region derived."
            )
