match
  $s isa {{ supplier_table }}, has country "EU";
  $sc (supplier_role: $s, product_role: $p) isa {{ supply_contract_table }};
  $p isa {{ product_table }}, has category "electronics";
select $p;
