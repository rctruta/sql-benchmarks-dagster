-- 2VL identity via the engine's native null-safe equality operator.
-- IS NOT DISTINCT FROM treats NULL = NULL as TRUE (Franconi's 2VL identity) in a
-- SINGLE operator — the natural way to express it, leaving the join strategy to
-- the planner (contrast null_logic/2VL_identity.sql, which hand-decomposes the
-- null cartesian to protect the hash join).
SELECT count(*)
FROM {{ r_table }} r1
JOIN {{ r_table }} r2
    ON r1.{{ join_key_a }} IS NOT DISTINCT FROM r2.{{ join_key_a }};
