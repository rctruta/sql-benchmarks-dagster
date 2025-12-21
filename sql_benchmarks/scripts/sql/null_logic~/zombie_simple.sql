-- The Optimized "Zombie" Join (Simple Equi-Join)
-- Note: This requires the 'zombify.sql' step to have been run beforehand.
SELECT count(*)
FROM r t1
JOIN r t2 ON 
    t1.join_key_a = t2.join_key_a 
    AND 
    t1.join_key_b = t2.join_key_b;
