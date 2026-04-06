match
  (seller_role: $a, buyer_role: $b) isa {{ supplies_table }};
  (seller_role: $b, buyer_role: $c) isa {{ supplies_table }};
  $a isa {{ company_table }}, has id 1;
select $c;
