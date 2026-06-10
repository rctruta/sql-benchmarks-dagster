SELECT DISTINCT b.id, b.name, b.region
FROM {{ supply_contract_table }} sc
JOIN {{ supplier_table }} s ON s.id = sc.supplier_id
JOIN {{ buyer_table }} b ON b.id = sc.buyer_id
WHERE s.country = 'US';
