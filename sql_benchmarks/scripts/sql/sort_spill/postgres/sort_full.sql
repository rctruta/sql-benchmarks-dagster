-- Sort Spill: Full sort (no LIMIT) on wide rows.
-- Without LIMIT, Postgres cannot use the top-N heap sort optimization.
-- The entire result set must be sorted in memory or spilled to disk.
-- At tight work_mem (4MB), spill will occur at low row counts.
-- This is where the cliff actually lives.

SELECT
    id,
    region,
    category,
    department,
    sub_category,
    ROUND(CAST(price AS NUMERIC), 4)        AS price,
    ROUND(CAST(cost AS NUMERIC), 4)         AS cost,
    ROUND(CAST(margin AS NUMERIC), 4)       AS margin,
    quantity,
    discount,
    ROUND(CAST(price * quantity * (1.0 - discount) AS NUMERIC), 4) AS net_revenue
FROM {{ sort_data_table }}
ORDER BY
    region ASC,
    category ASC,
    department ASC,
    net_revenue DESC,
    quantity DESC;
