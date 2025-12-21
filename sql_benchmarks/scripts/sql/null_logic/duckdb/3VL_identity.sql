-- 3VL TEST (Standard Identity Loss)
SELECT count(*) 
FROM {{ r_table }} r1 
JOIN {{ r_table }} r2 ON r1.join_key_a = r2.join_key_a;
