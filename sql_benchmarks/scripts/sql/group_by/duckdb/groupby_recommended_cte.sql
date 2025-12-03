-- The Recommended CTE Pattern: Aggregate the large table first, then join.
WITH CustomerSpend AS (
    SELECT
        customer_id,
        SUM(amount) AS total_customer_spend
    FROM
        {{ orders_table }}
    GROUP BY
        customer_id
)
SELECT
    c.customer_id,
    c.customer_name,
    c.region,
    cs.total_customer_spend
FROM
    {{ customers_table }} c
INNER JOIN
    CustomerSpend cs ON c.customer_id = cs.customer_id;