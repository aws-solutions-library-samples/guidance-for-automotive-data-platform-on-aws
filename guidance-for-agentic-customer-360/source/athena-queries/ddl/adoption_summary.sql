-- View: adoption_summary
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.adoption_summary AS
SELECT
  'Service Package' product
, SUM(service_package_adopted) adopters
, COUNT(*) total_customers
, ROUND(((1E2 * SUM(service_package_adopted)) / COUNT(*)), 2) adoption_rate
FROM
  product_adoption
UNION ALL SELECT
  'Premium Service'
, SUM(premium_service_adopted)
, COUNT(*)
, ROUND(((1E2 * SUM(premium_service_adopted)) / COUNT(*)), 2)
FROM
  product_adoption
UNION ALL SELECT
  'Connected Services'
, SUM(connected_services_adopted)
, COUNT(*)
, ROUND(((1E2 * SUM(connected_services_adopted)) / COUNT(*)), 2)
FROM
  product_adoption
UNION ALL SELECT
  'Extended Warranty'
, SUM(warranty_extended)
, COUNT(*)
, ROUND(((1E2 * SUM(warranty_extended)) / COUNT(*)), 2)
FROM
  product_adoption
UNION ALL SELECT
  'Loyalty Program'
, SUM(loyalty_program_member)
, COUNT(*)
, ROUND(((1E2 * SUM(loyalty_program_member)) / COUNT(*)), 2)
FROM
  product_adoption;
