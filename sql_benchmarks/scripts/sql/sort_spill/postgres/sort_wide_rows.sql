-- Sort Spill: Multi-column sort on wide rows.
-- Hypothesis: At some row count, the sort set exceeds work_mem and Postgres
-- spills to disk, producing a visible performance cliff.
-- The work_mem is set intentionally tight in pg_settings to expose this cliff.
-- DuckDB (sort_spill/duckdb/) runs the same query as a control without this constraint.

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
    quantity DESC
LIMIT 1000;
