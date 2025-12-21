-- Pre-processing: Zombify NULLs to enable simple equi-joins
UPDATE r1 SET join_key_a = 'zombie' WHERE join_key_a IS NULL;
UPDATE r1 SET join_key_b = -999      WHERE join_key_b IS NULL; -- Integer zombie

UPDATE r2 SET join_key_a = 'zombie' WHERE join_key_a IS NULL;
UPDATE r2 SET join_key_b = -999      WHERE join_key_b IS NULL; -- Integer zombie
