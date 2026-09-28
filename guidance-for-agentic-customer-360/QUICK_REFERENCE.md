# Customer 360 Platform - Quick Reference

## 🎯 Quick Access

### QuickSight Dashboard
```
https://<REGION>.quicksight.aws.amazon.com/sn/dashboards/customer-360-dashboard
```

### Key Resources
- **Region**: us-east-1 (default, configurable)
- **S3 Bucket**: `automotive-cx-data-lake-<ACCOUNT_ID>`
- **Glue Database**: `cx_analytics`
- **Athena Workgroup**: `cx-analytics-workgroup`
- **Bedrock Agent**: Created during deployment (customer-360-analyzer)

---

## 📊 Datasets (8 Total)

| Dataset | Rows | Description |
|---------|------|-------------|
| kpi-trends | 12 | Monthly KPI snapshots |
| operational-kpis | 12 | Service quality metrics |
| customer-health-scores | 500K | Customer health analysis |
| at-risk-revenue | 48 | At-risk revenue by type/month |
| customer-360 | 500K | Complete customer profiles |
| issue-categories | 12 | Issue breakdown by month |
| revenue-breakdown | 5 | Revenue by stream |
| top-revenue-stream | 5 | Revenue trends |

---

## 🔍 Sample Queries

### Get Monthly KPIs
```sql
SELECT 
    month_label,
    total_customers,
    median_health_score,
    total_clv,
    at_risk_customers,
    revenue_at_risk
FROM kpi_trends
ORDER BY month_date DESC
LIMIT 12;
```

### Find At-Risk Customers
```sql
SELECT 
    customer_id,
    health_score,
    health_segment,
    clv,
    total_cases,
    open_cases
FROM customer_360_view
WHERE health_segment = 'At Risk'
ORDER BY clv DESC
LIMIT 100;
```

### Revenue Breakdown
```sql
SELECT 
    revenue_stream,
    current_revenue,
    previous_revenue,
    revenue_change,
    growth_rate
FROM top_revenue_stream
ORDER BY current_revenue DESC;
```

### Operational Metrics
```sql
SELECT 
    month_label,
    first_contact_resolution_rate,
    avg_case_resolution_days,
    service_wait_days,
    operational_health_score
FROM operational_kpis
ORDER BY month_date DESC
LIMIT 6;
```

---

## 🛠️ Common Tasks

### Regenerate Data
```bash
cd guidance-for-agentic-customer-360
make phase3
```

### Run Glue Crawler
```bash
aws glue start-crawler \
  --name cx-analytics-crawler \
  --region us-east-1
```

### Check Crawler Status
```bash
aws glue get-crawler \
  --name cx-analytics-crawler \
  --region us-east-1 \
  --query 'Crawler.{State:State,LastCrawl:LastCrawl.Status}'
```

### List All Tables
```bash
aws glue get-tables \
  --database-name cx_analytics \
  --region us-east-1 \
  --query 'TableList[].Name'
```

### Update QuickSight Datasets
```bash
python3 deployment/scripts/update_quicksight_datasets.py
```

### Check Dashboard Status
```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws quicksight describe-dashboard \
  --aws-account-id $ACCOUNT_ID \
  --dashboard-id customer-360-dashboard \
  --region us-east-1 \
  --query 'Dashboard.Version.Status'
```

---

## 📈 Key Metrics

### Current Data
- **Total Customers**: 500,000
- **Total Interactions**: 1.4M
- **Total Service Records**: 900K
- **Total Cases**: 500K
- **Monthly Snapshots**: 12 months
- **Revenue Streams**: 5

### Health Segments
- **Healthy**: ~40%
- **Moderate**: ~25%
- **At Risk**: ~35%

### Average Metrics
- **Health Score**: ~60
- **CLV**: ~$4,000
- **Satisfaction**: ~3.5/5
- **Cases per Customer**: ~1

---

## 🔐 Permissions

### Lake Formation
Permissions granted to:
- Deploying IAM user/role
- Glue ETL role (created by CDK)
- QuickSight service role

### QuickSight
- Data source: `cx-analytics-athena`
- All datasets: DIRECT_QUERY mode
- Dashboard: Published (version 1)

---

## 🚨 Troubleshooting

### Dashboard Not Loading
1. Check dataset status:
   ```bash
   ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
   aws quicksight list-data-sets \
     --aws-account-id $ACCOUNT_ID \
     --region us-east-1
   ```

2. Verify Athena views:
   ```bash
   aws glue get-tables \
     --database-name cx_analytics \
     --region us-east-1 \
     --query 'TableList[?TableType==`VIRTUAL_VIEW`].Name'
   ```

### No Data in Views
1. Check if tables exist:
   ```bash
   aws glue get-tables \
     --database-name cx_analytics \
     --region us-east-1
   ```

2. Run crawler:
   ```bash
   aws glue start-crawler --name cx-analytics-crawler --region us-east-1
   ```

3. Verify S3 data:
   ```bash
   ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
   aws s3 ls s3://automotive-cx-data-lake-${ACCOUNT_ID}/raw/ --recursive
   ```

### Lake Formation Errors
Grant permissions:
```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
CALLER_ARN=$(aws sts get-caller-identity --query Arn --output text)
aws lakeformation grant-permissions \
  --principal DataLakePrincipalIdentifier=$CALLER_ARN \
  --resource '{"Table":{"DatabaseName":"cx_analytics","TableWildcard":{}}}' \
  --permissions "SELECT" \
  --region us-east-1
```

---

## 📞 Support

### Documentation
- Full deployment: `DEPLOYMENT_CHECKLIST.md`
- README: `README.md`

### AWS Console Links
- [Athena Query Editor](https://console.aws.amazon.com/athena/home#/query-editor)
- [Glue Catalog](https://console.aws.amazon.com/glue/home#/v2/data-catalog/databases)
- [S3 Console](https://s3.console.aws.amazon.com/s3/buckets)
- [QuickSight](https://quicksight.aws.amazon.com/)
- [Bedrock Agents](https://console.aws.amazon.com/bedrock/home#/agents)

---

**Last Updated**: February 2026
**Status**: ✅ Operational
