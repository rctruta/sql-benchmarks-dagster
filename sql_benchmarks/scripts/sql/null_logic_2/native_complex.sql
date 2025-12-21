-- The Standard SQL Join (Handling NULLs explicitly for equality)
SELECT count(*)
FROM r1
JOIN r2 ON 
    (r1.join_key_a = r2.join_key_a OR (r1.join_key_a IS NULL AND r2.join_key_a IS NULL))
    AND 
    (r1.join_key_b = r2.join_key_b OR (r1.join_key_b IS NULL AND r2.join_key_b IS NULL));
