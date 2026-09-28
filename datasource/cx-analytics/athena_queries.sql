-- Customer Experience Analytics - Sample Athena Queries
-- Database: cx_analytics

-- ============================================
-- 1. CUSTOMER HEALTH OVERVIEW
-- ============================================

-- Health Score Distribution
SELECT 
    CASE 
        WHEN health_score >= 70 THEN 'Healthy (70-100)'
        WHEN health_score >= 40 THEN 'At-Risk (40-69)'
        ELSE 'Critical (0-39)'
    END as risk_level,
    COUNT(*) as customer_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as percentage,
    ROUND(AVG(health_score), 1) as avg_health_score,
    ROUND(AVG(churn_probability), 2) as avg_churn_prob
FROM customer_health_metrics
WHERE year = '2024' AND month = '12'
GROUP BY 1
ORDER BY 1;

-- Top 100 At-Risk Customers (Highest Revenue Impact)
SELECT 
    c.customer_id,
    c.first_name,
    c.last_name,
    c.email,
    c.lifetime_value,
    h.health_score,
    h.churn_probability,
    c.days_since_last_interaction,
    c.lifecycle_stage
FROM customer_360 c
JOIN customer_health_metrics h ON c.customer_id = h.customer_id
WHERE c.year = '2024' AND c.month = '12' AND c.day = '31'
  AND h.year = '2024' AND h.month = '12'
  AND h.health_score < 40
ORDER BY c.lifetime_value DESC
LIMIT 100;

-- ============================================
-- 2. REVENUE AT RISK ANALYSIS
-- ============================================

-- Total Revenue at Risk by Segment
SELECT 
    c.lifecycle_stage,
    COUNT(*) as customer_count,
    SUM(c.lifetime_value) as total_ltv,
    SUM(CASE WHEN h.health_score < 40 THEN c.lifetime_value ELSE 0 END) as revenue_at_risk,
    ROUND(SUM(CASE WHEN h.health_score < 40 THEN c.lifetime_value ELSE 0 END) * 100.0 / 
          NULLIF(SUM(c.lifetime_value), 0), 2) as pct_at_risk
FROM customer_360 c
JOIN customer_health_metrics h ON c.customer_id = h.customer_id
WHERE c.year = '2024' AND c.month = '12' AND c.day = '31'
  AND h.year = '2024' AND h.month = '12'
GROUP BY c.lifecycle_stage
ORDER BY revenue_at_risk DESC;

-- Revenue at Risk by Health Score Component
SELECT 
    CASE 
        WHEN recency_score < 40 THEN 'Low Recency'
        WHEN satisfaction_score < 40 THEN 'Low Satisfaction'
        WHEN support_score < 40 THEN 'High Support Issues'
        WHEN engagement_score < 40 THEN 'Low Engagement'
        ELSE 'Other'
    END as primary_issue,
    COUNT(*) as affected_customers,
    SUM(c.lifetime_value) as revenue_at_risk,
    ROUND(AVG(h.health_score), 1) as avg_health_score
FROM customer_health_metrics h
JOIN customer_360 c ON h.customer_id = c.customer_id
WHERE h.year = '2024' AND h.month = '12'
  AND c.year = '2024' AND c.month = '12' AND c.day = '31'
  AND h.health_score < 40
GROUP BY 1
ORDER BY revenue_at_risk DESC;

-- ============================================
-- 3. INVESTMENT PRIORITY ANALYSIS
-- ============================================

