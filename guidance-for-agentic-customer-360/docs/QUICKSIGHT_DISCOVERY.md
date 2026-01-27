# Amazon Quick Suite Assets Discovery Summary

## Overview
Discovered comprehensive Amazon Quick Suite dashboard infrastructure in the givenand-CMS account supporting the Customer 360 Analytics platform.

## Key Findings

### 1. OEM Business Overview Dashboard
**Dashboard ID**: `32328b83-2444-4f82-8625-2b7b317bb798`
**Status**: Production-ready, 25 published versions
**Last Updated**: December 2024

#### Dashboard Structure
- **2 Sheets**: Executive Overview + Customer 360
- **8 Datasets**: All connected to Athena via `cx-analytics-athena` data source
- **Source Analysis**: `308f81db-8083-4ace-9358-31baeab42e5c` (Executive Overview)

#### Key Metrics Displayed
1. **Revenue Metrics**
   - Total Subscriptions Sold
   - Monthly Sales
   - Total CLV
   - Revenue at Risk
   - Revenue Growth Rate
   - Average Revenue per Customer

2. **Customer Health Metrics**
   - Total Customers
   - Median Health Score
   - At-Risk Customers (count & percentage)
   - Retention Rate
   - Customers Retained

3. **Operational Metrics**
   - Total Vehicles
   - Open Cases
   - Cases Created
   - NPS Score

4. **Trend Analysis**
   - Month-over-month comparisons
   - Retention change tracking
   - Growth rate calculations

### 2. Datasets

All datasets use **DIRECT_QUERY** mode (no SPICE), querying Athena in real-time:

| Dataset ID | Source View | Purpose |
|------------|-------------|---------|
| `kpi-trends` | `kpi_trends_from_vehicles` | Time-series executive metrics |
| `operational-kpis` | TBD | Operational performance |
| `customer-health-scores` | `customer_health` | Individual health scores |
| `at-risk-revenue` | Derived view | Revenue exposure from churn |
| `top-revenue-stream` | CLV analysis | Revenue stream breakdown |
| `customer-360` | `customer_360` | Comprehensive customer profiles |
| `issue-categories` | Cases analysis | Support ticket trends |
| `revenue-breakdown` | CLV analysis | Revenue segmentation |

### 3. Data Source Configuration

**Data Source ID**: `cx-analytics-athena`
**Type**: Amazon Athena
**Connection Details**:
- Catalog: `AwsDataCatalog`
- Schema: `cx_analytics`
- Workgroup: `customer-360-workgroup` (assumed)

### 4. Additional Dashboards Found

| Dashboard ID | Name | Status |
|--------------|------|--------|
| `adoption-dashboard` | Product Adoption Dashboard | Published |
| `churn-dashboard` | Churn Prediction Dashboard | Published |
| `clv-dashboard` | Customer Lifetime Value Dashboard | Published |
| `cx-analytics-dashboard-pub` | CX Analytics Dashboard | Published |

### 5. Analyses Found

| Analysis ID | Name | Status |
|-------------|------|--------|
| `308f81db-8083-4ace-9358-31baeab42e5c` | Executive Overview | Success |
| `customer-360-analysis-v2` | Customer 360 Deep Dive | Success |
| `operational-kpis-analysis` | Operational Performance Dashboard | Success |
| `issue-categories-analysis` | Issue Categories Dashboard | Success |
| `fcr-kpi-test` | First Contact Resolution Rate KPI | Success |

## Architecture Insights

### Data Flow
```
Aurora PostgreSQL (CRM)
    ↓
S3 Data Lake (Parquet)
    ↓
Glue Catalog (cx_analytics)
    ↓
Athena Views (50+ views)
    ↓
Amazon Quick Suite Datasets (DIRECT_QUERY)
    ↓
Amazon Quick Suite Dashboards
```

### Key Design Decisions

1. **DIRECT_QUERY vs SPICE**
   - All datasets use DIRECT_QUERY
   - Real-time data without manual refresh
   - Lower storage costs (no SPICE charges)
   - Query costs passed to Athena

