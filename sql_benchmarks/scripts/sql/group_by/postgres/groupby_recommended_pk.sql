SELECT
    c.customer_id,
    c.customer_name,
    c.region,
    SUM(o.amount) AS total_amount
FROM
    {{ customers_table }} c
JOIN
    {{ orders_table }} o ON c.customer_id = o.customer_id
GROUP BY
    c.customer_id; -- Postgres infers name/region from PK