-- LEFT OUTER JOIN: keeps ALL children; orphans get a NULL parent. The folklore
-- says this is "wasteful" vs INNER when FKs guarantee matches — measured here.
SELECT count(*)
FROM {{ child_table }} c
LEFT JOIN {{ parent_table }} p ON c.parent_fk = p.id;
