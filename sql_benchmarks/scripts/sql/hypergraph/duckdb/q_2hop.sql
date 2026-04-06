SELECT DISTINCT p.id, p.name, p.category
FROM {{ supply_contract_table }} sc
JOIN {{ supplier_table }} s ON s.id = sc.supplier_id
JOIN {{ product_table }} p ON p.id = sc.product_id
WHERE s.country = 'EU'
  AND p.category = 'electronics';
