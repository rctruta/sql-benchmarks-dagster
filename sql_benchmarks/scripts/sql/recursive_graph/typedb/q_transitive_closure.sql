# Full transitive closure from node 1 using a TypeDB 3.x recursive stream function.
# The 'reachable' function is defined in the schema and evaluated lazily with tabling
# (automatic cycle detection / fixed-point termination). No explicit loop needed.
match
  $root isa {{ company_table }}, has id 1;
  let $reachable in reachable($root);
select $reachable;
