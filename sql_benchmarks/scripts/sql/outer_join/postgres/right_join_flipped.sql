-- RIGHT OUTER JOIN with operands flipped: `parent RIGHT JOIN child` preserves the
-- CHILD side — algebraically identical to `child LEFT JOIN parent`. Same rows,
-- same cost. The symmetry, measured (a receipt, not an argument).
SELECT count(*)
FROM {{ parent_table }} p
RIGHT JOIN {{ child_table }} c ON c.parent_fk = p.id;
