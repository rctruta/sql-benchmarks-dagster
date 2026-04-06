match
  $s isa {{ supplier_table }}, has country "US";
  $sc (supplier_role: $s, buyer_role: $b) isa {{ supply_contract_table }};
select $b;
