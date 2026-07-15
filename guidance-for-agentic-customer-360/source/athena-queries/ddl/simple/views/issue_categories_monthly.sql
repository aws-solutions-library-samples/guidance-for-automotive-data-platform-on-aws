-- View: issue_categories_monthly (QuickSight expects this name)
CREATE OR REPLACE VIEW cx_analytics.issue_categories_monthly AS
SELECT
  CAST(month_date AS DATE) as month_date,
  month_label,
  battery_cases,
  software_cases as adas_cases,
  hardware_cases as connectivity_cases,
  service_cases as infotainment_cases
FROM cx_analytics.issue_categories;
