-- This query uses a standard Inner Join
SELECT count(*) 
FROM {{ orders_table }} o 
JOIN {{ customers_table }} c ON o.customer_id = c.customer_id;