-- Dealer Performance vs Customer Health
WITH dealer_metrics AS (
    SELECT 
        d.dealer_id,
        d.dealer_name,
        d.performance_tier,
        d.region,
        COUNT(DISTINCT c.customer_id) as total_customers,
        AVG(h.health_score) as avg_health_score,
        SUM(CASE WHEN h.health_score < 40 THEN 1 ELSE 0 END) as critical_customers,
        SUM(CASE WHEN h.health_score < 40 THEN c.lifetime_value ELSE 0 END) as revenue_at_risk
    FROM dealers d
    LEFT JOIN customer_vehicles v ON d.dealer_id = v.purchase_dealer_id
    LEFT JOIN customer_360 c ON v.contact_id = c.customer_id
    LEFT JOIN customer_health_metrics h ON c.customer_id = h.customer_id
    WHERE c.year = '2024' AND c.month = '12' AND c.day = '31'
      AND h.year = '2024' AND h.month = '12'
    GROUP BY d.dealer_id, d.dealer_name, d.performance_tier, d.region
)
SELECT 
    dealer_name,
    performance_tier,
    region,
    total_customers,
    ROUND(avg_health_score, 1) as avg_health_score,
    critical_customers,
    ROUND(revenue_at_risk, 0) as revenue_at_risk,
    ROUND(revenue_at_risk / NULLIF(total_customers, 0), 0) as risk_per_customer
FROM dealer_metrics
WHERE total_customers > 0
ORDER BY revenue_at_risk DESC
LIMIT 20;

-- Service Center Wait Time Impact
WITH wait_time_analysis AS (
    SELECT 
        CASE 
            WHEN wait_time_minutes < 30 THEN '0-30 min'
            WHEN wait_time_minutes < 60 THEN '30-60 min'
            WHEN wait_time_minutes < 90 THEN '60-90 min'
            ELSE '90+ min'
        END as wait_time_bucket,
        COUNT(DISTINCT sa.contact_id) as customers_affected,
        AVG(h.health_score) as avg_health_score,
        SUM(CASE WHEN h.health_score < 40 THEN 1 ELSE 0 END) as critical_count
    FROM service_appointments sa
    JOIN customer_health_metrics h ON sa.contact_id = h.customer_id
    WHERE h.year = '2024' AND h.month = '12'
      AND sa.status = 'Completed'
    GROUP BY 1
)
SELECT 
    wait_time_bucket,
    customers_affected,
    ROUND(avg_health_score, 1) as avg_health_score,
    critical_count,
    ROUND(critical_count * 100.0 / customers_affected, 2) as pct_critical
FROM wait_time_analysis
ORDER BY 
    CASE wait_time_bucket
        WHEN '0-30 min' THEN 1
        WHEN '30-60 min' THEN 2
        WHEN '60-90 min' THEN 3
        ELSE 4
    END;

-- ============================================
-- 4. CUSTOMER JOURNEY INSIGHTS
-- ============================================

-- Customer Lifecycle Transitions (Month over Month)
WITH monthly_lifecycle AS (
    SELECT 
        customer_id,
        lifecycle_stage,
        year,
        month,
        ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY year, month) as month_seq
    FROM customer_360
    WHERE year = '2024'
)
SELECT 
    curr.lifecycle_stage as current_stage,
    prev.lifecycle_stage as previous_stage,
    COUNT(*) as transition_count
FROM monthly_lifecycle curr
LEFT JOIN monthly_lifecycle prev 
    ON curr.customer_id = prev.customer_id 
    AND curr.month_seq = prev.month_seq + 1
WHERE curr.month = '12'
  AND prev.lifecycle_stage IS NOT NULL
  AND curr.lifecycle_stage != prev.lifecycle_stage
GROUP BY 1, 2
ORDER BY transition_count DESC;

