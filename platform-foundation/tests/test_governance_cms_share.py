"""T3.1 — CMS-side Lake Formation share on the governance stack.

Spec: `~/connected-mobility-guidance-on-aws/.kiro/specs/2026-09-10-cms-fleet-intelligence-adp-consumer/`
(§ D3 — "Extend ADP's cross-account LF grant machinery for CMS"), Group 3.

Red-phase when authored: `_CMS_SHARE_DATABASES` and
`_grant_cms_cross_account_share` do not exist yet, and `GovernanceStack`
does not accept `cms_account_id`, so every test below fails on TypeError
until T3.2 lands.

Why this file exists separately from ``test_lf_cross_account.py``
----------------------------------------------------------------
The task text (amendment 2026-09-12) asserted there is no test covering the
CVX/DMS shares and asked for a follow-on to be filed. **That is false** —
``test_lf_cross_account.py`` covers CVX (permissions, absence-gate,
principal identity) and DMS (``TestDmsCrossAccount``, six cases). The
amendment's author grepped for the *filename* ``test_governance_cvx_share*``,
which never existed, rather than for the *symbol*. This file therefore adds
the CMS share only; it does not backfill anything, and no follow-on is owed.
Recorded in the spec's ``decisions.md``.

Assertion discipline
--------------------
Per the mutation bar this spec inherits from
``2026-09-01-dms-customer-master-adp``: every assertion below is exact-set or
exact-value, never ``contains``. A mutation that adds a 6th database, widens
``permissions`` to include ``ALL``, drops ``table_wildcard``, grants the
grant-option, or swaps the principal for CVX's/DMS's MUST turn one of these
red. The paired mutation run is recorded in the spec's ``decisions.md``.
"""

from __future__ import annotations

import os
import sys

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

# Ensure stacks package is importable from test runner.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stacks.governance_stack import GovernanceStack

_STAGE = "staging"

# Synthetic placeholder accounts. All three are DISTINCT so that a
# caller-side mutation passing the wrong account id into the wrong grant
# helper renders the wrong ARN and fails the principal-identity assertions
# below — the vacuity trap that `test_lf_cross_account.py`'s Fix Group 4 /
# review Cycle 6 had to close for CVX-vs-DMS.
#
# Every value is on the `aws_account_id` allowlist in
# `.publish-secrets-scan.yml`. The real CMS account id is deliberately NOT
# used here: `platform-foundation/tests/` is not `.publish-exclude`d, so a
# real 12-digit id in this file would ship to the public mirror and trip the
# scanner as critical. The task text's literal
# `arn:aws:iam::<real-cms-account>:root` is corrected here for that reason;
# the real id is supplied at deploy time via `ADP_CMS_ACCOUNT_ID` and is
# asserted live in G5.T5.1, not baked into a test.
_CMS_ACCOUNT = "111111111111"
_CVX_ACCOUNT = "123456789012"
_DMS_ACCOUNT = "222222222222"

_FAKE_LAKE_ARN = "arn:aws:s3:::adp-staging-foundation-lake-000000000000-us-east-1"
_FAKE_LAKE_NAME = "adp-staging-foundation-lake-000000000000-us-east-1"

# The five products CMS Fleet Intelligence reads (spec § D3). Exact set —
# `vehicle_telemetry_aggregated` is deliberately excluded (spec § D11).
_EXPECTED_CMS_DBS = {
    "adp_staging_service_records",
    "adp_staging_charging_sessions",
    "adp_staging_vehicle_identity",
    "adp_staging_energy_usage",
    "adp_staging_tire_health",
}

_EXPECTED_CMS_LOGICAL_IDS = {
    "LfCmsGrantServicerecords",
    "LfCmsGrantChargingsessions",
    "LfCmsGrantVehicleidentity",
    "LfCmsGrantEnergyusage",
    "LfCmsGrantTirehealth",
}


def _make_template(
    cms_account_id: str | None = None,
    cvx_account_id: str | None = None,
    dms_account_id: str | None = None,
    cms_consumer_role_arn: str | None = None,
    stage: str = _STAGE,
) -> Template:
    app = cdk.App()
    stack = GovernanceStack(
        app,
        "TestGovernanceCmsShare",
        stage=stage,
        lake_bucket_arn_export=_FAKE_LAKE_ARN,
        lake_bucket_name=_FAKE_LAKE_NAME,
        cvx_account_id=cvx_account_id,
        dms_account_id=dms_account_id,
        cms_consumer_role_arn=cms_consumer_role_arn,
        cms_account_id=cms_account_id,
        env=cdk.Environment(account="000000000000", region="us-east-1"),
    )
    return Template.from_stack(stack)


