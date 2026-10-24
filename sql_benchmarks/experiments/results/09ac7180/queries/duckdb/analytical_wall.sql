-- analytical_wall.sql (DuckDB)
SELECT 
    region,
    category,
    COUNT(*) as transaction_count,
    ROUND(SUM(price * quantity * (1 - discount)), 2) as net_revenue,
    ROUND(AVG(price * quantity * (1 - discount)), 2) as avg_transaction_value,
    ROUND(SUM(CASE WHEN discount > 0.15 THEN price * quantity ELSE 0 END) / SUM(price * quantity + 0.00001) * 100, 2) as high_discount_impact_pct
FROM 
    {{ analytical_data_table }}
GROUP BY 
    region, 
    category
ORDER BY 
    net_revenue DESC;