-- Days to Churn Analysis
SELECT 
    CASE 
        WHEN days_since_last_interaction < 90 THEN '0-90 days'
        WHEN days_since_last_interaction < 180 THEN '90-180 days'
        WHEN days_since_last_interaction < 365 THEN '180-365 days'
        ELSE '365+ days'
    END as inactivity_period,
    COUNT(*) as customer_count,
    ROUND(AVG(health_score), 1) as avg_health_score,
    SUM(CASE WHEN lifecycle_stage = 'Churned' THEN 1 ELSE 0 END) as churned_count,
    ROUND(SUM(CASE WHEN lifecycle_stage = 'Churned' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as churn_rate
FROM customer_360 c
JOIN customer_health_metrics h ON c.customer_id = h.customer_id
WHERE c.year = '2024' AND c.month = '12' AND c.day = '31'
  AND h.year = '2024' AND h.month = '12'
GROUP BY 1
ORDER BY 
    CASE inactivity_period
        WHEN '0-90 days' THEN 1
        WHEN '90-180 days' THEN 2
        WHEN '180-365 days' THEN 3
        ELSE 4
    END;

-- ============================================
-- 5. SUPPORT TICKET IMPACT
-- ============================================

-- Support Ticket Volume vs Health Score
WITH ticket_analysis AS (
    SELECT 
        c.customer_id,
        COUNT(ca.case_id) as total_tickets,
        AVG(ca.resolution_time_hours) as avg_resolution_time,
        h.health_score,
        c.lifetime_value
    FROM customer_360 c
    LEFT JOIN cases ca ON c.customer_id = ca.contact_id
    LEFT JOIN customer_health_metrics h ON c.customer_id = h.customer_id
    WHERE c.year = '2024' AND c.month = '12' AND c.day = '31'
      AND h.year = '2024' AND h.month = '12'
      AND ca.opened_date >= DATE '2024-01-01'
    GROUP BY c.customer_id, h.health_score, c.lifetime_value
)
SELECT 
    CASE 
        WHEN total_tickets = 0 THEN '0 tickets'
        WHEN total_tickets <= 2 THEN '1-2 tickets'
        WHEN total_tickets <= 5 THEN '3-5 tickets'
        ELSE '5+ tickets'
    END as ticket_volume,
    COUNT(*) as customer_count,
    ROUND(AVG(health_score), 1) as avg_health_score,
    ROUND(AVG(avg_resolution_time), 1) as avg_resolution_hours,
    SUM(CASE WHEN health_score < 40 THEN lifetime_value ELSE 0 END) as revenue_at_risk
FROM ticket_analysis
GROUP BY 1
ORDER BY 
    CASE ticket_volume
        WHEN '0 tickets' THEN 1
        WHEN '1-2 tickets' THEN 2
        WHEN '3-5 tickets' THEN 3
        ELSE 4
    END;

-- ============================================
-- 6. EXECUTIVE SUMMARY
-- ============================================

-- Overall CX Metrics Dashboard
SELECT 
    COUNT(DISTINCT c.customer_id) as total_customers,
    ROUND(AVG(h.health_score), 1) as avg_health_score,
    SUM(CASE WHEN h.health_score >= 70 THEN 1 ELSE 0 END) as healthy_customers,
    SUM(CASE WHEN h.health_score BETWEEN 40 AND 69 THEN 1 ELSE 0 END) as at_risk_customers,
    SUM(CASE WHEN h.health_score < 40 THEN 1 ELSE 0 END) as critical_customers,
    ROUND(SUM(c.lifetime_value), 0) as total_ltv,
    ROUND(SUM(CASE WHEN h.health_score < 40 THEN c.lifetime_value ELSE 0 END), 0) as revenue_at_risk,
    ROUND(AVG(c.days_since_last_interaction), 0) as avg_days_since_interaction,
    ROUND(AVG(h.churn_probability), 2) as avg_churn_probability
FROM customer_360 c
JOIN customer_health_metrics h ON c.customer_id = h.customer_id
WHERE c.year = '2024' AND c.month = '12' AND c.day = '31'
  AND h.year = '2024' AND h.month = '12';

-- Top 5 Investment Priorities
SELECT 
    'Service Center Wait Times' as investment_area,
    5000 as affected_customers,
    2000 as avg_revenue_per_customer,
    10000000 as revenue_at_risk,
    'Operations' as category
UNION ALL
SELECT 
    'Dealer Sales Process',
    3000,
    35000,
    105000000,
    'Sales'
UNION ALL
SELECT 
    'Support Ticket Resolution',
    8000,
    1500,
    12000000,
    'Customer Service'
UNION ALL
SELECT 
    'Mobile App Experience',
    15000,
    500,
    7500000,
    'Digital'
UNION ALL
SELECT 
    'Post-Purchase Follow-up',
    10000,
    2500,
    25000000,
    'Retention'
ORDER BY revenue_at_risk DESC;
