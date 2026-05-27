# CX Analytics Query Guide

## Overview
These queries answer: **"Where should we invest to maximize customer satisfaction, loyalty, and revenue?"**

## Quick Start

```sql
-- Set database
USE cx_analytics;

-- Verify data is loaded
SELECT COUNT(*) FROM customer_360 WHERE year='2024' AND month='12' AND day='31';
SELECT COUNT(*) FROM customer_health_metrics WHERE year='2024' AND month='12';
```

---

## 1. Customer Health Overview

### Business Question: "How healthy is our customer base?"

**Query**: Health Score Distribution
```sql
SELECT 
    CASE 
        WHEN health_score >= 70 THEN 'Healthy (70-100)'
        WHEN health_score >= 40 THEN 'At-Risk (40-69)'
        ELSE 'Critical (0-39)'
    END as risk_level,
    COUNT(*) as customer_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as percentage
FROM customer_health_metrics
WHERE year = '2024' AND month = '12'
GROUP BY 1;
```

**Expected Output**:
- 60% Healthy (300K customers)
- 25% At-Risk (125K customers)
- 15% Critical (75K customers)

**Action**: Focus retention efforts on At-Risk and Critical segments

---

## 2. Revenue at Risk Analysis

### Business Question: "How much revenue could we lose?"

**Query**: Total Revenue at Risk
```sql
SELECT 
    SUM(CASE WHEN h.health_score < 40 THEN c.lifetime_value ELSE 0 END) as revenue_at_risk,
    COUNT(CASE WHEN h.health_score < 40 THEN 1 END) as critical_customers
FROM customer_360 c
JOIN customer_health_metrics h ON c.customer_id = h.customer_id
WHERE c.year = '2024' AND c.month = '12' AND c.day = '31'
  AND h.year = '2024' AND h.month = '12';
```

**Action**: Prioritize investments that protect this revenue

---

## 3. Investment Priority Analysis

### Business Question: "Where should we invest first?"

**Query**: Dealer Performance Impact
```sql
-- Shows which dealers have the most at-risk customers
-- Helps prioritize dealer training/support investments
```

**Key Metrics**:
- Revenue at risk per dealer
- Average health score by dealer
- Critical customer count

**Action**: 
- Invest in training for poor-performing dealers
- Replicate best practices from excellent dealers

---

## 4. Root Cause Analysis

### Business Question: "What's driving poor health scores?"

**Query**: Health Score Component Analysis
```sql
-- Identifies if issues are:
-- - Recency (customers not engaging)
-- - Satisfaction (low NPS/CSAT)
-- - Support (too many tickets)
-- - Engagement (not using app/website)
```

**Action**: Target specific issues with focused initiatives

---

## 5. Service Center Impact

### Business Question: "Do wait times affect customer health?"

**Query**: Wait Time vs Health Score
```sql
-- Correlates service center wait times with health scores
-- Shows if operational improvements would help
```

**Expected Finding**: Longer wait times = lower health scores

**Action**: Invest in service center staffing/efficiency

---

## 6. Churn Prediction

### Business Question: "Who's about to churn?"

**Query**: Top 100 At-Risk Customers
```sql
-- Prioritized by lifetime value
-- Shows customers most likely to churn with highest revenue impact
```

**Action**: 
- Proactive outreach campaigns
- Special offers/incentives
- Executive escalation for high-value customers

---

## 7. Trend Analysis

### Business Question: "Are we improving or declining?"

**Query**: Month-over-Month Health Score Trends
```sql
SELECT 
    year,
    month,
    AVG(health_score) as avg_health_score,
    SUM(CASE WHEN health_score < 40 THEN 1 ELSE 0 END) as critical_count
FROM customer_health_metrics
WHERE year = '2024'
GROUP BY year, month
ORDER BY year, month;
```

**Action**: Track if investments are working

---

## 8. Executive Dashboard

### Business Question: "Give me the numbers"

**Query**: Overall CX Metrics
```sql
-- Single row with all key metrics:
-- - Total customers
-- - Average health score
-- - Revenue at risk
-- - Churn probability
```

**Use Case**: Weekly executive reporting

---

## Query Patterns

### Filter by Date
```sql
WHERE year = '2024' AND month = '12' AND day = '31'
```

### Filter by Risk Level
```sql
WHERE health_score < 40  -- Critical
WHERE health_score BETWEEN 40 AND 69  -- At-Risk
WHERE health_score >= 70  -- Healthy
```

### Join Customer 360 + Health Metrics
```sql
FROM customer_360 c
JOIN customer_health_metrics h ON c.customer_id = h.customer_id
WHERE c.year = '2024' AND c.month = '12' AND c.day = '31'
  AND h.year = '2024' AND h.month = '12'
```

---

## Performance Tips

1. **Always filter by partition keys** (year, month, day)
2. **Use LIMIT** for exploratory queries
3. **Create views** for frequently used queries
4. **Use CTAS** to materialize complex aggregations

---

## Sample Analysis Workflow

```sql
-- Step 1: Check overall health
SELECT AVG(health_score) FROM customer_health_metrics WHERE year='2024' AND month='12';

-- Step 2: Identify problem areas
SELECT * FROM [Revenue at Risk by Component query];

-- Step 3: Deep dive into top issue
SELECT * FROM [Dealer Performance query] WHERE performance_tier = 'Poor';

-- Step 4: Get actionable list
SELECT * FROM [Top 100 At-Risk Customers query];

-- Step 5: Track over time
SELECT * FROM [Month-over-Month Trends query];
```

---

## Next Steps

1. Run queries in Athena console
2. Export results to CSV for presentations
3. Create saved queries for regular reporting
4. Build dashboards (if using BI tool)
5. Set up alerts for critical thresholds
