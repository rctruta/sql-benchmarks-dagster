match
  $x isa {{ skewed_data_table }},
    has selectivity_code "filler";
select $x;
