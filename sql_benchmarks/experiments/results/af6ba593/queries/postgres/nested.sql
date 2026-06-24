-- jsonb + int[]: the full nested case.
SELECT id, n, payload, tags FROM {{ wide_table }};
