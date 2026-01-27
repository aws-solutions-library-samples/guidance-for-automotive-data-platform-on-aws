# Customer 360 Analytics Metadata Guide

This guide provides comprehensive documentation of the Customer 360 data platform schema, KPIs, metrics, and analytical views.

---

## Data Architecture Overview

### Data Lake Structure

```
s3://automotive-cx-data-lake/
├── raw/                          # Raw ingestion data
│   ├── customer-profiles/        # Customer master data
│   ├── interactions/             # Customer interactions
│   ├── service-records/          # Service appointments
│   └── product-issues/           # Issue tracking
├── processed/                    # Cleaned and transformed
│   ├── customer-360/             # Unified customer view
│   ├── health-scores/            # Calculated health metrics
│   └── churn-predictions/        # ML model outputs
└── analytics/                    # Aggregated for reporting
    ├── kpi-trends/               # Time-series KPIs
    └── customer-segments/        # Segmentation analysis
```

### Glue Database: `cx_analytics`

**Purpose:** Central catalog for all Customer 360 analytical tables and views

**Tables:**
- `customer_profiles` - Master customer data
- `customer_health_scores` - Current health metrics
- `customer_interactions` - Interaction history
- `service_appointments` - Service records
- `product_issues` - Issue tracking
- `churn_predictions` - ML predictions

---

## Core Metrics and KPIs

### 1. Customer Health Score

**Definition:** Composite metric (0-100) indicating customer engagement, satisfaction, and churn risk

**Calculation:**
```sql
health_score = (
    engagement_score * 0.30 +
    satisfaction_score * 0.25 +
    product_usage_score * 0.20 +
    support_interaction_score * 0.15 +
    payment_history_score * 0.10
)
```

**Components:**

#### Engagement Score (0-100)
- App usage frequency (daily, weekly, monthly)
- Feature adoption rate
- Community participation
- Response to communications

#### Satisfaction Score (0-100)
- Service satisfaction ratings (1-5 scale, normalized)
- NPS score contribution
- Complaint resolution satisfaction
- Product review sentiment

#### Product Usage Score (0-100)
- Active feature usage
- Time spent in product
- Advanced feature adoption
- Integration usage

#### Support Interaction Score (0-100)
- Case volume (inverse - fewer is better)
- Case resolution time
- Escalation frequency (inverse)
- Self-service usage

#### Payment History Score (0-100)
- On-time payment rate
- Payment method reliability
- Billing dispute frequency (inverse)

**Interpretation:**
- **80-100 (Thriving)**: Highly engaged, low churn risk
- **60-79 (Healthy)**: Stable, normal engagement
- **40-59 (At Risk)**: Declining engagement, intervention needed
- **20-39 (Needs Attention)**: High churn risk, immediate action
- **0-19 (Critical)**: Imminent churn, executive escalation

**Update Frequency:** Daily

---

### 2. Churn Probability

**Definition:** ML-predicted likelihood (0-100%) that customer will churn within 90 days

**Model:** Random Forest Classifier trained on historical churn events

**Features:**
- Health score trend (30-day, 60-day, 90-day)
- Open case count and age
- Service appointment frequency
- Satisfaction score trend
- Revenue and contract value
- Product usage patterns
- Support interaction patterns

**Thresholds:**
- **>70%**: Critical - immediate intervention
- **50-70%**: High risk - proactive outreach
- **30-50%**: Moderate risk - monitoring
- **<30%**: Low risk - standard engagement

**Update Frequency:** Weekly (Monday 2 AM)

---

### 3. Revenue at Risk

**Definition:** Potential revenue loss if at-risk customers churn

**Calculation:**
```sql
revenue_at_risk = 
    customer_lifetime_value * 
    churn_probability * 
    remaining_contract_months / 12
```

**Aggregations:**
- By customer segment
- By root cause category
- By account manager
- By product line

**Use Cases:**
- Prioritize intervention efforts
- Forecast revenue impact
- Measure retention program ROI

---

### 4. Customer Lifetime Value (CLV)

**Definition:** Predicted total revenue from customer over entire relationship

**Calculation:**
```sql
CLV = (
    avg_monthly_revenue * 
    expected_lifetime_months * 
    gross_margin_pct
) - acquisition_cost
```

**Segments:**
- **High Value**: CLV >$10,000
- **Medium Value**: CLV $5,000-$10,000
- **Standard Value**: CLV <$5,000

**Update Frequency:** Monthly

---

### 5. Net Promoter Score (NPS)

**Definition:** Customer loyalty metric based on likelihood to recommend

