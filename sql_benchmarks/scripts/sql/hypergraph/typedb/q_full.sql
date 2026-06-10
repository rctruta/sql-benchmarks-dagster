match
  $sc (supplier_role: $s, buyer_role: $b, product_role: $p) isa {{ supply_contract_table }};
  $s isa {{ supplier_table }}, has country "US";
  $b isa {{ buyer_table }}, has region "APAC";
  $p isa {{ product_table }};
select $s, $b, $p;
