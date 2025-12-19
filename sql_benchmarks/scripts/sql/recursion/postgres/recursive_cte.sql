-- sql_queries/postgres/recursion_cte.sql
-- Recursively finds all descendants (or ancestors) of a specific node.
-- We use node ID 1 as a common starting point.

WITH RECURSIVE
    -- {{ hierarchy_table }} will be rendered as `hierarchy_partitionkey`
    descendants (id, parent_id, name, depth) AS (
        SELECT 
            id, 
            parent_id, 
            name, 
            1 AS depth 
        FROM {{ hierarchy_data_table }} AS t
        WHERE id = 1 -- Start at a known root/branch node

        UNION ALL

        SELECT 
            t.id, 
            t.parent_id, 
            t.name, 
            d.depth + 1
        FROM {{ hierarchy_data_table }} AS t
        INNER JOIN descendants AS d 
            ON t.parent_id = d.id
)
SELECT 
    -- The final result is the count of all descendant nodes found
    count(*) 
FROM descendants;