**Question:** "How likely are you to recommend [Product] to a friend or colleague?" (0-10 scale)

**Calculation:**
```
NPS = % Promoters (9-10) - % Detractors (0-6)
```

**Segments:**
- **Promoters** (9-10): Loyal enthusiasts
- **Passives** (7-8): Satisfied but unenthusiastic
- **Detractors** (0-6): Unhappy customers

**Targets:**
- World-class: NPS >70
- Excellent: NPS 50-70
- Good: NPS 30-50
- Needs Improvement: NPS <30

---

## Analytical Views

### View: `customer_360_view`

**Purpose:** Unified customer view combining all data sources

**Schema:**
```sql
CREATE VIEW customer_360_view AS
SELECT 
    cp.customer_id,
    cp.customer_name,
    cp.email,
    cp.phone,
    cp.account_created_date,
    cp.customer_segment,
    
    -- Health Metrics
    chs.health_score,
    chs.health_segment,
    chs.health_score_trend_30d,
    chs.days_at_risk,
    
    -- Financial Metrics
    cp.total_revenue,
    cp.avg_monthly_revenue,
    cp.customer_lifetime_value,
    chs.revenue_at_risk,
    
    -- Engagement Metrics
    cp.last_login_date,
    cp.total_logins_90d,
    cp.feature_adoption_rate,
    
    -- Support Metrics
    chs.total_cases,
    chs.open_cases,
    chs.avg_case_resolution_days,
    chs.total_service_appointments,
    
    -- Satisfaction Metrics
    chs.avg_satisfaction_score,
    chs.nps_score,
    chs.last_survey_date,
    
    -- Risk Indicators
    chs.churn_probability,
    chs.primary_root_cause,
    chs.contributing_factor,
    chs.severity
    
FROM customer_profiles cp
JOIN customer_health_scores chs 
    ON cp.customer_id = chs.customer_id
WHERE cp.status = 'active';
```

---

### View: `at_risk_customers`

**Purpose:** Customers requiring immediate attention

**Schema:**
```sql
CREATE VIEW at_risk_customers AS
SELECT 
    customer_id,
    customer_name,
    health_score,
    churn_probability,
    revenue_at_risk,
    days_at_risk,
    primary_root_cause,
    open_cases,
    last_interaction_date,
    assigned_csm
FROM customer_360_view
WHERE 
    health_score < 60 
    OR churn_probability > 0.5
    OR open_cases > 0
ORDER BY 
    revenue_at_risk DESC,
    health_score ASC;
```

---

### View: `kpi_trends`

**Purpose:** Time-series KPI tracking for dashboards

**Schema:**
```sql
CREATE VIEW kpi_trends AS
SELECT 
    date_trunc('day', metric_date) as metric_date,
    
    -- Customer Counts
    COUNT(DISTINCT customer_id) as total_customers,
    COUNT(DISTINCT CASE WHEN health_segment = 'Critical' THEN customer_id END) as critical_customers,
    COUNT(DISTINCT CASE WHEN health_segment = 'Needs Attention' THEN customer_id END) as needs_attention_customers,
    COUNT(DISTINCT CASE WHEN health_segment = 'At Risk' THEN customer_id END) as at_risk_customers,
    
    -- Health Metrics
    AVG(health_score) as avg_health_score,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY health_score) as median_health_score,
    
    -- Financial Metrics
    SUM(revenue_at_risk) as total_revenue_at_risk,
    AVG(customer_lifetime_value) as avg_clv,
    
    -- Support Metrics
    SUM(open_cases) as total_open_cases,
    AVG(avg_case_resolution_days) as avg_resolution_time,
    
    -- Satisfaction Metrics
    AVG(avg_satisfaction_score) as avg_satisfaction,
    AVG(nps_score) as avg_nps

FROM customer_health_scores
GROUP BY date_trunc('day', metric_date)
ORDER BY metric_date DESC;
```

---

## Data Quality Rules

### Customer Profiles
- `customer_id`: NOT NULL, UNIQUE
- `email`: Valid email format, UNIQUE
- `account_created_date`: NOT NULL, <= CURRENT_DATE
- `customer_segment`: IN ('Enterprise', 'Mid-Market', 'SMB', 'Consumer')

### Health Scores
- `health_score`: BETWEEN 0 AND 100
- `churn_probability`: BETWEEN 0 AND 1
- `revenue_at_risk`: >= 0
- `days_at_risk`: >= 0

