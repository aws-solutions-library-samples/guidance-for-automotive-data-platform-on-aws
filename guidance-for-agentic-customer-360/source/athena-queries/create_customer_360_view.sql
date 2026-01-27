-- Customer 360 View for QuickSight
CREATE OR REPLACE VIEW customer_360_view AS
SELECT 
    customer_id,
    health_score,
    health_segment,
    clv,
    avg_satisfaction_score,
    total_cases,
    open_cases,
    total_vehicles,
    total_service_spend,
    total_service_appointments,
    battery_related_cases,
    last_interaction_date,
    avg_sentiment,
    first_purchase_date,
    last_purchase_date
FROM customer_health;
