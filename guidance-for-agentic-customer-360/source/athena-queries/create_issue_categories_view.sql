-- Issue Categories View for QuickSight
CREATE OR REPLACE VIEW issue_categories_view AS
SELECT 
    CAST(month_date AS DATE) as month_date,
    month_label,
    battery_cases,
    adas_cases,
    connectivity_cases,
    infotainment_cases
FROM issue_categories;
