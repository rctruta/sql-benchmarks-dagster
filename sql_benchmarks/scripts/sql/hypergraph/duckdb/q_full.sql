SELECT s.id AS supplier_id, s.country,
       b.id AS buyer_id,    b.region,
       p.id AS product_id,  p.category
FROM {{ supply_contract_table }} sc
JOIN {{ supplier_table }} s ON s.id = sc.supplier_id
JOIN {{ buyer_table }}    b ON b.id = sc.buyer_id
JOIN {{ product_table }}  p ON p.id = sc.product_id
WHERE s.country = 'US'
  AND b.region  = 'APAC';
