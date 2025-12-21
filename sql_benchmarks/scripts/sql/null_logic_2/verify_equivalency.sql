-- Verification Script (For Manual Check)
WITH native_cnt AS (
    SELECT count(*) as c1
    FROM r1
    JOIN r2 ON 
        (r1.join_key_a = r2.join_key_a OR (r1.join_key_a IS NULL AND r2.join_key_a IS NULL))
        AND 
        (r1.join_key_b = r2.join_key_b OR (r1.join_key_b IS NULL AND r2.join_key_b IS NULL))
),
zombie_cnt AS (
    -- Need to temporarily zombify in a CTE or assume transformation? 
    -- Since we can't update in a SELECT query, we simulate it with COALESCE for the check.
    SELECT count(*) as c2
    FROM r1
    JOIN r2 ON 
        COALESCE(r1.join_key_a, 'zombie') = COALESCE(r2.join_key_a, 'zombie')
        AND
        COALESCE(r1.join_key_b, -999) = COALESCE(r2.join_key_b, -999)
)
SELECT 
    c1, c2, 
    CASE WHEN c1 = c2 THEN 'MATCH' ELSE 'MISMATCH' END as result
FROM native_cnt, zombie_cnt;
