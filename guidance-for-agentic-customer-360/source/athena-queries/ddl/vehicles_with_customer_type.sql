-- View: vehicles_with_customer_type
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.vehicles_with_customer_type AS
SELECT
  v.*
, (CASE WHEN (MOD(v.user_id, 10) < 3) THEN 'Commercial' ELSE 'Individual' END) customer_type
FROM
  dms_lakehouse.vehicles_bronze v;
