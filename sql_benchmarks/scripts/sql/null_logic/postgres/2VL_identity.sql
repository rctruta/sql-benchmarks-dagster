-- 1. Matches for Non-Nulls (Uses Hash Join)
SELECT count(*) 
FROM {{ r_table }} r1 
JOIN {{ r_table }} r2 ON r1.join_key_a = r2.join_key_a

UNION ALL

-- 2. Matches for Nulls (Identity)
-- This is just a cartesian of nulls, but isolated so it doesn't kill the Hash Join
SELECT count(*) 
FROM {{ r_table }} r1 
JOIN {{ r_table }} r2 ON r1.join_key_a IS NULL AND r2.join_key_a IS NULL;