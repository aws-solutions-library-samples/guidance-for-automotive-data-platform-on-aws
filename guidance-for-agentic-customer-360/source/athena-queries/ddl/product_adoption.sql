-- View: product_adoption
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.product_adoption AS
SELECT
  customer_id
, total_vehicles
, (CASE WHEN (total_service_appointments > 0) THEN 1 ELSE 0 END) service_package_adopted
, (CASE WHEN (total_service_spend > 5000) THEN 1 ELSE 0 END) premium_service_adopted
, (CASE WHEN (MOD(customer_id, 3) = 0) THEN 1 ELSE 0 END) connected_services_adopted
, (CASE WHEN (MOD(customer_id, 4) = 0) THEN 1 ELSE 0 END) warranty_extended
, (CASE WHEN (MOD(customer_id, 5) = 0) THEN 1 ELSE 0 END) loyalty_program_member
, total_service_spend
, total_revenue
, health_segment
, (CASE WHEN (total_vehicles > 1) THEN 'Multi-Vehicle' ELSE 'Single-Vehicle' END) customer_type
FROM
  customer_health
WHERE (total_vehicles > 0);
