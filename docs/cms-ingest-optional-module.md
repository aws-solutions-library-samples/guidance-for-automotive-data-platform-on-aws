# Optional CMS→ADP ingest module

This document is the operator-facing runbook for the **optional**
CMS→ADP ingest module. The module lets ADP consume change events
from a CMS DynamoDB table (e.g. `cms-prod-vehicle-state`), land them
on the ADP foundation lake as parquet, and MERGE them into per-table
Iceberg replicas in a dedicated `adp_{stage}_cms_ingest` Glue
database.

> **It is off by default.** Vanilla `make deploy STAGE=staging|prod`
> creates **zero** CMS-ingest resources. Skip this doc unless you
> are running both CMS and ADP in the same AWS account and want a
> read-only replica of CMS DDB tables in the ADP analytical lake.

The module ships as a Should-Have per the spec
([`spec.md` Risk #10](../.kiro/specs/2026-05-28-adp-ev-startup-foundation/spec.md))
and is the first to slip if schedule is at risk.

> **Placeholder notation in commands and ARNs below**: any
> `<account>` token is a **user-substitution** — replace it with
> your 12-digit AWS account ID before running the command (e.g.
> `aws sts get-caller-identity --query Account --output text`).
> The region is pinned to `us-east-1` as a literal throughout
> (single-region by design — see
> [`docs/DEPLOYMENT.md` "Why single-region"](DEPLOYMENT.md#why-single-region));
> there is no `<region>` placeholder. Stage tokens (`{stage}`) are
> filled by the `STAGE=staging|prod` environment per the Makefile
> contract.

---

## 1. Opt-in rationale

ADP customers who do not run CMS see **no benefit** from the ingest
module — turning it on imposes the cost of one Firehose stream + one
Glue Spark job + one EventBridge schedule with no return.

Customers who run both CMS and ADP gain:

* A near-real-time (≈1–2 minute end-to-end) Iceberg replica of
  CMS-owned operational data, queryable from Athena alongside the
  9 ADP data products.
* No CMS code changes required — ingest is read-only on DDB
  Streams (the source-side stream is owned by CMS; ADP consumes).
* A single MERGE pipeline that handles inserts, updates, and
  deletes (Iceberg `MERGE INTO` with a tombstone branch on
  `REMOVE` events).

---

## 2. Prereqs

### 2.1 Single-account assumption (v1)

v1 assumes **CMS and ADP live in the same AWS account**. The
foundation's stage is irrelevant to CMS — staging and prod ADP
stages can each consume the same CMS table or different ones, but
the CMS table itself must reside in the same account where the
selected ADP stage is deployed. Cross-account guidance is in
[§ 8 — Cross-account (deferred to v2)](#8-cross-account-deferred-to-v2).

### 2.2 CMS DDB table is reachable

The CMS table ARN you pass via `-c cms_vehicle_state_table_arn=...`
must:

* Resolve in the **same account + region** as the ADP foundation
  (us-east-1, fixed per spec Constraint #3).
* Be in `ACTIVE` table status.
* Have **DynamoDB Streams enabled** with `StreamViewType =
  NEW_AND_OLD_IMAGES` (the MERGE job needs the OLD image to compute
  Iceberg deletes).

Run the helper to audit:

```bash
.venv/bin/python -m source.optional.cms_ingest.enable_streams \
    --table-arn arn:aws:dynamodb:us-east-1:<account>:table/cms-prod-vehicle-state
```

Expected output (audit-only, exit `0`):

```json
{
  "action": "audit",
  "enabled": true,
  "view_type": "NEW_AND_OLD_IMAGES",
  "stream_arn": "arn:aws:dynamodb:us-east-1:<account>:table/cms-prod-vehicle-state/stream/2026-..."
}
```

If the audit fails (streams disabled, or wrong view type), re-run
with `--enable` to fix it idempotently:

```bash
.venv/bin/python -m source.optional.cms_ingest.enable_streams \
    --table-arn arn:aws:dynamodb:us-east-1:<account>:table/cms-prod-vehicle-state \
    --enable
```

> ⚠️ **Toggling streams on a write-hot table is operationally risky.**
> The shard iterator resets, and Firehose will miss every record
> written during the cutover window. Coordinate with the CMS
> operator before running with `--enable` against a production CMS
> table.

### 2.3 IAM trust

Ingest is **read-only** on the CMS side. The Firehose role this
stack creates does not require any policy on the CMS DDB table
itself — Firehose ingests records that have already been put to it
by a Lambda transformer. The Lambda transformer (not provisioned by
this stack — see § 6) reads the DDB Stream via standard
`dynamodb-streams:*` actions, which work with a same-account
identity-based policy.

The DDB resource-based policy on the CMS table is **not** required
for v1 (same-account). Cross-account guidance: § 8.

### 2.4 ADP foundation stage already deployed

The optional stack consumes the foundation's stage-prefixed lake
bucket (`adp-{stage}-foundation-lake-<account>-us-east-1`). Make
sure `make deploy STAGE=<stage>` has succeeded once before
opting in to ingest.

---

## 3. Enable command

From the `platform-foundation/` directory:

```bash
make deploy-cms-ingest STAGE=staging \
    CMS_TABLE_ARN=arn:aws:dynamodb:us-east-1:<account>:table/cms-prod-vehicle-state
```

The Makefile target dispatches to the canonical CDK invocation:

```bash
.venv/bin/cdk deploy adp-staging-foundation-cms-ingest \
    -c stage=staging \
    -c enable_cms_ingest=true \
    -c cms_vehicle_state_table_arn=arn:aws:dynamodb:us-east-1:<account>:table/cms-prod-vehicle-state \
    --require-approval never
```

What gets created (per stage):

| Resource | Stage-prefixed name (staging) | Notes |
|---|---|---|
| Glue database | `adp_staging_cms_ingest` | Raw replica DB. NOT a published product. |
| Glue table (Firehose schema target) | `_firehose_staging_records` | Drives JSON → parquet conversion. |
| Glue Iceberg target table | `vehicle_state` | One per CMS source table registered in `TABLE_PROJECTIONS`. |
| Kinesis Firehose stream | `adp-staging-foundation-cms-vehicle-state` | 60s / 64MiB buffering. Parquet + ZSTD. |
| Firehose IAM role | `adp-staging-foundation-cms-ingest-firehose-role` | S3 PutObject + Glue GetTable + KMS decrypt scoped to `cms-ingest/`. |
| Glue MERGE job | `adp-staging-foundation-cms-ingest-merge` | 2× G.1X workers; 10-min timeout. |
| Glue MERGE job IAM role | `adp-staging-foundation-cms-ingest-glue-role` | S3 RW + Glue catalog edit + KMS scoped to `cms-ingest/` and `curated/cms-ingest/`. |
| EventBridge rule | `adp-staging-foundation-cms-ingest-merge-schedule` | Fires every 15 min. |
| EventBridge IAM role | `adp-staging-foundation-cms-ingest-schedule-role` | `glue:StartJobRun` only. |

S3 prefix layout under the lake bucket:

```
s3://adp-{stage}-foundation-lake-<account>-us-east-1/
  cms-ingest/
    vehicle_state/
      dt=2026-05-29/
        adp-staging-foundation-cms-vehicle-state-1-2026-05-29-...parquet
    _errors/
      ProcessingFailed/
        dt=2026-05-29/
    _archive/                  # consumed parquet (after MERGE)
      vehicle_state/
        dt=2026-05-28/
  curated/
    cms-ingest/
      vehicle_state/
        metadata/              # Iceberg snapshot manifests
        data/                  # Iceberg data files
```

After deploy, `make smoke-test STAGE=staging` continues to pass —
the smoke-test in pre-Group-3 mode does not exercise CMS ingest, so
adding the optional stack is a no-op against the foundation's
acceptance contract.

---

## 4. Disable command

From the `platform-foundation/` directory:

```bash
.venv/bin/cdk destroy adp-staging-foundation-cms-ingest \
    -c stage=staging \
    -c enable_cms_ingest=true \
    -c cms_vehicle_state_table_arn=arn:aws:dynamodb:us-east-1:<account>:table/cms-prod-vehicle-state \
    --require-approval never
```

> The `enable_cms_ingest=true` and `cms_vehicle_state_table_arn=...`
> context flags must be supplied to `cdk destroy` so the app
> instantiates the stack. Without them, CDK reports "no stack with
> name adp-staging-foundation-cms-ingest" because `app.py` skips
> the construct when the flag is OFF.

`cdk destroy` removes the Glue database, Iceberg tables (catalog
entries — the parquet on S3 stays), Firehose stream, IAM roles, and
EventBridge rule. The lake bucket itself stays (it is owned by
`adp-{stage}-foundation-lake`).

To fully tear down the data, see [§ 7 — Tear-down and archival](#7-tear-down-and-archival).

---

## 5. Data freshness expectations

| Hop | Latency | Failure mode |
|---|---|---|
| CMS DDB write → DDB Streams record | ~ms (DDB-internal) | Ignorable. |
| DDB Streams → Lambda transformer | < 1 s shard-poll | Lambda errors → retry; >1h delay → consult Lambda metrics. |
| Lambda → Firehose `PutRecord` | < 100 ms per record | Firehose-side retry on 5xx; sticky errors → `_errors/` prefix. |
| Firehose buffer flush | ≤ 60 s OR 64 MiB | Configured in [`firehose_schema.py`](../platform-foundation/source/optional/cms_ingest/firehose_schema.py). |
| S3 PutObject (parquet) | < 1 s | Standard S3 retry semantics. |
| EventBridge → Glue MERGE | every 15 min | `max_concurrent_runs=1` — overlaps queue. |
| Glue MERGE → Iceberg snapshot | < 5 min on 2× G.1X for `vehicle_state` (~10K rows / window) | Failures land in CloudWatch Logs under `/aws-glue/jobs/`. |

End-to-end **wire → queryable**: typically 1–2 minutes after the
DDB write, plus the wait for the next 15-minute schedule slot.
Worst case (write at minute 0, slot at minute 15): ~16 minutes.

The MERGE job's `_seq_no`-based idempotency makes overlapping
windows safe — duplicates become no-ops, never double-insert.

---

## 6. Lambda transformer (operator-supplied)

The Firehose stream type is `DirectPut`. Records arrive via
`firehose:PutRecord` from a Lambda transformer — **not** via a
direct DDB-Stream → Firehose source mapping (Firehose's
`KinesisStreamAsSource` is documented in `docs/tech.md` but has
cross-account limitations and a 1024-byte-record cap that DDB-Stream
records can exceed).

The Lambda transformer is intentionally **not provisioned by this
stack** because:

1. It belongs in the same account as the CMS DDB table, which is
   the operator's call.
2. CMS will likely wire it to its own observability stack.
3. The transformer is small (~50 lines) and stable across CMS
   schema evolution since it only re-shapes the envelope.

Drop-in transformer (Python 3.12, AWS Lambda):

```python
import base64
import json
import os
from datetime import datetime, timezone

import boto3

_FIREHOSE = boto3.client("firehose")
_STREAM_NAME = os.environ["FIREHOSE_STREAM_NAME"]
_TABLE_NAME = os.environ["TABLE_LOGICAL_NAME"]  # e.g. 'vehicle_state'


def handler(event, context):
    """DDB Stream event → Firehose putRecord (one PUT per record)."""
    for record in event["Records"]:
        envelope = {
            "event_id": record["eventID"],
            "event_name": record["eventName"],          # INSERT|MODIFY|REMOVE
            "event_version": record["eventVersion"],
            "event_source": record["eventSource"],
            "aws_region": record["awsRegion"],
            "approximate_creation_datetime": (
                datetime.fromtimestamp(
                    record["dynamodb"]["ApproximateCreationDateTime"],
                    tz=timezone.utc,
                ).isoformat()
            ),
            "ingest_time": datetime.now(timezone.utc).isoformat(),
            "sequence_number": record["dynamodb"]["SequenceNumber"],
            "size_bytes": record["dynamodb"]["SizeBytes"],
            "table_name": _TABLE_NAME,
            "keys": json.dumps(record["dynamodb"].get("Keys", {})),
            "new_image": json.dumps(record["dynamodb"].get("NewImage", {})),
            "old_image": json.dumps(record["dynamodb"].get("OldImage", {})),
        }
        # Newline delimiter helps Firehose's OpenXJsonSerDe parse
        # multiple records from a single payload if you ever batch.
        _FIREHOSE.put_record(
            DeliveryStreamName=_STREAM_NAME,
            Record={"Data": (json.dumps(envelope) + "\n").encode("utf-8")},
        )
    return {"batchItemFailures": []}
```

Wire the Lambda's event source mapping to the CMS DDB table's
stream ARN, set the env vars, and grant the function role:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:DescribeStream",
        "dynamodb:GetRecords",
        "dynamodb:GetShardIterator",
        "dynamodb:ListStreams"
      ],
      "Resource": "arn:aws:dynamodb:us-east-1:<account>:table/cms-prod-vehicle-state/stream/*"
    },
    {
      "Effect": "Allow",
      "Action": ["firehose:PutRecord", "firehose:PutRecordBatch"],
      "Resource": "arn:aws:firehose:us-east-1:<account>:deliverystream/adp-staging-foundation-cms-vehicle-state"
    }
  ]
}
```

---

## 7. Tear-down and archival

`cdk destroy` (§ 4) removes the catalog + roles + schedule but
leaves S3 data behind on purpose — so the operator can replay or
back up before deleting raw DDB-Stream records.

To purge the per-stage CMS-ingest data after `cdk destroy`:

```bash
# 1. Empty the staged + curated CMS-ingest prefixes (destructive).
aws s3 rm s3://adp-staging-foundation-lake-<account>-us-east-1/cms-ingest/ --recursive
aws s3 rm s3://adp-staging-foundation-lake-<account>-us-east-1/curated/cms-ingest/ --recursive

# 2. Drop the Iceberg table metadata if any leaked (rare — cdk destroy
#    handles this via the Glue:DeleteTable cascade).
aws glue delete-table \
    --database-name adp_staging_cms_ingest \
    --name vehicle_state || true
```

Alternatively, archive consumed parquet (the MERGE job logs the
archive intent today; the actual move is a 30-line follow-up). Run:

```bash
aws s3 mv \
    s3://adp-staging-foundation-lake-<account>-us-east-1/cms-ingest/vehicle_state/dt=2026-05-29/ \
    s3://adp-staging-foundation-lake-<account>-us-east-1/cms-ingest/_archive/vehicle_state/dt=2026-05-29/ \
    --recursive
```

---

## 8. Cross-account (deferred to v2)

v1 is single-account. The cross-account pattern is documented but
**not implemented** because:

1. Firehose's `KinesisStreamAsSource` does not accept cross-account
   Kinesis Streams natively
   ([docs/tech.md](tech.md) "DynamoDB Streams — cross-account configuration").
2. The work-around is a two-account stream relay (CMS-account
   Lambda → cross-account Kinesis Data Stream → ADP-account
   Firehose), which doubles the operational surface and is
   out-of-scope for the Should-Have v1 module.

When v2 ships, the cross-account piece adds:

* CMS-side: DDB resource-based policy on the table allowing the ADP
  Lambda role `dynamodb:DescribeStream`, `dynamodb:GetRecords`,
  `dynamodb:GetShardIterator`, `dynamodb:ListStreams`.
* ADP-side: identity-based policy on the Lambda role granting the
  same actions on the cross-account stream ARN.
* Both halves are required (RBP + identity policy).
* CloudTrail logs the cross-account read in both accounts.

Pitfalls (carry-overs from `docs/tech.md`):

* "Internal table configuration APIs" (e.g., `UpdateTimeToLive`,
  `DisableKinesisStreamingDestination`) do **not** support
  cross-account access. ADP must NEVER attempt to alter CMS table
  state — ingest is read-only on streams.
* Stream resource-based policies do not exist on the stream itself
  — the policy lives on the parent table. All API calls to the
  stream resolve back to the table for auth.

---

## 9. Cost estimate

For a CMS `vehicle_state` table at ~50K rows updated per hour:

| Component | Monthly $ (us-east-1, 2026 list price) |
|---|---|
| DDB Streams read | $0 (always-on for write-hot table; ADP reads incur no extra cost) |
| Lambda transformer (1M invocations, 128 MB, 50 ms each) | ~$0.20 |
| Firehose ingestion (≈3 GB / day @ $0.029 / GB) | ~$2.60 |
| S3 PutObject + storage (parquet, ZSTD) | ~$1 |
| Glue MERGE job (2× G.1X for 5 min, every 15 min) | ~$8.40/day = ~$252/mo |
| EventBridge schedule | ~$0 (10K matches/mo on free tier) |
| **Total** | **~$256/mo** for one CMS table |

Each additional CMS table registered in `TABLE_PROJECTIONS` adds
the Lambda + Firehose + S3 + per-table-MERGE-execution cost — most
of the Glue cost is fixed (job startup), so adding a 2nd table
batched into the same MERGE invocation typically adds < $50/mo.

---

## 10. Troubleshooting

| Symptom | Probable cause | Fix |
|---|---|---|
| `cdk deploy` fails: `CmsIngestStack requires -c cms_vehicle_state_table_arn` | Forgot the ARN context flag | Re-run `make deploy-cms-ingest` with `CMS_TABLE_ARN=...`. |
| `enable_streams.py` exits 1 with "DynamoDB Streams are NOT enabled" | Source table never had streams turned on | Re-run with `--enable` after coordinating with the CMS operator. |
| Parquet appears in `cms-ingest/_errors/` instead of the table prefix | Lambda transformer emitted JSON the Firehose schema cannot parse | Compare the transformer output to [`firehose_schema.STREAM_RECORD_COLUMNS`](../platform-foundation/source/optional/cms_ingest/firehose_schema.py); fix the transformer. |
| MERGE job runs but Iceberg row count never increases | Window scope too narrow | Run the MERGE job manually with `--from-dt` / `--to-dt` covering a known-data window; check Iceberg snapshot history with `aws glue get-tables --database-name adp_staging_cms_ingest`. |
| MERGE job duration > 10 min | Backfill window or worker count too small | Bump `--from-dt` to a tighter window for the next run; or temporarily edit the stack's `number_of_workers` from `2` to `4` for backfill. |
| Athena `SELECT COUNT(*) FROM adp_staging_cms_ingest.vehicle_state` returns 0 | First MERGE has not run yet | Wait one 15-min slot, or invoke `aws glue start-job-run --job-name adp-staging-foundation-cms-ingest-merge` manually. |
| CloudTrail shows `AccessDenied` on `glue:GetTable` | Firehose role IAM lagged Glue table create | Re-deploy the stack — the synth-time `add_dependency(self.firehose_staging_table)` should already prevent this. |

---

## 11. Cross-references

* Spec: `.kiro/specs/2026-05-28-adp-ev-startup-foundation/spec.md`
  → "Optional CMS→ADP ingest module (Should-Have, opt-in)" section.
* Tasks: `.kiro/specs/2026-05-28-adp-ev-startup-foundation/tasks.md`
  → Group 5 task "Optional CMS→ADP ingest module".
* Tech notes: [`docs/tech.md`](tech.md)
  → "Kinesis Firehose — dynamic partitioning to S3 parquet" and
  "DynamoDB Streams — cross-account configuration".
* CDK stack: [`platform-foundation/stacks/optional/cms_ingest_stack.py`](../platform-foundation/stacks/optional/cms_ingest_stack.py).
* Runtime helpers: [`platform-foundation/source/optional/cms_ingest/`](../platform-foundation/source/optional/cms_ingest/).
* Verify (synth-time): `make verify-standalone STAGE=staging`
  asserts both flag-OFF and flag-ON contracts pass.
