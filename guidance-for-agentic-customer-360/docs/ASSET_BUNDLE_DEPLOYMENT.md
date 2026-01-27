# Amazon Quick Suite - Asset Bundle Export/Import for Cross-Account Deployment

## Answer: YES - Asset Bundles Support Cross-Account Deployment

### What Can Be Exported

**Asset Bundle APIs** (June 2023) support exporting and importing:
- ✅ **Dashboards**
- ✅ **Analyses**
- ✅ **Datasets** (including refresh schedules)
- ✅ **Data sources**
- ✅ **Themes**
- ✅ **VPC connections**
- ✅ **Folders** (October 2024 update)
- ✅ **Q Topics** (natural language query definitions)
- ❌ **Q Automations** (NOT supported yet)

### Export Formats

1. **Quick Suite JSON** (`.qs` zip file)
   - Native format
   - Can be imported back to Quick Suite
   - Preserves all configurations

2. **CloudFormation JSON**
   - Infrastructure as Code
   - Can be deployed via CloudFormation/CDK
   - Supports parameter overrides

### How It Works

#### 1. Export Assets from Source Account

```bash
# Start export job
aws quicksight start-asset-bundle-export-job \
  --aws-account-id 022035076260 \
  --asset-bundle-export-job-id export-cx360-$(date +%s) \
  --resource-arns '[
    "arn:aws:quicksight:us-east-1:022035076260:dashboard/32328b83-2444-4f82-8625-2b7b317bb798"
  ]' \
  --include-all-dependencies \
  --export-format QUICKSIGHT_JSON \
  --profile givenand-CMS \
  --region us-east-1

# Poll for completion
aws quicksight describe-asset-bundle-export-job \
  --aws-account-id 022035076260 \
  --asset-bundle-export-job-id export-cx360-TIMESTAMP \
  --profile givenand-CMS \
  --region us-east-1

# Download bundle (returns presigned S3 URL)
wget -O cx360-bundle.qs 'https://presigned-url-from-job-description...'
```

#### 2. Import to Target Account

```bash
# Upload bundle to S3 in target account
aws s3 cp cx360-bundle.qs s3://target-bucket/cx360-bundle.qs

# Start import job
aws quicksight start-asset-bundle-import-job \
  --aws-account-id TARGET_ACCOUNT_ID \
  --asset-bundle-import-job-id import-cx360-$(date +%s) \
  --asset-bundle-import-source '{
    "S3Uri": "s3://target-bucket/cx360-bundle.qs"
  }' \
  --override-parameters '{
    "DataSources": [{
      "DataSourceId": "cx-analytics-athena",
      "Name": "CX Analytics Athena"
    }]
  }' \
  --region us-east-1

# Poll for completion
aws quicksight describe-asset-bundle-import-job \
  --aws-account-id TARGET_ACCOUNT_ID \
  --asset-bundle-import-job-id import-cx360-TIMESTAMP \
  --region us-east-1
```

### Benefits

1. **Cross-Account Deployment**: Export from dev, import to prod
2. **Version Control**: Store `.qs` bundles in Git
3. **Backup & Restore**: Save dashboard configurations
4. **Multi-Region**: Deploy same dashboard to multiple regions
5. **Parameter Overrides**: Customize per environment

### What About Q Automations?

**Current Status**: ❌ **NOT supported in asset bundles**

**Evidence**:
- Asset bundle policy (March 2024) includes: dashboards, analyses, datasets, data sources, themes, VPC connections
- No mention of automations/topics in export/import APIs
- Q Automations are newer feature (2024)
- API support likely coming in future

### Workaround for Automations

Since automations can't be exported, we have two options:

#### Option 1: Document Manual Setup

Create `docs/AUTOMATIONS_SETUP.md` with step-by-step instructions for recreating automations in target account.

#### Option 2: Use Bedrock Agents Instead

Implement alerting logic in Bedrock agents (Phase 5):
- Fully automatable
- Version controlled
- More flexible than Q Automations
- Can be deployed via CDK

### Recommended Approach for Distribution

**Phase 4: Quick Suite Deployment**

1. **Export Asset Bundle** (one-time, from production):
```bash
cd deployment/scripts
./export-asset-bundle.sh
```

2. **Store Bundle in Git**:
```
source/quick-suite/
└── bundles/
    └── cx360-dashboard-bundle.qs
```

3. **Deploy to Target Account**:
```bash
make phase4  # Creates datasets + imports bundle
```

### Implementation

Create new script: `deployment/scripts/export-asset-bundle.sh`

```bash
#!/bin/bash
# Export complete Quick Suite asset bundle

ACCOUNT_ID=022035076260
REGION=us-east-1
PROFILE=givenand-CMS
JOB_ID="export-cx360-$(date +%s)"
OUTPUT_DIR="../../source/quick-suite/bundles"

# Start export
aws quicksight start-asset-bundle-export-job \
  --aws-account-id $ACCOUNT_ID \
  --asset-bundle-export-job-id $JOB_ID \
  --resource-arns '[
    "arn:aws:quicksight:us-east-1:022035076260:dashboard/32328b83-2444-4f82-8625-2b7b317bb798"
  ]' \
  --include-all-dependencies \
  --export-format QUICKSIGHT_JSON \
  --profile $PROFILE \
  --region $REGION

# Poll until complete
while true; do
  STATUS=$(aws quicksight describe-asset-bundle-export-job \
    --aws-account-id $ACCOUNT_ID \
    --asset-bundle-export-job-id $JOB_ID \
    --profile $PROFILE \
    --region $REGION \
    --query 'JobStatus' \
    --output text)
  
  if [ "$STATUS" = "SUCCESSFUL" ]; then
    break
  elif [ "$STATUS" = "FAILED" ]; then
    echo "Export failed"
    exit 1
  fi
  
  echo "Waiting for export... ($STATUS)"
  sleep 5
done

# Get download URL
DOWNLOAD_URL=$(aws quicksight describe-asset-bundle-export-job \
  --aws-account-id $ACCOUNT_ID \
  --asset-bundle-export-job-id $JOB_ID \
  --profile $PROFILE \
  --region $REGION \
  --query 'DownloadUrl' \
  --output text)

# Download bundle
mkdir -p $OUTPUT_DIR
wget -O $OUTPUT_DIR/cx360-dashboard-bundle.qs "$DOWNLOAD_URL"

echo "✅ Bundle exported: $OUTPUT_DIR/cx360-dashboard-bundle.qs"
```

### Summary

**Can we share Quick Suite assets cross-account?**
- ✅ **YES** - via Asset Bundle APIs
- ✅ Dashboards, datasets, data sources fully supported
- ✅ Export as `.qs` bundle or CloudFormation JSON
- ✅ Import with parameter overrides
- ❌ Q Automations NOT supported (yet)

**Recommendation**: 
1. Use asset bundles for dashboards (automated)
2. Document Q Automations setup (manual)
3. Use Bedrock agents for alerting (automated alternative)
