-- BORNE D'ANCRAGE. Le range est mesure sur un bloc d'une heure FIXE (12 bougies
-- de 5 min, non chevauchantes). Sa borne haute est figee. On surveille ensuite
-- l'heure suivante : le signal est la PREMIERE bougie qui cloture 5 % au-dessus
-- de cette borne figee.
--
-- Difference avec la fenetre glissante : la borne ne monte pas avec le prix.
-- Avec une fenetre glissante, une bougie qui casse devient elle-meme la borne de
-- la suivante, et le signal ne se declenche que si le bond depasse de 5 % son
-- propre plus haut recent — ce qui rate les vraies cassures.
CREATE OR REPLACE TABLE pumpfun.tmp_bloc ENGINE = MergeTree ORDER BY (pool, bloc) AS
SELECT pool, intDiv(b, 12) AS bloc,
  min(plus_bas) AS bas, max(plus_haut) AS borne,
  sum(trades) AS trades_bloc, min(trades) AS trades_min, count() AS bougies,
  median(taille_med) AS taille_range, max(b) AS b_fin
FROM pumpfun.tmp_c5t
GROUP BY pool, bloc
HAVING bougies = 12;

CREATE OR REPLACE TABLE pumpfun.tmp_ancre ENGINE = MergeTree ORDER BY (pool, bloc) AS
SELECT bl.pool AS pool, bl.bloc AS bloc, bl.bas AS bas, bl.borne AS borne,
  bl.trades_bloc AS trades_bloc, bl.trades_min AS trades_min,
  bl.taille_range AS taille_range,
  argMin(c.b, c.b) AS b_signal, argMin(c.t5, c.b) AS t_signal,
  argMin(c.cloture, c.b) AS prix_signal, argMin(c.taille_med, c.b) AS taille_signal
FROM pumpfun.tmp_bloc bl
INNER JOIN pumpfun.tmp_c5t c ON c.pool = bl.pool
WHERE c.b > bl.b_fin AND c.b <= bl.b_fin + 12 AND c.cloture > bl.borne * 1.05
GROUP BY bl.pool, bl.bloc, bl.bas, bl.borne, bl.trades_bloc, bl.trades_min, bl.taille_range;

SELECT round(avg(x),4) AS moyenne, uniqExact(a.pool) AS tokens, count() AS trades,
  round(median(x),4) AS mediane, round(100*countIf(x<0.2)/count(),2) AS pct_effondrements,
  round(100*countIf(x>1)/count(),1) AS pct_gagnants,
  round(median(a.prix_signal/a.borne),3) AS depassement_med,
  round(median(a.b_signal - a.bloc*12 - 12),1) AS bougies_d_attente
FROM pumpfun.tmp_ancre a
INNER JOIN pumpfun.tmp_c5t e ON e.pool = a.pool AND e.b = a.b_signal + 1
INNER JOIN pumpfun.tmp_c5t s ON s.pool = a.pool AND s.b = a.b_signal + 7
ARRAY JOIN [(s.cloture/e.ouverture)*(1-0.5/e.reserve)*(1-0.5/e.reserve)*0.994] AS x
WHERE a.borne/a.bas <= 1.10 AND a.trades_min >= 5 AND e.reserve >= 5
  AND a.taille_range > 0 AND a.taille_signal/a.taille_range <= 3;