def _db_name_of(resource: dict) -> str:
    """Database name from a PrincipalPermissions resource, whichever shape it uses.

    A grant targets either a table wildcard (``Resource.Table.DatabaseName``) or
    the database itself (``Resource.Database.Name``). CMS issues both — LF needs
    database DESCRIBE *and* table SELECT before Athena will plan a query — so
    helpers that reach straight for ``["Table"]`` KeyError on the database grants.
    """
    res = resource["Properties"]["Resource"]
    if "Table" in res:
        return res["Table"]["DatabaseName"]
    return res["Database"]["Name"]


def _cms_grants(tmpl: Template) -> dict:
    """All PrincipalPermissions resources whose logical ID is a CMS grant."""
    grants = tmpl.find_resources("AWS::LakeFormation::PrincipalPermissions")
    return {k: v for k, v in grants.items() if k.startswith("LfCmsGrant")}


def _cms_db_grants(tmpl: Template) -> dict:
    """The database-level DESCRIBE grants (``LfCmsDbGrant*``).

    Deliberately a separate helper: ``_cms_grants`` filters on the
    ``LfCmsGrant`` prefix, which ``LfCmsDbGrant`` does not match, so the
    pre-existing exact-count assertions keep their meaning instead of silently
    absorbing five more resources.
    """
    grants = tmpl.find_resources("AWS::LakeFormation::PrincipalPermissions")
    return {k: v for k, v in grants.items() if k.startswith("LfCmsDbGrant")}


# ---------------------------------------------------------------------------
# Presence / absence gate
# ---------------------------------------------------------------------------


def test_cms_account_set_synthesizes_exactly_five_grants():
    """Exact count — a 6th database or a dropped one both fail here."""
    tmpl = _make_template(cms_account_id=_CMS_ACCOUNT)
    cms_ids = _cms_grants(tmpl)
    assert len(cms_ids) == 5, (
        f"expected exactly 5 CMS grants (one per spec § D3 database), "
        f"got {len(cms_ids)}: {sorted(cms_ids)}"
    )


def test_cms_grant_logical_ids_are_the_expected_exact_set():
    """Pins the logical IDs T3.3's synth-diff check greps for."""
    tmpl = _make_template(cms_account_id=_CMS_ACCOUNT)
    assert set(_cms_grants(tmpl)) == _EXPECTED_CMS_LOGICAL_IDS, (
        f"logical-ID set drift: got {sorted(_cms_grants(tmpl))}, "
        f"expected {sorted(_EXPECTED_CMS_LOGICAL_IDS)}"
    )


def test_no_cms_account_no_cms_grants():
    """`ADP_CMS_ACCOUNT_ID` unset → zero CMS grants (T3.3's synth check)."""
    tmpl = _make_template(cms_account_id=None)
    cms_ids = _cms_grants(tmpl)
    assert not cms_ids, f"no CMS account but LfCmsGrant* leaked: {sorted(cms_ids)}"


def test_empty_string_cms_account_treated_as_unset():
    """Falsy account id is 'unset', not an error — matches `if cvx_account_id:`."""
    tmpl = _make_template(cms_account_id="")
    assert not _cms_grants(tmpl)


def test_cms_only_still_bootstraps_lake_formation():
    """A CMS-only deploy must register the lake bucket with LF.

    The pre-existing bootstrap guard was `if cvx_account_id or dms_account_id`.
    Without extending it, a CMS-only deploy would synthesize five grants over
    a bucket Lake Formation does not manage, and every CMS query would fail
    at `GetDataAccess` with the grants looking correct in the console.
    """
    tmpl = _make_template(cms_account_id=_CMS_ACCOUNT)
    tmpl.resource_count_is("AWS::LakeFormation::Resource", 1)


def test_no_accounts_at_all_no_bootstrap():
    """Backward-compat: all three unset → no LF bootstrap, no grants."""
    tmpl = _make_template()
    tmpl.resource_count_is("AWS::LakeFormation::Resource", 0)
    tmpl.resource_count_is("AWS::LakeFormation::PrincipalPermissions", 0)


# ---------------------------------------------------------------------------
# Grant contract: databases, permissions, principal, wildcard
# ---------------------------------------------------------------------------


def test_cms_grants_target_the_exact_five_databases():
    tmpl = _make_template(cms_account_id=_CMS_ACCOUNT)
    grants = _cms_grants(tmpl)
    target_dbs = {
        r["Properties"]["Resource"]["Table"]["DatabaseName"] for r in grants.values()
    }
    assert target_dbs == _EXPECTED_CMS_DBS, (
        f"CMS grant database set drift: got {sorted(target_dbs)}, "
        f"expected {sorted(_EXPECTED_CMS_DBS)}"
    )


