-- View: nps_by_month
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.nps_by_month AS
WITH
  sentiment_nps AS (
   SELECT
     DATE_TRUNC('month', interaction_date) month_date
   , (CASE WHEN (sentiment_score >= 8.5E-1) THEN 1 WHEN (sentiment_score <= 3.5E-1) THEN -1 ELSE 0 END) nps_category
   , sentiment_score
   FROM
     customer_interactions
   WHERE (sentiment_score IS NOT NULL)
) 
SELECT
  month_date
, DATE_FORMAT(month_date, '%b %Y') month_label
, COUNT(*) total_responses
, SUM((CASE WHEN (nps_category = 1) THEN 1 ELSE 0 END)) promoters
, SUM((CASE WHEN (nps_category = 0) THEN 1 ELSE 0 END)) passives
, SUM((CASE WHEN (nps_category = -1) THEN 1 ELSE 0 END)) detractors
, ROUND((((CAST(SUM((CASE WHEN (nps_category = 1) THEN 1 ELSE 0 END)) AS DOUBLE) / COUNT(*)) * 100) - ((CAST(SUM((CASE WHEN (nps_category = -1) THEN 1 ELSE 0 END)) AS DOUBLE) / COUNT(*)) * 100)), 1) nps_score
, ROUND((AVG(sentiment_score) * 10), 1) avg_score
FROM
  sentiment_nps
GROUP BY month_date;
