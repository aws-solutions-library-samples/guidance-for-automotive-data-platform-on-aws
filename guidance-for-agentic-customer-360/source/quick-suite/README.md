# Amazon Quick Suite Dashboard Assets

This directory contains the Amazon Quick Suite dashboard definitions and dataset configurations for the Customer 360 Analytics platform.

## Dashboard Overview

### OEM Business Overview Dashboard
**Dashboard ID**: `32328b83-2444-4f82-8625-2b7b317bb798`

A comprehensive executive dashboard with two main sheets:

#### Sheet 1: Executive Overview
Key metrics and KPIs:
- **Total Subscriptions Sold** - OEM subscription revenue tracking
- **Monthly Sales** - Sales performance trends
- **Total Customers** - Customer base size
- **Total Vehicles** - Fleet size tracking
- **Median Health Score** - Overall customer health
- **Total CLV** - Customer lifetime value aggregate
- **Revenue at Risk** - Churn-related revenue exposure
- **NPS Score** - Net Promoter Score
- **At-Risk Customers** - Count and percentage
- **Revenue Growth Rate** - Month-over-month growth
- **Open Cases** - Support ticket volume
- **Retention Rate** - Customer retention metrics

#### Sheet 2: Customer 360
Detailed customer analytics and segmentation

## Datasets

The dashboard uses 8 primary datasets, all sourced from Athena views in the `cx_analytics` database:

### 1. KPI Trends (`kpi-trends`)
**Source**: `kpi_trends_from_vehicles` view
**Purpose**: Time-series metrics for executive dashboard

Key columns:
- `snapshot_month`, `month_date`, `month_label` - Time dimensions
- `total_customers`, `monthly_sales`, `total_vehicles` - Volume metrics
- `median_health_score`, `total_clv`, `revenue_at_risk` - Health metrics
- `avg_nps_score`, `nps_score` - Customer satisfaction
- `at_risk_customers`, `pct_at_risk_customers` - Churn indicators
- `revenue_growth_rate`, `avg_revenue_per_customer` - Financial metrics
- `open_cases`, `cases_created` - Support metrics
- `retention_rate`, `customers_retained`, `retention_change` - Retention metrics
- `subscriptions_sold` - Sales metrics

### 2. Operational KPIs (`operational-kpis`)
**Source**: Athena view
**Purpose**: Operational performance metrics

### 3. Customer Health Scores (`customer-health-scores`)
**Source**: `customer_health` table/view
**Purpose**: Individual customer health scoring

### 4. At-Risk Revenue (`at-risk-revenue`)
**Source**: Derived from churn prediction
**Purpose**: Revenue exposure from at-risk customers

### 5. Top Revenue Stream (`top-revenue-stream`)
**Source**: CLV analysis by revenue stream
**Purpose**: Revenue stream breakdown and analysis

### 6. Customer 360 (`customer-360`)
**Source**: `customer_360` table
**Purpose**: Comprehensive customer profiles

### 7. Issue Categories (`issue-categories`)
**Source**: Support cases analysis
**Purpose**: Support ticket categorization and trends

### 8. Revenue Breakdown (`revenue-breakdown`)
**Source**: CLV analysis
**Purpose**: Revenue segmentation by stream type

## Data Source

All datasets connect to:
- **Data Source**: `cx-analytics-athena`
- **Catalog**: `AwsDataCatalog`
- **Schema**: `cx_analytics`
- **Query Engine**: Amazon Athena

## Deployment

### Prerequisites
1. Athena views must be created (see `source/athena-queries/`)
2. Glue catalog tables must exist (see `deployment/cdk/lib/glue-catalog-stack.ts`)
3. Amazon Quick Suite must be enabled in the AWS account
4. Amazon Quick Suite service role must have permissions to access Athena and S3

### Export Existing Assets
```bash
cd deployment/scripts
./export-quick-suite-assets.sh
```

This exports:
- Dashboard definitions to `source/quicksight/dashboards/`
- Dataset configurations to `source/quicksight/datasets/`
- Analysis definitions to `source/quicksight/analyses/`

### Create New Dashboard (Manual Steps)

1. **Create Athena Data Source**
```bash
aws quicksight create-data-source \
  --aws-account-id <ACCOUNT_ID> \
  --data-source-id cx-analytics-athena \
  --name "CX Analytics Athena" \
  --type ATHENA \
  --data-source-parameters '{
    "AthenaParameters": {
      "WorkGroup": "customer-360-workgroup"
    }
  }' \
  --permissions '[{
    "Principal": "arn:aws:quicksight:us-east-1:<ACCOUNT_ID>:user/default/<USERNAME>",
    "Actions": ["quicksight:DescribeDataSource", "quicksight:PassDataSource"]
  }]'
```

2. **Create Datasets**
For each dataset, create using the Athena data source:
```bash
aws quicksight create-data-set \
  --aws-account-id <ACCOUNT_ID> \
  --data-set-id kpi-trends \
  --name "KPI Trends" \
  --physical-table-map '{
    "trends": {
      "RelationalTable": {
        "DataSourceArn": "arn:aws:quicksight:us-east-1:<ACCOUNT_ID>:datasource/cx-analytics-athena",
        "Catalog": "AwsDataCatalog",
        "Schema": "cx_analytics",
        "Name": "kpi_trends_from_vehicles",
        "InputColumns": [...]
      }
    }
  }' \
  --import-mode DIRECT_QUERY
```

3. **Create Analysis**
Use Amazon Quick Suite console to create analysis from datasets

4. **Publish Dashboard**
Publish analysis as dashboard for sharing

### Automated Deployment (Future)

We plan to create CDK constructs for Amazon Quick Suite deployment:
- `deployment/cdk/lib/quicksight-stack.ts` - Data sources, datasets, and dashboards
- Template-based approach for easy customization
- Parameterized for multi-account deployment

## Dashboard Features

### Interactivity
- Time range filters (monthly granularity)
- Drill-down capabilities
- Cross-filtering between visuals
- Export to CSV/PDF

### Refresh Schedule
- Datasets use DIRECT_QUERY mode (real-time)
- Athena views refresh as underlying data changes
- No manual refresh required

### Sharing
- Published dashboard can be shared with Amazon Quick Suite users
- Embed URLs available for web applications
- Email reports can be scheduled

## Cost Considerations

Amazon Quick Suite pricing (as of 2024):
- **Standard Edition**: $9/user/month (first user free)
- **Enterprise Edition**: $18/user/month
- **SPICE capacity**: $0.25/GB/month (not used - we use DIRECT_QUERY)
- **Athena queries**: $5/TB scanned

For this dashboard with DIRECT_QUERY:
- 10 users: ~$90-180/month (Amazon Quick Suite)
- Athena queries: ~$5-20/month (depends on usage)
- **Total**: ~$95-200/month

## Maintenance

### Adding New Metrics
1. Create Athena view with new metric
2. Update or create new dataset in Amazon Quick Suite
3. Add visual to analysis
4. Republish dashboard

### Troubleshooting
- **"Table not found"**: Verify Glue catalog tables exist
- **"Access denied"**: Check Amazon Quick Suite service role permissions
- **"Query timeout"**: Optimize Athena views or add partitioning
- **Slow performance**: Consider SPICE import for large datasets

## Related Documentation
- [Athena Views](../athena-queries/README.md)
- [Glue Catalog](../cdk/lib/glue-catalog-stack.ts)
- [Data Model](../../docs/DATA_MODEL_SPEC.md)