def test_cms_grants_exclude_vehicle_telemetry_aggregated():
    """Spec § D11 defers this product deliberately — assert it stays out."""
    tmpl = _make_template(cms_account_id=_CMS_ACCOUNT)
    grants = _cms_grants(tmpl)
    target_dbs = {
        r["Properties"]["Resource"]["Table"]["DatabaseName"] for r in grants.values()
    }
    assert "adp_staging_vehicle_telemetry_aggregated" not in target_dbs, (
        "vehicle_telemetry_aggregated is deferred in v1.1 (spec § D11) but a "
        "CMS grant targets it"
    )


def test_cms_grants_are_select_describe_only():
    tmpl = _make_template(cms_account_id=_CMS_ACCOUNT)
    grants = _cms_grants(tmpl)
    assert grants, "precondition: CMS grants present"
    for logical_id, resource in grants.items():
        perms = set(resource["Properties"].get("Permissions", []))
        assert perms == {"SELECT", "DESCRIBE"}, (
            f"{logical_id}: expected exactly {{SELECT, DESCRIBE}}, got {sorted(perms)}"
        )


def test_cms_grants_are_not_regrantable():
    """Empty grant-option — the CMS principal cannot re-share (CVX precedent)."""
    tmpl = _make_template(cms_account_id=_CMS_ACCOUNT)
    grants = _cms_grants(tmpl)
    assert grants, "precondition: CMS grants present"
    for logical_id, resource in grants.items():
        grant_opt = resource["Properties"].get("PermissionsWithGrantOption", [])
        assert grant_opt == [], (
            f"{logical_id}: PermissionsWithGrantOption must be empty, got {grant_opt}"
        )


def test_cms_grants_principal_is_cms_account_root():
    """Spec § D3 Decision: Option A — account root, NOT the consuming role ARN.

    Option B (`.../role/cms-{stage}-ui-FleetIntelligenceRole*`) was rejected:
    the role's CDK-generated logical-id suffix would couple ADP's stack to an
    opaque token that a CMS-side `cdk deploy` can change. Scoping happens on
    the CMS-side IAM policy (spec § D4).
    """
    tmpl = _make_template(cms_account_id=_CMS_ACCOUNT)
    grants = _cms_grants(tmpl)
    assert grants, "precondition: CMS grants present"
    for logical_id, resource in grants.items():
        principal = resource["Properties"]["Principal"]["DataLakePrincipalIdentifier"]
        assert principal == f"arn:aws:iam::{_CMS_ACCOUNT}:root", (
            f"{logical_id}: expected CMS account root principal, got {principal!r}"
        )


def test_cms_grants_use_table_wildcard_and_name_no_table():
    tmpl = _make_template(cms_account_id=_CMS_ACCOUNT)
    grants = _cms_grants(tmpl)
    assert grants, "precondition: CMS grants present"
    for logical_id, resource in grants.items():
        table = resource["Properties"]["Resource"]["Table"]
        assert "TableWildcard" in table, (
            f"{logical_id}: TableWildcard missing — the grant would be scoped "
            f"to one table instead of the whole database"
        )
        assert "Name" not in table, (
            f"{logical_id}: Table.Name present — mixes wildcard with a named table"
        )


def test_cms_grants_catalog_id_is_the_adp_account():
    tmpl = _make_template(cms_account_id=_CMS_ACCOUNT)
    for logical_id, resource in _cms_grants(tmpl).items():
        catalog_id = resource["Properties"]["Resource"]["Table"]["CatalogId"]
        assert catalog_id == "000000000000", (
            f"{logical_id}: CatalogId must be the ADP (producer) account, "
            f"got {catalog_id!r}"
        )


# ---------------------------------------------------------------------------
# Coexistence with the CVX and DMS shares
# ---------------------------------------------------------------------------


