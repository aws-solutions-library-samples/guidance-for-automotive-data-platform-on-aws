-- Revenue Breakdown View for QuickSight
CREATE OR REPLACE VIEW revenue_breakdown AS
SELECT 
    revenue_stream,
    revenue
FROM revenue_streams;
