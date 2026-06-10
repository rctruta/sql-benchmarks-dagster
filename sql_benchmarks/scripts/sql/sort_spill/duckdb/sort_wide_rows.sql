-- Sort Spill: Multi-column sort on wide rows (DuckDB control).
-- DuckDB manages memory adaptively — no work_mem equivalent.
-- This is the control arm: same query, no spill constraint.
-- Compare against postgres/sort_wide_rows.sql to isolate the spill cost.

SELECT
    id,
    region,
    category,
    department,
    sub_category,
    ROUND(price, 4)                              AS price,
    ROUND(cost, 4)                               AS cost,
    ROUND(margin, 4)                             AS margin,
    quantity,
    discount,
    ROUND(price * quantity * (1.0 - discount), 4) AS net_revenue
FROM {{ sort_data_table }}
ORDER BY
    region ASC,
    category ASC,
    department ASC,
    net_revenue DESC,
    quantity DESC
LIMIT 1000;
