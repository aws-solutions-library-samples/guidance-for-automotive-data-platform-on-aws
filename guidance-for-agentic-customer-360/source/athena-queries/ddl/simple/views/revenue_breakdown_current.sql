-- View: revenue_breakdown_current (QuickSight expects this name)
CREATE OR REPLACE VIEW cx_analytics.revenue_breakdown_current AS
SELECT
  revenue_stream,
  CAST(current_revenue AS INTEGER) as revenue
FROM cx_analytics.revenue_breakdown;
