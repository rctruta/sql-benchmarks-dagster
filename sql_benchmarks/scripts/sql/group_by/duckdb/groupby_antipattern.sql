SELECT
    c.customer_id,
    c.customer_name,
    c.region,
    SUM(o.amount) AS total_spend
FROM
    {{ orders_table }} o
INNER JOIN
    {{ customers_table }} c ON o.customer_id = c.customer_id
GROUP BY
    c.customer_id, c.customer_name, c.region; -- The anti-pattern