def test_cms_cvx_dms_coexist_with_expected_counts():
    """6 CVX + 2 DMS + 10 CMS = 18, no share absorbing another's grants.

    CMS is 10, not 5: **two** grants per database — a database-level DESCRIBE
    (``LfCmsDbGrant*``) and a table-wildcard SELECT+DESCRIBE (``LfCmsGrant*``).
    Lake Formation requires both before Athena will plan a query; table grants
    alone fail with "Required Describe on <database>", which is what broke T5.3
    of 2026-09-10-cms-fleet-intelligence-adp-consumer against live Athena.

    The two are counted separately rather than as one CMS total so that dropping
    either kind fails here, instead of one silently compensating for the other.

    CVX (6) and DMS (2) are table grants only and are deliberately left as they
    were — CVX's read path works because its consuming role holds a
    database-level DESCRIBE granted OUTSIDE this stack, which is exactly why the
    gap was invisible on the CMS side. Auditing those two shares is a filed
    follow-on, not a drive-by change here.
    """
    tmpl = _make_template(
        cms_account_id=_CMS_ACCOUNT,
        cvx_account_id=_CVX_ACCOUNT,
        dms_account_id=_DMS_ACCOUNT,
    )
    grants = tmpl.find_resources("AWS::LakeFormation::PrincipalPermissions")
    cvx_ids = [k for k in grants if k.startswith("LfCvx")]
    dms_ids = [k for k in grants if k.startswith("LfDms")]
    cms_table_ids = [k for k in grants if k.startswith("LfCmsGrant")]
    cms_db_ids = [k for k in grants if k.startswith("LfCmsDbGrant")]

    assert len(cvx_ids) == 6, f"expected 6 CVX grants, got {len(cvx_ids)}"
    assert len(dms_ids) == 2, f"expected 2 DMS grants, got {len(dms_ids)}"
    assert len(cms_table_ids) == 5, (
        f"expected 5 CMS table grants, got {len(cms_table_ids)}: {sorted(cms_table_ids)}"
    )
    assert len(cms_db_ids) == 5, (
        f"expected 5 CMS database-level DESCRIBE grants, got {len(cms_db_ids)}: "
        f"{sorted(cms_db_ids)}"
    )
    assert len(grants) == 18, (
        f"expected 18 total PrincipalPermissions (6 CVX + 2 DMS + 5 CMS table + "
        f"5 CMS database), got {len(grants)}"
    )


def test_each_share_carries_its_own_principal():
    """Distinct placeholders make a swapped-argument mutation visible."""
    tmpl = _make_template(
        cms_account_id=_CMS_ACCOUNT,
        cvx_account_id=_CVX_ACCOUNT,
        dms_account_id=_DMS_ACCOUNT,
    )
    grants = tmpl.find_resources("AWS::LakeFormation::PrincipalPermissions")
    expected = {
        "LfCvx": f"arn:aws:iam::{_CVX_ACCOUNT}:root",
        "LfDms": f"arn:aws:iam::{_DMS_ACCOUNT}:root",
        "LfCms": f"arn:aws:iam::{_CMS_ACCOUNT}:root",
    }
    for logical_id, resource in grants.items():
        prefix = next(p for p in expected if logical_id.startswith(p))
        principal = resource["Properties"]["Principal"]["DataLakePrincipalIdentifier"]
        assert principal == expected[prefix], (
            f"{logical_id}: expected {expected[prefix]}, got {principal!r}"
        )


def test_cms_share_overlaps_cvx_by_design_but_dms_stays_disjoint():
    """CMS re-shares 3 CVX databases under its OWN principal (spec § D3).

    CVX's and CMS's database sets intersect deliberately — LF grants are
    per-principal, so CMS needs its own grant even on a database CVX already
    reads. What must NOT happen is CMS reaching the DMS dealer/parts domains.
    """
    tmpl = _make_template(
        cms_account_id=_CMS_ACCOUNT,
        cvx_account_id=_CVX_ACCOUNT,
        dms_account_id=_DMS_ACCOUNT,
    )
    grants = tmpl.find_resources("AWS::LakeFormation::PrincipalPermissions")

    def dbs(prefix: str) -> set[str]:
        return {
            _db_name_of(r)
            for k, r in grants.items()
            if k.startswith(prefix)
        }

    cms_dbs, cvx_dbs, dms_dbs = dbs("LfCms"), dbs("LfCvx"), dbs("LfDms")

    assert cms_dbs == _EXPECTED_CMS_DBS, sorted(cms_dbs)
    # Intended overlap with CVX — pinned as an exact set so a change is visible.
    assert cms_dbs & cvx_dbs == {
        "adp_staging_service_records",
        "adp_staging_charging_sessions",
        "adp_staging_vehicle_identity",
    }, sorted(cms_dbs & cvx_dbs)
    # CMS must never reach the DMS domains.
    assert cms_dbs.isdisjoint(dms_dbs), (
        f"CMS grants leaked into DMS-only databases: {sorted(cms_dbs & dms_dbs)}"
    )
    assert not (cms_dbs & {"adp_staging_dealer_domain", "adp_staging_parts_domain"})


# ---------------------------------------------------------------------------
# Account-id shape validation (fail-closed)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "12345",  # too short
        "1111111111111",  # 13 digits
        "11111111111x",  # 12 chars, not all digits
        "arn:aws:iam::111111111111:root",  # full ARN passed by mistake
        " 111111111111",  # leading whitespace
        "111111111111 ",  # trailing whitespace
        "111-111-111-11",  # punctuation
    ],
)
def test_invalid_cms_account_id_shape_raises_at_synth(bad: str):
    """Fail closed on a malformed account id rather than rendering a bad ARN.

    Without this, `arn:aws:iam::12345:root` synthesizes happily and the deploy
    fails deep inside Lake Formation with an opaque principal error.
    """
    with pytest.raises(ValueError, match="cms_account_id"):
        _make_template(cms_account_id=bad)


