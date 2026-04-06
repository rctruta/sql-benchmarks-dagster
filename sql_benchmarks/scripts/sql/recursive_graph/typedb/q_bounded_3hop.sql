match
  $root isa {{ company_table }}, has id 1;
  (seller_role: $root, buyer_role: $hop1) isa {{ supplies_table }};
  (seller_role: $hop1, buyer_role: $hop2) isa {{ supplies_table }};
  (seller_role: $hop2, buyer_role: $leaf) isa {{ supplies_table }};
select $hop1, $hop2, $leaf;
