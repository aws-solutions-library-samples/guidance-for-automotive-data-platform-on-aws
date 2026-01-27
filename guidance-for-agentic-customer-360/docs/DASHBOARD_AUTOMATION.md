# Amazon Quick Suite - Fully Automated Dashboard Deployment

## Overview

We have **complete automation** for Amazon Quick Suite dashboard deployment:
- ✅ Data source creation
- ✅ Dataset creation (all 8 datasets)
- ✅ **Full dashboard deployment with ALL formatting preserved**
- ✅ **No analysis required** - dashboard created directly from definition

## Dashboard vs Analysis

**Analysis**: Editable workspace in Quick Suite (not required for deployment)
**Dashboard**: Published, read-only view (what we deploy)

Our approach:
- Export complete dashboard `Definition` (236KB JSON)
- Deploy dashboard **directly from definition**
- No intermediate analysis needed
- All formatting, visuals, and configurations preserved

## What We Captured

### Dashboard Export (236KB JSON)
The `oem-business-overview.json` contains the **complete dashboard definition**:

```json
{
  "Definition": {
    "DataSetIdentifierDeclarations": [...],
    "Sheets": [
      {
        "SheetId": "...",
        "Name": "Executive Overview",
        "Visuals": [
          {
            "KPIVisual": {
              "VisualId": "...",
              "Title": {
                "FormatText": {
                  "RichText": "<visual-title>\n  <inline font-size=\"14px\">Total Subscriptions Sold</inline>\n</visual-title>"
                }
              },
              "ChartConfiguration": {...},
              "ConditionalFormatting": {...}
            }
          }
        ]
      }
    ]
  }
}
```

### What's Preserved

**Visual Formatting**:
- ✅ Rich text titles with font sizes
- ✅ Colors and styles
- ✅ Chart types and configurations
- ✅ Conditional formatting rules
- ✅ Layout and positioning

**Data Connections**:
- ✅ Dataset references
- ✅ Field mappings
- ✅ Aggregations and calculations
- ✅ Filters and parameters

**Dashboard Structure**:
- ✅ Multiple sheets (Executive Overview, Customer 360)
- ✅ Visual hierarchy
- ✅ Interactions and drill-downs

## Automated Deployment

### Single Command
```bash
make phase4
```

### What Happens

**Step 1: Setup Data Source & Datasets** (`setup-quick-suite.sh`)
- Creates Athena data source
- Creates 8 datasets in DIRECT_QUERY mode
- Sets up permissions

**Step 2: Deploy Dashboard** (`deploy-dashboard.sh`)
- Reads template: `source/quick-suite/dashboards/oem-business-overview.json`
- Parameterizes account IDs and regions
- Creates dashboard via AWS CLI
- Preserves ALL formatting and configurations

### Script Details

```bash
#!/bin/bash
# deploy-dashboard.sh

# 1. Load template
TEMPLATE_FILE="source/quick-suite/dashboards/oem-business-overview.json"

# 2. Parameterize (replace account IDs)
cat "${TEMPLATE_FILE}" | \
  sed "s/022035076260/${ACCOUNT_ID}/g" | \
  sed "s/us-east-1/${REGION}/g" > temp.json

# 3. Extract definition
DEFINITION=$(cat temp.json | jq '.Definition')

# 4. Create dashboard
aws quicksight create-dashboard \
  --dashboard-id "oem-business-overview-${ACCOUNT_ID}" \
  --name "OEM Business Overview" \
  --definition "${DEFINITION}" \
  --permissions [...]
```

## Verification

After deployment:

```bash
# Check dashboard exists
aws quicksight describe-dashboard \
  --aws-account-id $(aws sts get-caller-identity --query Account --output text) \
  --dashboard-id oem-business-overview-$(aws sts get-caller-identity --query Account --output text)

# Access dashboard
open "https://us-east-1.quicksight.aws.amazon.com/sn/dashboards/oem-business-overview-$(aws sts get-caller-identity --query Account --output text)"
```

## Benefits

1. **Zero Manual Steps**: No console clicking required
2. **Formatting Preserved**: All colors, fonts, layouts intact
3. **Repeatable**: Deploy to multiple accounts/regions
4. **Version Controlled**: Dashboard definition in Git
5. **Fast**: 5-10 minutes vs 30-45 minutes manual

## Files

```
source/quick-suite/
├── dashboards/
│   └── oem-business-overview.json    (236KB - complete definition)
└── datasets/
    ├── kpi-trends.json
    ├── customer-health-scores.json
    ├── at-risk-revenue.json
    ├── revenue-breakdown.json
    ├── operational-kpis.json
    ├── issue-categories.json
    ├── customer-360.json
    └── top-revenue-stream.json

deployment/scripts/
├── setup-quick-suite.sh       (creates data source + datasets)
├── deploy-dashboard.sh        (deploys dashboard from definition)
└── export-quick-suite-assets.sh (exports from production)
```

## Updating the Dashboard

To capture changes from production:

```bash
cd deployment/scripts
./export-quick-suite-assets.sh
git add ../../source/quick-suite/
git commit -m "Update dashboard template"
```

## Troubleshooting

**Dashboard already exists**:
```bash
# Delete existing
aws quicksight delete-dashboard \
  --aws-account-id $(aws sts get-caller-identity --query Account --output text) \
  --dashboard-id oem-business-overview-$(aws sts get-caller-identity --query Account --output text)

# Redeploy
make phase4
```

**Datasets not found**:
- Ensure phase4 runs `setup-quick-suite.sh` first
- Check datasets exist: `aws quicksight list-data-sets`

**Permission denied**:
- Set correct username: `export QUICKSIGHT_USERNAME=your-user`
- Verify user exists in Quick Suite

## Summary

✅ **YES** - We have the complete dashboard source with ALL formatting
✅ **YES** - Dashboard deployment is fully automated
✅ **YES** - All visual styles, colors, fonts are preserved
✅ **YES** - Runs as part of `make phase4`

The OEM Business Overview dashboard with 20+ KPIs, 2 sheets, and complete formatting is now deployed automatically!
