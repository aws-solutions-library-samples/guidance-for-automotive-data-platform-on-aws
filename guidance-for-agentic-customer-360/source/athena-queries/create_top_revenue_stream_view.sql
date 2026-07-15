-- Top Revenue Stream View for QuickSight
CREATE OR REPLACE VIEW top_revenue_stream AS
SELECT 
    revenue_stream,
    current_revenue,
    previous_revenue,
    revenue_change,
    growth_rate
FROM revenue_trends;
