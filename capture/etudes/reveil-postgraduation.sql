-- Étude 15 — Réveil après consolidation, sur PumpSwap (post-graduation).
--
--   clickhouse-client --password "$CLICKHOUSE_PASSWORD" -n < etudes/reveil-postgraduation.sql
--   (nécessite pumpswap_trades, produit par etudes/pumpswap-decode.sql)
--
-- HYPOTHÈSE. Un token qui reste 30 minutes dans un couloir de ±10 % a laissé
-- sortir ses vendeurs impatients : l'offre disponible est épuisée. La cassure
-- du haut du couloir part alors contre peu de résistance. C'est une hypothèse
-- sur une contrainte, pas sur une opinion.
--
-- RÈGLE. Signal si, sur les 30 minutes STRICTEMENT PRÉCÉDENTES, haut/bas ≤ 1,10
-- avec ≥ 60 trades, et que le prix casse haut × 1,01. Entrée à la minute
-- suivante, sortie à durée fixe. Taille plafonnée à 10 % des réserves du pool.
--
-- DEUX PIÈGES CORRIGÉS EN CHEMIN, tous deux repérés par un chiffre absurde :
--
--   1. `leadInFrame(prix, 61)` renvoie 61 LIGNES, pas 61 minutes. Ces pools ne
--      tradent que 27 % des minutes : le « +60 min » valait 62 minutes à la
--      médiane mais 159 au 9e décile, et le +180 sortait de la partition avec
--      un décalage négatif. D'où la série dense reconstruite ci-dessous —
--      toutes les minutes, prix reporté.
--   2. Le facteur d'impact `1 - taille/réserves` devient NÉGATIF sous 0,5 SOL
--      de réserves, ce qui donnait des moyennes à -2 400. D'où la contrainte
--      `reserve >= 10 × taille`, qui est de toute façon une règle de bon sens.

-- Étape 1 — agrégat par minute (minutes avec activité seulement).
CREATE OR REPLACE TABLE pumpfun.tmp_ps_min ENGINE = MergeTree ORDER BY (pool, m) AS
WITH vivants AS (
  SELECT pool, min(received_at) AS t0 FROM pumpfun.pumpswap_trades
  GROUP BY pool
  HAVING dateDiff('minute', min(received_at), max(received_at)) >= 120 AND count() >= 200)
SELECT t.pool AS pool, toUInt16(dateDiff('minute', v.t0, t.received_at)) AS m,
  argMax(t.price_sol, t.received_at) AS prix, count() AS activite,
  argMax(t.quote_reserves, t.received_at) / 1e9 AS qr
FROM pumpfun.pumpswap_trades t INNER JOIN vivants v ON v.pool = t.pool
WHERE dateDiff('minute', v.t0, t.received_at) BETWEEN 0 AND 480
GROUP BY pool, m;

-- Étape 2 — série DENSE : toutes les minutes, prix reporté. Indispensable, cf. piège 1.
CREATE OR REPLACE TABLE pumpfun.tmp_ps_dense ENGINE = MergeTree ORDER BY (pool, m) AS
SELECT pool, toUInt16(idx - 1) AS m, px[idx] AS prix, qr[idx] AS reserve, act[idx] AS activite
FROM (
  SELECT pool,
    arrayFill(x -> x > 0, groupArrayInsertAt(toFloat64(0), 481)(prix, m)) AS px,
    arrayFill(x -> x > 0, groupArrayInsertAt(toFloat64(0), 481)(qr, m))   AS qr,
    groupArrayInsertAt(toUInt32(0), 481)(toUInt32(activite), m)           AS act
  FROM pumpfun.tmp_ps_min GROUP BY pool)
ARRAY JOIN range(1, 482) AS idx
WHERE px[idx] > 0;

-- Étape 3 — détection du couloir sur fenêtre STRICTEMENT PASSÉE, et prix futurs.
CREATE OR REPLACE TABLE pumpfun.tmp_ps_ok ENGINE = MergeTree ORDER BY (pool, m) AS
SELECT pool, m, prix, reserve,
  min(prix) OVER w AS bas, max(prix) OVER w AS haut, sum(activite) OVER w AS tr30,
  leadInFrame(prix, 1)    OVER f AS p_e,
  leadInFrame(prix, 31)   OVER f AS h30,
  leadInFrame(prix, 61)   OVER f AS h60,
  leadInFrame(prix, 121)  OVER f AS h120,
  leadInFrame(reserve, 1) OVER f AS qr_e
FROM pumpfun.tmp_ps_dense
WINDOW w AS (PARTITION BY pool ORDER BY m ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING),
       f AS (PARTITION BY pool ORDER BY m ROWS BETWEEN CURRENT ROW AND 121 FOLLOWING);

-- Étape 4 — l'arbitrage de la sortie. Le rendement médian monte avec la durée,
-- la queue gauche aussi. Il n'y a pas de « bon » horizon, il y a un choix.
SELECT 30 AS horizon_min, count() AS n, round(median(h30 / p_e), 4) AS mediane,
  round(100 * countIf(h30 / p_e > 1.01) / count(), 1) AS pct_gagnant,
  round(100 * countIf(h30 / p_e < 0.8) / count(), 1)  AS pct_perte_20
FROM pumpfun.tmp_ps_ok
WHERE m >= 31 AND bas > 0 AND haut / bas <= 1.10 AND tr30 >= 60 AND prix > haut * 1.01
  AND p_e > 0 AND h30 > 0 AND qr_e >= 5
UNION ALL
SELECT 60, count(), round(median(h60 / p_e), 4),
  round(100 * countIf(h60 / p_e > 1.01) / count(), 1),
  round(100 * countIf(h60 / p_e < 0.8) / count(), 1)
FROM pumpfun.tmp_ps_ok
WHERE m >= 31 AND bas > 0 AND haut / bas <= 1.10 AND tr30 >= 60 AND prix > haut * 1.01
  AND p_e > 0 AND h60 > 0 AND qr_e >= 5
UNION ALL
SELECT 120, count(), round(median(h120 / p_e), 4),
  round(100 * countIf(h120 / p_e > 1.01) / count(), 1),
  round(100 * countIf(h120 / p_e < 0.8) / count(), 1)
FROM pumpfun.tmp_ps_ok
WHERE m >= 31 AND bas > 0 AND haut / bas <= 1.10 AND tr30 >= 60 AND prix > haut * 1.01
  AND p_e > 0 AND h120 > 0 AND qr_e >= 5;

-- Étape 5 — BASELINE APPARIÉE : mêmes pools, mêmes instants, sans la condition
-- de réveil. C'est la seule comparaison qui vaille : un « +3,6 % » ne dit rien
-- si le marché fait +3,6 % au même moment.
SELECT count() AS n, round(median(h60 / p_e), 4) AS mediane_baseline
FROM pumpfun.tmp_ps_ok
WHERE m >= 31 AND p_e > 0 AND h60 > 0 AND tr30 >= 60 AND qr_e >= 5;