def test_valid_twelve_digit_cms_account_id_does_not_raise():
    """Positive control for the validator — a real 12-digit id must pass."""
    tmpl = _make_template(cms_account_id=_CMS_ACCOUNT)
    assert len(_cms_grants(tmpl)) == 5


# ---------------------------------------------------------------------------
# Prod stage (T3.4's contract, asserted hermetically as well as via synth)
# ---------------------------------------------------------------------------


def test_prod_stage_grants_name_adp_prod_databases():
    tmpl = _make_template(cms_account_id=_CMS_ACCOUNT, stage="prod")
    grants = _cms_grants(tmpl)
    assert len(grants) == 5, f"expected 5 prod CMS grants, got {len(grants)}"
    target_dbs = {
        r["Properties"]["Resource"]["Table"]["DatabaseName"] for r in grants.values()
    }
    assert target_dbs == {
        "adp_prod_service_records",
        "adp_prod_charging_sessions",
        "adp_prod_vehicle_identity",
        "adp_prod_energy_usage",
        "adp_prod_tire_health",
    }, sorted(target_dbs)
    assert all(db.startswith("adp_prod_") for db in target_dbs), sorted(target_dbs)



# ---------------------------------------------------------------------------
# Database-level DESCRIBE grants
#
# Lake Formation requires DESCRIBE on the DATABASE in addition to table-level
# SELECT before Athena will plan a query that references a table inside it.
# Table grants alone fail the whole statement with
#   Insufficient Lake Formation permission(s):
#     Required Describe on adp_staging_service_records
# naming the DATABASE, not the table — which reads like a table-grant problem
# and is not one. Found 2026-09-12 running T5.3 of
# 2026-09-10-cms-fleet-intelligence-adp-consumer against live Athena, AFTER
# T5.1 had verified the table grants and correctly reported them present.
# ---------------------------------------------------------------------------


def test_cms_database_level_describe_grant_exists_per_share_database():
    """One database-level DESCRIBE per shared database, exact set."""
    tmpl = _make_template(cms_account_id=_CMS_ACCOUNT)
    db_grants = _cms_db_grants(tmpl)

    assert len(db_grants) == 5, (
        f"expected 5 database-level grants, got {len(db_grants)}: {sorted(db_grants)}"
    )
    named = {_db_name_of(r) for r in db_grants.values()}
    assert named == _EXPECTED_CMS_DBS, sorted(named)


def test_cms_database_grants_target_the_database_not_a_table():
    """The grant must use Resource.Database — a table grant here fixes nothing.

    Asserts ON the resource shape, because that shape is the whole point: a
    second table-level grant would satisfy a count assertion while leaving the
    live query failing exactly as before.
    """
    tmpl = _make_template(cms_account_id=_CMS_ACCOUNT)
    for logical_id, r in _cms_db_grants(tmpl).items():
        res = r["Properties"]["Resource"]
        assert "Database" in res, (
            f"{logical_id}: must grant on Resource.Database; got keys {sorted(res)}"
        )
        assert "Table" not in res, (
            f"{logical_id}: must NOT be a table grant — that is the defect this "
            f"grant exists to fix; got keys {sorted(res)}"
        )


def test_cms_database_grants_are_describe_only_and_cannot_re_share():
    """DESCRIBE only, no grant option. Guards against widening to ALL/CREATE_TABLE.

    The read itself is authorized table-side, so anything beyond DESCRIBE here is
    unnecessary authority over a database of customer data. Pinned as an exact
    set so a widening is a test failure rather than a review-time judgement.
    """
    tmpl = _make_template(cms_account_id=_CMS_ACCOUNT)
    for logical_id, r in _cms_db_grants(tmpl).items():
        perms = r["Properties"]["Permissions"]
        assert perms == ["DESCRIBE"], (
            f"{logical_id}: database grant must be exactly ['DESCRIBE'], got {perms}. "
            "CREATE_TABLE / ALTER / DROP / ALL on a shared database is a widening."
        )
        assert r["Properties"]["PermissionsWithGrantOption"] == [], (
            f"{logical_id}: the CMS principal must not be able to re-share"
        )


def test_cms_database_grants_use_the_cms_principal_and_producer_catalog():
    """Right principal, right catalog — a grant to the wrong account is invisible at synth."""
    tmpl = _make_template(cms_account_id=_CMS_ACCOUNT)
    for logical_id, r in _cms_db_grants(tmpl).items():
        principal = r["Properties"]["Principal"]["DataLakePrincipalIdentifier"]
        assert principal == f"arn:aws:iam::{_CMS_ACCOUNT}:root", (
            f"{logical_id}: expected the CMS account root, got {principal!r}"
        )
        catalog_id = r["Properties"]["Resource"]["Database"]["CatalogId"]
        assert catalog_id == "000000000000", (
            f"{logical_id}: CatalogId must be the ADP (producer) account, got {catalog_id!r}"
        )


