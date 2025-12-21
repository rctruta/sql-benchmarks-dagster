-- Benchmarks the cost of handling NULLs as a concrete value ("Identity")
-- vs letting the database skip them (Standard 3VL).
DROP TABLE IF EXISTS {{ r_table }}_sentinel;

CREATE TABLE {{ r_table }}_sentinel AS 
SELECT 
    COALESCE({{ join_key_a }}, -1) AS {{ join_key_a }}
FROM {{ r_table }};

ANALYZE {{ r_table }}_sentinel;

SELECT count(*)
FROM {{ r_table }}_sentinel r1
JOIN {{ r_table }}_sentinel r2 
  ON r1.{{ join_key_a }} = r2.{{ join_key_a }};

