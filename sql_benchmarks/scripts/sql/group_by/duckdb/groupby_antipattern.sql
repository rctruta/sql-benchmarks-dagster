SELECT
    c.customer_id,
    c.customer_name,
    c.region,
    SUM(o.amount) AS total_spend
FROM
    {{ customers_table }} c
INNER JOIN
    {{ orders_table }} o ON c.customer_id = o.customer_id
GROUP BY
    c.customer_id, c.customer_name, c.region; -- The anti-pattern