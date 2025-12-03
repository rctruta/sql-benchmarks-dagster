-- groupby_recommended_pk.sql
-- This demonstrates the correct way to group when you need columns from
-- a "one" side of a join. By grouping only by the primary key,
-- Postgres is smart enough to know the other columns (customer_name, state)
-- are functionally dependent and allows them in the SELECT list.

SELECT
    c.customer_id,
    c.customer_name,
    c.region,
    SUM(o.amount) AS total_amount
FROM
    {{ orders_table }} o
INNER JOIN
    {{ customers_table }} c ON o.customer_id = c.customer_id
GROUP BY
    c.customer_id; -- The efficient pattern
