-- This query uses a standard Inner Join
SELECT count(*) 
FROM orders o 
JOIN customers c ON o.customer_id = c.customer_id;