### Interactions
- `interaction_date`: NOT NULL, <= CURRENT_DATE
- `interaction_type`: IN ('call', 'email', 'chat', 'service', 'app')
- `sentiment_score`: BETWEEN -1 AND 1

---

## Common Queries

### Find High-Value At-Risk Customers
```sql
SELECT 
    customer_id,
    customer_name,
    health_score,
    customer_lifetime_value,
    revenue_at_risk,
    primary_root_cause
FROM customer_360_view
WHERE 
    health_score < 60
    AND customer_lifetime_value > 10000
ORDER BY revenue_at_risk DESC
LIMIT 50;
```

### Calculate Churn Rate by Segment
```sql
SELECT 
    customer_segment,
    COUNT(*) as total_customers,
    SUM(CASE WHEN churned = true THEN 1 ELSE 0 END) as churned_customers,
    ROUND(100.0 * SUM(CASE WHEN churned = true THEN 1 ELSE 0 END) / COUNT(*), 2) as churn_rate_pct
FROM customer_profiles
WHERE account_created_date >= CURRENT_DATE - INTERVAL '12' MONTH
GROUP BY customer_segment
ORDER BY churn_rate_pct DESC;
```

### Identify Trending Issues
```sql
SELECT 
    primary_root_cause,
    COUNT(DISTINCT customer_id) as affected_customers,
    SUM(revenue_at_risk) as total_revenue_at_risk,
    AVG(health_score) as avg_health_score
FROM customer_health_scores
WHERE 
    health_score < 60
    AND metric_date >= CURRENT_DATE - INTERVAL '30' DAY
GROUP BY primary_root_cause
ORDER BY affected_customers DESC;
```

---

## Dashboard KPIs

### Executive Dashboard
1. **Total Active Customers** - COUNT(DISTINCT customer_id)
2. **Average Health Score** - AVG(health_score)
3. **Revenue at Risk** - SUM(revenue_at_risk)
4. **Churn Rate (30d)** - Churned customers / Total customers
5. **NPS Score** - (% Promoters - % Detractors)

### Customer Success Dashboard
1. **Critical Customers** - COUNT WHERE health_score < 20
2. **Needs Attention** - COUNT WHERE health_score 20-39
3. **At Risk** - COUNT WHERE health_score 40-59
4. **Open Cases by Age** - Histogram of case age
5. **Top Root Causes** - Bar chart of primary_root_cause

### Operational Dashboard
1. **Case Volume Trend** - Line chart of daily case count
2. **Average Resolution Time** - Trend over 90 days
3. **Service Appointment Volume** - By location and type
4. **Customer Satisfaction** - Trend by interaction type
5. **Product Issue Categories** - Pareto chart

---

## Data Refresh Schedule

| Dataset | Frequency | Time (UTC) | Latency |
|---------|-----------|------------|---------|
| Customer Profiles | Daily | 01:00 | 1 hour |
| Health Scores | Daily | 02:00 | 2 hours |
| Churn Predictions | Weekly | Monday 02:00 | 3 hours |
| Interactions | Hourly | :15 | 15 min |
| Service Records | Daily | 03:00 | 1 hour |
| KPI Aggregations | Hourly | :30 | 30 min |

---

## Data Retention Policy

- **Raw Data**: 7 years (compliance requirement)
- **Processed Data**: 3 years (analytical needs)
- **Aggregated KPIs**: 5 years (trending analysis)
- **ML Model Predictions**: 1 year (model retraining)
- **Audit Logs**: 7 years (compliance requirement)

---

## Access Control

### Data Classification
- **Public**: Aggregated KPIs, anonymized trends
- **Internal**: Customer names, contact info, health scores
- **Confidential**: Payment info, detailed interaction logs
- **Restricted**: PII, compliance data

### Role-Based Access
- **Executives**: All dashboards, aggregated views only
- **Customer Success**: Customer 360 view, intervention tools
- **Support**: Case data, service records, limited customer info
- **Analytics**: All data for analysis, no direct customer contact
- **Data Engineers**: Full access for pipeline maintenance

---

## Glossary

**Churn**: Customer cancels service or stops using product for 90+ days

**Health Score**: Composite metric indicating customer engagement and satisfaction

**Root Cause**: Primary reason for customer dissatisfaction or churn risk

**Revenue at Risk**: Potential revenue loss from at-risk customers

**Customer Lifetime Value (CLV)**: Total predicted revenue from customer

**Net Promoter Score (NPS)**: Loyalty metric based on recommendation likelihood

**Engagement Score**: Measure of customer interaction with product/service

**At-Risk Period**: Number of days customer has been below healthy threshold