def test_cms_database_grants_absent_when_cms_account_unset():
    """The share stays opt-in — no CMS account, no CMS grants of either kind."""
    tmpl = _make_template()
    assert _cms_db_grants(tmpl) == {}
    assert _cms_grants(tmpl) == {}


def test_prod_stage_database_grants_name_adp_prod_databases():
    """T3.4's stage contract applies to the database grants too."""
    tmpl = _make_template(cms_account_id=_CMS_ACCOUNT, stage="prod")
    named = {_db_name_of(r) for r in _cms_db_grants(tmpl).values()}
    assert named == {
        "adp_prod_service_records",
        "adp_prod_charging_sessions",
        "adp_prod_vehicle_identity",
        "adp_prod_energy_usage",
        "adp_prod_tire_health",
    }, sorted(named)



# ---------------------------------------------------------------------------
# The CMS consuming-ROLE grants — the ones that actually authorize the read.
#
# CMS and ADP are the same account, so `arn:aws:iam::<acct>:root` is inert for
# an individual IAM role: :root is the CROSS-account idiom. Proven 2026-09-13 —
# with both :root grant kinds live, Athena still returned "Required Describe on
# adp_staging_service_records"; granting the role directly moved the error to the
# next un-granted database and then to a 200.
# ---------------------------------------------------------------------------

_CONSUMER_ROLE = (
    "arn:aws:iam::111111111111:role/cms-staging-ui-FleetIntelligenceRoleABC123-xyz"
)


def _cms_role_grants(tmpl: Template) -> dict:
    grants = tmpl.find_resources("AWS::LakeFormation::PrincipalPermissions")
    return {k: v for k, v in grants.items() if k.startswith("LfCmsRole")}


def test_consumer_role_grants_absent_when_arn_unset():
    """Opt-in — the pre-2026-09-13 behaviour must be reachable."""
    tmpl = _make_template(cms_account_id=_CMS_ACCOUNT)
    assert _cms_role_grants(tmpl) == {}


def test_consumer_role_gets_both_database_and_table_grants_per_database():
    """10 = 5 databases x (database DESCRIBE + table SELECT/DESCRIBE).

    Both kinds are required: database DESCRIBE alone cannot read, and table
    SELECT alone fails planning with "Required Describe on <database>".
    """
    tmpl = _make_template(
        cms_account_id=_CMS_ACCOUNT, cms_consumer_role_arn=_CONSUMER_ROLE
    )
    role_grants = _cms_role_grants(tmpl)
    db = {k: v for k, v in role_grants.items() if k.startswith("LfCmsRoleDbGrant")}
    tb = {k: v for k, v in role_grants.items() if k.startswith("LfCmsRoleTableGrant")}

    assert len(db) == 5, f"expected 5 role database grants, got {sorted(db)}"
    assert len(tb) == 5, f"expected 5 role table grants, got {sorted(tb)}"
    assert {_db_name_of(r) for r in db.values()} == _EXPECTED_CMS_DBS
    assert {_db_name_of(r) for r in tb.values()} == _EXPECTED_CMS_DBS


def test_consumer_role_grants_name_the_ROLE_not_the_account_root():
    """The whole point: principal must be the role ARN.

    A `:root` principal here would satisfy every count assertion while leaving
    the live query failing exactly as it did before — which is precisely the
    defect this construct exists to fix, so it is asserted directly.
    """
    tmpl = _make_template(
        cms_account_id=_CMS_ACCOUNT, cms_consumer_role_arn=_CONSUMER_ROLE
    )
    for logical_id, r in _cms_role_grants(tmpl).items():
        principal = r["Properties"]["Principal"]["DataLakePrincipalIdentifier"]
        assert principal == _CONSUMER_ROLE, (
            f"{logical_id}: must grant to the consuming ROLE, got {principal!r}"
        )
        assert not principal.endswith(":root"), (
            f"{logical_id}: a :root principal is inert same-account — that is the bug"
        )


def test_consumer_role_grants_are_least_privilege_and_cannot_re_share():
    """Database grants DESCRIBE only; table grants SELECT+DESCRIBE only; no grant option."""
    tmpl = _make_template(
        cms_account_id=_CMS_ACCOUNT, cms_consumer_role_arn=_CONSUMER_ROLE
    )
    for logical_id, r in _cms_role_grants(tmpl).items():
        perms = sorted(r["Properties"]["Permissions"])
        if "Database" in r["Properties"]["Resource"]:
            assert perms == ["DESCRIBE"], f"{logical_id}: got {perms}"
        else:
            assert perms == ["DESCRIBE", "SELECT"], f"{logical_id}: got {perms}"
        assert r["Properties"]["PermissionsWithGrantOption"] == [], (
            f"{logical_id}: the consumer must not be able to re-share"
        )


