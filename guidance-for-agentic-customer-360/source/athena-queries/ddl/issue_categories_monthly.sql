-- View: issue_categories_monthly
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.issue_categories_monthly AS
SELECT
  month_date
, month_label
, battery_cases
, (CASE WHEN (month_date = DATE '2025-01-01') THEN 95 WHEN (month_date = DATE '2025-02-01') THEN 92 WHEN (month_date = DATE '2025-03-01') THEN 98 WHEN (month_date = DATE '2025-04-01') THEN 94 WHEN (month_date = DATE '2025-05-01') THEN 96 WHEN (month_date = DATE '2025-06-01') THEN 91 WHEN (month_date = DATE '2025-07-01') THEN 99 WHEN (month_date = DATE '2025-08-01') THEN 93 WHEN (month_date = DATE '2025-09-01') THEN 95 WHEN (month_date = DATE '2025-10-01') THEN 97 WHEN (month_date = DATE '2025-11-01') THEN 89 WHEN (month_date = DATE '2025-12-01') THEN 85 END) adas_cases
, (CASE WHEN (month_date = DATE '2025-01-01') THEN 72 WHEN (month_date = DATE '2025-02-01') THEN 69 WHEN (month_date = DATE '2025-03-01') THEN 75 WHEN (month_date = DATE '2025-04-01') THEN 71 WHEN (month_date = DATE '2025-05-01') THEN 74 WHEN (month_date = DATE '2025-06-01') THEN 68 WHEN (month_date = DATE '2025-07-01') THEN 76 WHEN (month_date = DATE '2025-08-01') THEN 70 WHEN (month_date = DATE '2025-09-01') THEN 73 WHEN (month_date = DATE '2025-10-01') THEN 77 WHEN (month_date = DATE '2025-11-01') THEN 79 WHEN (month_date = DATE '2025-12-01') THEN 81 END) connectivity_cases
, (CASE WHEN (month_date = DATE '2025-01-01') THEN 65 WHEN (month_date = DATE '2025-02-01') THEN 63 WHEN (month_date = DATE '2025-03-01') THEN 68 WHEN (month_date = DATE '2025-04-01') THEN 64 WHEN (month_date = DATE '2025-05-01') THEN 67 WHEN (month_date = DATE '2025-06-01') THEN 62 WHEN (month_date = DATE '2025-07-01') THEN 69 WHEN (month_date = DATE '2025-08-01') THEN 66 WHEN (month_date = DATE '2025-09-01') THEN 65 WHEN (month_date = DATE '2025-10-01') THEN 70 WHEN (month_date = DATE '2025-11-01') THEN 61 WHEN (month_date = DATE '2025-12-01') THEN 58 END) infotainment_cases
FROM
  support_cases_monthly;
