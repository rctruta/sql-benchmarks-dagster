-- analytical_wall.sql (Postgres)
SELECT 
    region,
    category,
    COUNT(*) as transaction_count,
    ROUND(CAST(SUM(price * quantity * (1 - discount)) AS numeric), 2) as net_revenue,
    ROUND(CAST(AVG(price * quantity * (1 - discount)) AS numeric), 2) as avg_transaction_value,
    ROUND(CAST(SUM(CASE WHEN discount > 0.15 THEN price * quantity ELSE 0 END) / SUM(price * quantity + 0.00001) * 100 AS numeric), 2) as high_discount_impact_pct
FROM 
    {{ analytical_data_table }}
GROUP BY 
    region, 
    category
ORDER BY 
    net_revenue DESC;
