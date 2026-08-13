-- Hypothèse 21 — chercher un edge sur plusieurs heures.
--
-- Motivation : la règle 5 (le preneur paie le gap) tue toute stratégie qui
-- réagit à un prix affiché. Sur des horizons de plusieurs heures, la latence ne
-- mord plus. Restait à savoir s'il y a quelque chose à y prendre.
--
-- DEUX PIÈGES RENCONTRÉS ET CORRIGÉS, tous deux repérés par un chiffre absurde :
--
--   1. LOOK-AHEAD. Première version : population définie par « pool vivant ≥ 20 h
--      et ≥ 2 000 trades ». C'est une sélection sur l'AVENIR du pool. Elle
--      donnait une baseline à 1,342 sans top 3 — un edge impossible sur un achat
--      au hasard. Corrigé : aucune condition de survie, toutes les conditions
--      portent sur le passé au moment de la décision.
--   2. POOLS HORS SOL. Deuxième version : moyennes à 95 357. Cause : un pool dont
--      le côté base est vidé voit son prix exploser mécaniquement (0,0107 puis
--      1 103 812) sans qu'on puisse rien y vendre. Faute de `base_mint` et
--      `quote_mint` dans la capture, ils ne se distinguent que par une bande de
--      prix calibrée sur la cohorte de graduation, seule certifiée Pump.fun.

-- AUCUNE condition de survie : tous les pools, toutes les heures.
-- Les conditions ne s'appliquent qu'au moment de la decision, sur du passe.
CREATE OR REPLACE TABLE pumpfun.tmp_all_h ENGINE = MergeTree ORDER BY (pool, h) AS
SELECT pool,
  toUInt16(dateDiff('hour', toDateTime64('2026-08-10 11:33:27.266', 3, 'UTC'), received_at)) AS h,
  argMax(price_sol, received_at) AS prix,
  argMax(toFloat64(quote_reserves), received_at)/1e9 AS reserve,
  count() AS trades
FROM pumpfun.pumpswap_trades GROUP BY pool, h;

CREATE OR REPLACE TABLE pumpfun.tmp_all_dense ENGINE = MergeTree ORDER BY (pool, h) AS
SELECT pool, toUInt16(idx-1) AS h, px[idx] AS prix, rs[idx] AS reserve, ac[idx] AS trades
FROM (
  SELECT pool,
    arrayFill(x -> x > 0, groupArrayInsertAt(toFloat64(0), 80)(prix, h))    AS px,
    arrayFill(x -> x > 0, groupArrayInsertAt(toFloat64(0), 80)(reserve, h)) AS rs,
    groupArrayInsertAt(toUInt32(0), 80)(toUInt32(trades), h)                AS ac
  FROM pumpfun.tmp_all_h WHERE h <= 79 GROUP BY pool)
ARRAY JOIN range(1, 81) AS idx
WHERE px[idx] > 0;

SELECT uniqExact(pool) AS pools, count() AS barres FROM pumpfun.tmp_all_dense;
CREATE OR REPLACE TABLE pumpfun.tmp_all_ok ENGINE = MergeTree ORDER BY (pool, h) AS
SELECT pool, h, prix, reserve, trades,
  min(prix) OVER w AS bas, max(prix) OVER w AS haut, sum(trades) OVER w AS act6,
  leadInFrame(prix, 1)  OVER f AS p_e,
  leadInFrame(prix, 4)  OVER f AS s3,
  leadInFrame(prix, 7)  OVER f AS s6,
  leadInFrame(prix, 13) OVER f AS s12
FROM pumpfun.tmp_all_dense
WINDOW w AS (PARTITION BY pool ORDER BY h ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING),
       f AS (PARTITION BY pool ORDER BY h ROWS BETWEEN CURRENT ROW AND 13 FOLLOWING);

SELECT regime, concat('+', toString(k), ' h') AS maintien, count() AS n,
  round(median(x),4) AS mediane, round(avg(x),4) AS moyenne,
  round((sum(x)-arraySum(arraySlice(arraySort(groupArray(x)), count()-2)))/(count()-3),4)  AS sans_top3,
  round((sum(x)-arraySum(arraySlice(arraySort(groupArray(x)), count()-9)))/(count()-10),4) AS sans_top10,
  round(100*countIf(x>1)/count(),1) AS pct_gagnants
FROM (
  SELECT 'A. cassure de couloir 6 h' AS regime, k, (sortie/p_e)*0.99*0.99*0.994 AS x
  FROM pumpfun.tmp_all_ok ARRAY JOIN [3,6,12] AS k, [s3,s6,s12] AS sortie
  WHERE h >= 7 AND reserve BETWEEN 300 AND 20000 AND act6 >= 200
    AND bas > 0 AND haut/bas <= 1.10 AND prix > haut*1.01 AND p_e > 0 AND sortie > 0
  UNION ALL
  SELECT 'B. baseline apparie', k, (sortie/p_e)*0.99*0.99*0.994
  FROM pumpfun.tmp_all_ok ARRAY JOIN [3,6,12] AS k, [s3,s6,s12] AS sortie
  WHERE h >= 7 AND reserve BETWEEN 300 AND 20000 AND act6 >= 200 AND p_e > 0 AND sortie > 0)
GROUP BY regime, k ORDER BY regime, k;
CREATE OR REPLACE TABLE pumpfun.tmp_pool_sain ENGINE = MergeTree ORDER BY pool AS
SELECT pool FROM pumpfun.tmp_all_h
GROUP BY pool HAVING median(prix) BETWEEN 1e-11 AND 1e-2 AND max(prix) < 1e-1;

SELECT regime, concat('+', toString(k), ' h') AS maintien, count() AS n,
  round(median(x),4) AS mediane, round(avg(x),4) AS moyenne,
  round((sum(x)-arraySum(arraySlice(arraySort(groupArray(x)), count()-2)))/(count()-3),4)  AS sans_top3,
  round((sum(x)-arraySum(arraySlice(arraySort(groupArray(x)), count()-9)))/(count()-10),4) AS sans_top10,
  round(100*countIf(x>1)/count(),1) AS pct_gagnants,
  round(100*countIf(x<0.5)/count(),1) AS pct_pertes_lourdes
FROM (
  SELECT 'A. cassure de couloir 6 h' AS regime, k, (sortie/p_e)*0.99*0.99*0.994 AS x
  FROM pumpfun.tmp_all_ok
  ARRAY JOIN [3,6,12] AS k, [s3,s6,s12] AS sortie
  WHERE pool IN (SELECT pool FROM pumpfun.tmp_pool_sain)
    AND h >= 7 AND reserve BETWEEN 300 AND 20000 AND act6 >= 200
    AND bas > 0 AND haut/bas <= 1.10 AND prix > haut*1.01 AND p_e > 0 AND sortie > 0
  UNION ALL
  SELECT 'B. baseline apparie', k, (sortie/p_e)*0.99*0.99*0.994
  FROM pumpfun.tmp_all_ok
  ARRAY JOIN [3,6,12] AS k, [s3,s6,s12] AS sortie
  WHERE pool IN (SELECT pool FROM pumpfun.tmp_pool_sain)
    AND h >= 7 AND reserve BETWEEN 300 AND 20000 AND act6 >= 200 AND p_e > 0 AND sortie > 0)
GROUP BY regime, k ORDER BY regime, k;
