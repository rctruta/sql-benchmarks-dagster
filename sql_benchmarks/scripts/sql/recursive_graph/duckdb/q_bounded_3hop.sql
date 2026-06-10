-- Bounded variable-depth: all companies reachable from node 1 in up to 3 hops.
-- Recursive CTE with depth guard. Intermediate result set materialised at each
-- step — this is where OOM occurs on hub-heavy Zipf graphs.
WITH RECURSIVE reachable(company_id, depth) AS (
    SELECT to_id AS company_id, 1 AS depth
    FROM {{ supplies_table }}
    WHERE from_id = 1

    UNION

    SELECT s.to_id, r.depth + 1
    FROM reachable r
    JOIN {{ supplies_table }} s ON s.from_id = r.company_id
    WHERE r.depth < 3
)
SELECT COUNT(DISTINCT company_id) AS reachable_count
FROM reachable;
