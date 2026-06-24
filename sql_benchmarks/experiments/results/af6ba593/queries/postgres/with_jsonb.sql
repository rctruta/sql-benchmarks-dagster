-- + a jsonb column: fat semi-structured payload over the wire.
SELECT id, n, payload FROM {{ wide_table }};
