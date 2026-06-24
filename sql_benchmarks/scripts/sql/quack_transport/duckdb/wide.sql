-- Wide large result: 5 primitive columns, all rows (more bytes per row over the wire).
SELECT id, a, b, c, d FROM {{ wide_table }};
