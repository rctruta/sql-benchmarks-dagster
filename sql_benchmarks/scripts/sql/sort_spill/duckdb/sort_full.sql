-- Sort Spill: Full sort (no LIMIT) on wide rows (DuckDB control).
-- DuckDB uses vectorized execution and adaptive memory management.
-- No work_mem equivalent — spill is handled transparently.
-- Compare against postgres/sort_full.sql: without top-N optimization,
-- the full architectural cost of row-at-a-time vs vectorized sort is exposed.

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
    quantity DESC;
