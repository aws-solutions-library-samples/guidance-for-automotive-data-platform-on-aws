# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
pytest conftest for daily_tire_check/tests/ — provenance tests.

Sets the required environment variables (CMS_TABLE_REGION and CMS_STAGE) so
that importing daily_tire_check/main.py succeeds during the provenance test
suite.  These variables were introduced by § D2 (region/stage decoupling) and
are REQUIRED at module load — no default is provided, so the module fails
closed without them.

The provenance tests (test_provenance.py) focus on § D3 (provenance fields)
and assume the module can be imported; they rely on this conftest to satisfy
§ D2's import requirement.  The config tests (test_config.py, one directory
up) exercise the fail-closed behaviour directly with controlled env patches,
so they do not use this conftest.
"""

import os


def pytest_configure(config):
    """Set required env vars before any test module is imported."""
    # These are the staging values; the exact values don't matter for unit tests
    # because boto3 calls are mocked — what matters is that the vars are set and
    # non-empty so _require_env() does not raise during module import.
    os.environ.setdefault("CMS_TABLE_REGION", "us-west-2")
    os.environ.setdefault("CMS_STAGE", "staging")