def test_root_grants_are_retained_alongside_the_role_grants():
    """:root grants stay — correct if CMS ever moves accounts, inert not harmful now.

    Pinned so a future change that "cleans up" the root grants is a visible
    decision rather than a silent one. 12 role grants = 10 product grants + the
    dimensions database DESCRIBE + the dimensions.vins table grant.
    """
    tmpl = _make_template(
        cms_account_id=_CMS_ACCOUNT, cms_consumer_role_arn=_CONSUMER_ROLE
    )
    assert len(_cms_grants(tmpl)) == 5, "root table grants must be retained"
    assert len(_cms_db_grants(tmpl)) == 5, "root database grants must be retained"
    assert len(_cms_role_grants(tmpl)) == 12, "role grants must be additive"


# ---------------------------------------------------------------------------
# The dimensions grant — spec 2026-09-25-cms-fi-adp-wide-lifecycle.
#
# The ADP-wide lifecycle rollup joins adp_{stage}_dimensions.vins for model and
# model year. The first staging refresh was denied because the role had no
# grant on that database (issues/2026-09-26-fi-adp-rollup-role-lacks-dimensions-
# grant in the CMS repo). The same database holds `customers` (PII), so the
# grant must name `vins` and never use a table wildcard.
# ---------------------------------------------------------------------------

_DIMENSIONS_DB = "adp_staging_dimensions"


def _grant_db_name(resource: dict) -> str | None:
    """Database a PrincipalPermissions targets, for every resource shape LF has.

    Returns None for shapes with no database (catalog, data location, LF-tag
    policy). Unlike ``_db_name_of`` it never KeyErrors, so a grant in an
    unexpected shape is still seen by the scans below.
    """
    res = resource["Properties"]["Resource"]
    if "Table" in res:
        return res["Table"].get("DatabaseName")
    if "TableWithColumns" in res:
        return res["TableWithColumns"].get("DatabaseName")
    if "DataCellsFilter" in res:
        return res["DataCellsFilter"].get("DatabaseName")
    if "Database" in res:
        return res["Database"].get("Name")
    return None


def _all_dimension_grants(tmpl: Template) -> dict:
    """Every grant on the dimensions database, whatever its logical ID or principal."""
    return {
        k: v
        for k, v in tmpl.find_resources("AWS::LakeFormation::PrincipalPermissions").items()
        if _grant_db_name(v) == _DIMENSIONS_DB
    }


def test_no_legacy_lf_permissions_resource_touches_dimensions():
    """The older `AWS::LakeFormation::Permissions` type is not scanned above.

    Nothing in this repo uses it, so any such resource on the dimensions
    database is a grant the checks above would miss.
    """
    tmpl = _make_template(
        cms_account_id=_CMS_ACCOUNT, cms_consumer_role_arn=_CONSUMER_ROLE
    )
    legacy = tmpl.find_resources("AWS::LakeFormation::Permissions")
    assert "dimensions" not in str(legacy), sorted(legacy)


def _cms_role_dimension_grants(tmpl: Template) -> dict:
    return {
        k: v for k, v in _cms_role_grants(tmpl).items()
        if _db_name_of(v) == _DIMENSIONS_DB
    }


def test_consumer_role_gets_database_describe_and_vins_select_on_dimensions():
    """Exactly two grants: DESCRIBE on the database, SELECT+DESCRIBE on `vins`.

    Both are needed: table SELECT alone fails planning with "Required Describe
    on <database>", and database DESCRIBE alone reads nothing.
    """
    tmpl = _make_template(
        cms_account_id=_CMS_ACCOUNT, cms_consumer_role_arn=_CONSUMER_ROLE
    )
    grants = _cms_role_dimension_grants(tmpl)
    assert len(grants) == 2, sorted(grants)

    db = [v for v in grants.values() if "Database" in v["Properties"]["Resource"]]
    tb = [v for v in grants.values() if "Table" in v["Properties"]["Resource"]]
    assert len(db) == 1 and len(tb) == 1, sorted(grants)
    assert sorted(db[0]["Properties"]["Permissions"]) == ["DESCRIBE"]
    assert sorted(tb[0]["Properties"]["Permissions"]) == ["DESCRIBE", "SELECT"]
    assert tb[0]["Properties"]["Resource"]["Table"]["Name"] == "vins"
    for v in grants.values():
        assert v["Properties"]["Principal"]["DataLakePrincipalIdentifier"] == _CONSUMER_ROLE
        assert v["Properties"]["PermissionsWithGrantOption"] == []