2. **Athena View Strategy**
   - Complex calculations in Athena views
   - Amazon Quick Suite datasets are thin wrappers
   - Easy to update logic without touching Amazon Quick Suite
   - Consistent metrics across all tools

3. **Dashboard Organization**
   - Executive-level: OEM Business Overview
   - Functional-level: Churn, CLV, Adoption dashboards
   - Operational-level: Issue Categories, Support Cases

## Migration Strategy for Guidance

### Phase 1: Export Assets ✅
- [x] Created export script: `export-quick-suite-assets.sh`
- [x] Documented dashboard structure
- [x] Identified all dependencies

### Phase 2: Template Creation (TODO)
- [ ] Convert dashboard definition to CloudFormation template
- [ ] Parameterize account IDs, regions, resource names
- [ ] Create dataset templates with variable substitution
- [ ] Document manual setup steps

### Phase 3: CDK Implementation (TODO)
- [ ] Create `quicksight-stack.ts` CDK construct
- [ ] Implement data source creation
- [ ] Implement dataset creation from Athena views
- [ ] Implement dashboard template import
- [ ] Add to phased deployment (Phase 4)

### Phase 4: Documentation (DONE)
- [x] Created `source/quicksight/README.md`
- [x] Updated main README with Amazon Quick Suite section
- [x] Updated DEPLOYMENT.md with setup instructions
- [x] Added cost estimates

## Recommendations

### For Guidance Package

1. **Include Dashboard Templates**
   - Export OEM Business Overview as template
   - Provide as optional deployment
   - Document customization points

2. **Simplify for Customers**
   - Provide manual setup guide (current approach)
   - Consider Amazon Quick Suite CLI/SDK automation
   - Include sample dashboard screenshots

3. **Cost Transparency**
   - Clearly mark Amazon Quick Suite as optional
   - Provide cost calculator
   - Explain DIRECT_QUERY vs SPICE tradeoffs

4. **Integration Points**
   - Dashboard depends on Athena views
   - Athena views depend on Glue catalog
   - Glue catalog depends on S3 data
   - Document this dependency chain

### For Production Use

1. **Performance Optimization**
   - Consider SPICE for frequently accessed datasets
   - Add partitioning to Athena tables
   - Optimize view queries for Amazon Quick Suite

2. **Security**
   - Row-level security for multi-tenant scenarios
   - Column-level security for PII
   - Embed URLs with proper authentication

3. **Monitoring**
   - CloudWatch metrics for query performance
   - Usage tracking per user/dashboard
   - Cost allocation tags

## Files Created

1. `deployment/scripts/export-quick-suite-assets.sh` - Export script
2. `source/quicksight/README.md` - Comprehensive Amazon Quick Suite documentation
3. `docs/QUICKSIGHT_DISCOVERY.md` - This file

## Next Steps

1. Run export script to capture current dashboard definitions
2. Create CloudFormation templates from exported JSON
3. Test deployment in clean account
4. Add to Makefile as optional phase
5. Create sample screenshots for documentation
6. Consider Amazon Quick Suite Q (natural language queries) integration

## Cost Analysis

### Current Production Setup
- **Amazon Quick Suite Users**: Unknown (need to query)
- **SPICE Usage**: 0 GB (DIRECT_QUERY only)
- **Athena Queries**: ~$5-20/month (estimated)
- **Total Amazon Quick Suite**: $9-180/month (depends on user count)

### Recommended for Guidance
- **Amazon Quick Suite**: Optional deployment
- **Estimated Cost**: $9/month (1 user) to $90/month (10 users)
- **Alternative**: Provide Athena queries only, let customers choose BI tool

## References

- Amazon Quick Suite API: https://docs.aws.amazon.com/quicksight/latest/APIReference/
- Dashboard Templates: https://docs.aws.amazon.com/quicksight/latest/user/working-with-templates.html
- DIRECT_QUERY: https://docs.aws.amazon.com/quicksight/latest/user/direct-query.html
