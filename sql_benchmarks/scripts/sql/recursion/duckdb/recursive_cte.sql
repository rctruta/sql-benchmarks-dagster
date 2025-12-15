-- sql_queries/duckdb/recursion_cte.sql
-- Recursively finds all descendants (or ancestors) of a specific node.
-- We use node ID 1 as a common starting point.
-- | id | INTEGER | Primary Key, Node ID | 
-- | parent_id | INTEGER | Foreign Key to id, or NULL for the root | 
-- | name | VARCHAR | Node label |

WITH RECURSIVE
    # {{ hierarchy_table }} will be rendered as `hierarchy_partitionkey` (e.g., hierarchy_small)
    descendants (id, parent_id, name, depth) AS (
        SELECT 
            id, 
            parent_id, 
            name, 
            1 AS depth 
        FROM {{ hierarchy_table }}
        WHERE id = 1 # Start at a known root/branch node

        UNION ALL

        SELECT 
            t.id, 
            t.parent_id, 
            t.name, 
            d.depth + 1
        FROM {{ hierarchy_table }} AS t
        INNER JOIN descendants AS d 
            ON t.parent_id = d.id
)
SELECT 
    # The final result is the count of all descendant nodes found
    count(*) 
FROM descendants;