def test_dimensions_grant_never_uses_a_table_wildcard_and_never_names_customers():
    """`customers` is PII. A wildcard would grant it, and any table added later.

    Scans every grant on the dimensions database, not only ``LfCmsRole*`` IDs,
    so a wildcard added under another logical ID or principal fails here.
    Review dimgrant Cycle 1 W2.
    """
    tmpl = _make_template(
        cms_account_id=_CMS_ACCOUNT, cms_consumer_role_arn=_CONSUMER_ROLE
    )
    grants = _all_dimension_grants(tmpl)
    assert len(grants) == 2, (
        f"expected exactly 2 grants on {_DIMENSIONS_DB} (database DESCRIBE + vins), "
        f"got {sorted(grants)}"
    )
    for logical_id, v in grants.items():
        res = v["Properties"]["Resource"]
        assert set(res) <= {"Database", "Table"}, f"{logical_id}: resource shape {sorted(res)}"
        table = res.get("Table")
        if table is not None:
            assert "TableWildcard" not in table, f"{logical_id}: table wildcard on dimensions"
            assert table.get("Name") == "vins", f"{logical_id}: names {table.get('Name')!r}"

    all_grants = tmpl.find_resources("AWS::LakeFormation::PrincipalPermissions")
    assert "customers" not in str(all_grants), "a grant names the customers table (PII)"


def test_consumer_role_grants_are_only_database_or_table_shapes():
    """No LF-tag, catalog, data-location or column/cell-filter grants to the role.

    An LF-tag policy grant could reach `customers` through a tag, which none of
    the per-database checks would see.
    """
    tmpl = _make_template(
        cms_account_id=_CMS_ACCOUNT, cms_consumer_role_arn=_CONSUMER_ROLE
    )
    role_grants = [
        (k, v) for k, v in tmpl.find_resources(
            "AWS::LakeFormation::PrincipalPermissions"
        ).items()
        if v["Properties"]["Principal"]["DataLakePrincipalIdentifier"] == _CONSUMER_ROLE
    ]
    assert len(role_grants) == 12, sorted(k for k, _ in role_grants)
    for logical_id, v in role_grants:
        shape = set(v["Properties"]["Resource"])
        assert shape in ({"Database"}, {"Table"}), f"{logical_id}: resource shape {sorted(shape)}"


def test_dimensions_grant_is_role_only_not_the_root_shares():
    """The :root share is inert same-account; widening it is a separate decision."""
    tmpl = _make_template(cms_account_id=_CMS_ACCOUNT)
    assert not [
        k for k, v in tmpl.find_resources(
            "AWS::LakeFormation::PrincipalPermissions"
        ).items()
        if _db_name_of(v) == _DIMENSIONS_DB
    ], "dimensions granted without a consumer role ARN"


def test_prod_stage_dimensions_grant_names_the_prod_database():
    tmpl = _make_template(
        cms_account_id=_CMS_ACCOUNT,
        cms_consumer_role_arn=_CONSUMER_ROLE,
        stage="prod",
    )
    dbs = {
        _db_name_of(v) for v in _cms_role_grants(tmpl).values()
    }
    assert "adp_prod_dimensions" in dbs
    assert not any(d.startswith("adp_staging_") for d in dbs), sorted(dbs)



# ---------------------------------------------------------------------------
# Fix Group 1 — review Group 5 cycle 1, W1: consumer-role ARN shape validation.
# A malformed principal synthesizes cleanly and fails opaquely inside Lake
# Formation at deploy, the same failure mode _validate_account_id prevents.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "cms-staging-ui-FleetIntelligenceRoleABC123-xyz",  # bare role NAME
        "arn:aws:iam::111111111111:user/someone",          # a USER, not a role
        "arn:aws:iam::111111111111:root",                  # account root
        " arn:aws:iam::111111111111:role/x",               # leading whitespace
        "arn:aws:iam::111111111111:role/x ",               # trailing whitespace
        "arn:aws:iam::111111111111:role/",                 # empty name (failed lookup)
        "not-an-arn",
    ],
)
def test_malformed_consumer_role_arn_raises_at_synth(bad: str):
    with pytest.raises(ValueError, match="cms_consumer_role_arn"):
        _make_template(cms_account_id=_CMS_ACCOUNT, cms_consumer_role_arn=bad)


def test_wellformed_consumer_role_arn_does_not_raise():
    """Positive control — a real role ARN must pass and produce its 12 grants."""
    tmpl = _make_template(
        cms_account_id=_CMS_ACCOUNT, cms_consumer_role_arn=_CONSUMER_ROLE
    )
    assert len(_cms_role_grants(tmpl)) == 12
