-- INNER JOIN: keeps only children that have a matching parent (orphans dropped).
SELECT count(*)
FROM {{ child_table }} c
JOIN {{ parent_table }} p ON c.parent_fk = p.id;
