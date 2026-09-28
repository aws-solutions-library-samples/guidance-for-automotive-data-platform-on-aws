"""Stage-aware resource naming helpers for ADP foundation stacks.

Per ``staging-prod-design.md`` §2, ``{stage}`` is woven into stack
and resource names so staging and prod can coexist in the same
account+region. Every per-stage stack composes its names through
the helpers below — direct ``f"adp-foundation-..."`` literals are
forbidden in the per-stage stacks.

Conventions
-----------
- Stack/resource names that today read ``adp-foundation-*`` become
  ``adp-{stage}-foundation-*`` (see :func:`_stage_name`).
- Glue databases that today read ``adp_<x>`` become
  ``adp_{stage}_<x>`` (see :func:`_stage_db_name`).
- IDC group display names that today read ``adp-<x>`` become
  ``adp-{stage}-<x>`` (see :func:`_stage_group_name`).
- CFN export names that today read ``adp-foundation-<x>`` become
  ``adp-{stage}-foundation-<x>`` (use :func:`_stage_name` directly).

``stage`` MUST be one of ``{"staging", "prod"}``. ``app.py`` is the
sanctioned entry point that validates ``stage`` before constructing
per-stage stacks; helpers re-validate defensively so a misconfigured
construct call surfaces the error early.
"""

from __future__ import annotations


VALID_STAGES = ("staging", "prod")


def validate_stage(stage: str) -> None:
    """Raise ``ValueError`` if ``stage`` is not in :data:`VALID_STAGES`."""
    if stage not in VALID_STAGES:
        raise ValueError(
            f"stage must be one of {VALID_STAGES}; got {stage!r}"
        )


def _stage_name(stage: str, suffix: str) -> str:
    """Compose ``adp-{stage}-foundation-{suffix}``.

    Used for stack names, S3 bucket names, KMS aliases (after the
    ``alias/`` prefix), the DataZone domain name, IAM role names,
    the CloudTrail trail name, the optional CMS-ingest Firehose
    stream name, and CFN ``Export.Name`` values per design
    §2.1–§2.4 and §2.8–§2.11.

    Examples
    --------
    >>> _stage_name("staging", "network")
    'adp-staging-foundation-network'
    >>> _stage_name("prod", "lake-bucket-name")
    'adp-prod-foundation-lake-bucket-name'
    >>> _stage_name("staging", "datazone-execution-role")
    'adp-staging-foundation-datazone-execution-role'
    """
    validate_stage(stage)
    return f"adp-{stage}-foundation-{suffix}"


def _stage_db_name(stage: str, product: str) -> str:
    """Compose ``adp_{stage}_{product}`` Glue database name (design §2.7).

    Examples
    --------
    >>> _stage_db_name("staging", "vehicle_telemetry_aggregated")
    'adp_staging_vehicle_telemetry_aggregated'
    >>> _stage_db_name("prod", "dimensions")
    'adp_prod_dimensions'
    """
    validate_stage(stage)
    return f"adp_{stage}_{product}"


def _stage_group_name(stage: str, group_suffix: str) -> str:
    """Compose ``adp-{stage}-{group_suffix}`` IDC group display name (design §2.6).

    Examples
    --------
    >>> _stage_group_name("staging", "data-owners")
    'adp-staging-data-owners'
    >>> _stage_group_name("prod", "platform-admins")
    'adp-prod-platform-admins'
    """
    validate_stage(stage)
    return f"adp-{stage}-{group_suffix}"
