-- Fixed 2-hop: companies reachable from node 1 in exactly 2 supply steps.
-- Baseline — DuckDB should win comfortably. Two plain JOINs on integer FKs.
SELECT DISTINCT s2.to_id AS company_id
FROM {{ supplies_table }} s1
JOIN {{ supplies_table }} s2 ON s1.to_id = s2.from_id
WHERE s1.from_id = 1;
