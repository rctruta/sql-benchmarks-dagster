-- Full transitive closure from node 1: every company that directly or
-- indirectly depends on node 1 in the supply chain.
-- No depth limit — the CTE runs until no new nodes are discovered.
-- This is the query most likely to OOM on a Zipf hub at medium scale.
WITH RECURSIVE closure(company_id) AS (
    SELECT to_id AS company_id
    FROM {{ supplies_table }}
    WHERE from_id = 1

    UNION

    SELECT s.to_id
    FROM closure c
    JOIN {{ supplies_table }} s ON s.from_id = c.company_id
)
SELECT COUNT(DISTINCT company_id) AS total_reachable
FROM closure;
