-- This query uses a Left Join and filters NULLs, which is slower than Inner Join
SELECT count(*) 
FROM orders o 
LEFT JOIN customers c ON o.customer_id = c.customer_id
WHERE c.customer_id IS NOT NULL;