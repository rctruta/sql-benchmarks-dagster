-- Benchmarks the cost of handling NULLs as a concrete value ("Identity")
-- vs letting the database skip them (Standard 3VL).
-- [PREP_START]
DROP TABLE IF EXISTS {{ r_table }}_sentinel;

-- 1. Physical Materialization (The "Baking" Phase)
CREATE UNLOGGED TABLE {{ r_table }}_sentinel AS 
SELECT 
    COALESCE({{ join_key_a }}, -1) AS {{ join_key_a }}
FROM {{ r_table }};

-- 2. Statistic Update (The "Notification" Phase)
ANALYZE {{ r_table }}_sentinel;
-- [PREP_END]

-- 3. The Benchmark 
SELECT count(*)
FROM {{ r_table }}_sentinel r1
JOIN {{ r_table }}_sentinel r2 
  ON r1.{{ join_key_a }} = r2.{{ join_key_a }};

