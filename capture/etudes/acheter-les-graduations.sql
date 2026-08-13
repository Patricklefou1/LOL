-- Hypothèse 19 — acheter TOUTES les graduations.
--
-- POPULATION ENFIN PROPRE. La signature d'une graduation Pump.fun sur PumpSwap
-- est une réserve initiale de très exactement **67,406 SOL** — constante à la
-- troisième décimale sur les quatre jours de capture. Ce n'est pas 85 SOL : la
-- migration prélève sa part. Cela donne 365 / 468 / 817 graduations par jour,
-- enfin cohérent avec le marché réel (les « 3 626 migrations/jour » d'une étude
-- antérieure comptaient tout ce qui ouvre un pool sur PumpSwap).
--
-- SANS BIAIS DU SURVIVANT, contrairement aux études 15 à 18 : ces 1 821 pools
-- sont suivis depuis leur première seconde, pas sélectionnés parce qu'ils
-- vivaient encore. C'est la différence entre « ce que fait le marché » et « ce
-- que font les survivants ».
--
-- Entrée au premier trade au moins 1 seconde après l'ouverture du pool : on ne
-- peut pas être dans la transaction de migration elle-même.

CREATE OR REPLACE TABLE pumpfun.tmp_grad_serie ENGINE = MergeTree ORDER BY pool AS
WITH (SELECT min(received_at) FROM pumpfun.pumpswap_trades) AS t_debut
SELECT g.pool AS pool, g.t0 AS t0,
  arraySort(x -> x.1, groupArray((t.received_at, t.price_sol, toFloat64(t.quote_reserves)/1e9))) AS serie
FROM (SELECT pool, min(received_at) AS t0, argMin(toFloat64(quote_reserves), received_at)/1e9 AS qr0
      FROM pumpfun.pumpswap_trades GROUP BY pool
      HAVING t0 > t_debut + toIntervalHour(1) AND qr0 >= 67.4 AND qr0 < 67.42) g
INNER JOIN pumpfun.pumpswap_trades t ON t.pool = g.pool
WHERE t.received_at >= g.t0 AND t.received_at <= g.t0 + toIntervalMinute(65)
GROUP BY g.pool, g.t0;

SELECT count() AS graduations, round(median(length(serie)),0) AS trades_median_65min
FROM pumpfun.tmp_grad_serie;
SELECT concat(toString(horizon_s), ' s') AS horizon, count() AS n,
  round(median(x),4) AS mediane,
  round(avg(x),4)    AS moyenne,
  round((sum(x)-arraySum(arraySlice(arraySort(groupArray(x)), count()-2)))/(count()-3),4)  AS sans_top3,
  round((sum(x)-arraySum(arraySlice(arraySort(groupArray(x)), count()-9)))/(count()-10),4) AS sans_top10,
  round(100*countIf(x>1)/count(),1)   AS pct_gagnants,
  round(100*countIf(x<0.5)/count(),1) AS pct_pertes_lourdes
FROM (
  SELECT horizon_s,
    (sortie.2 / entree.2) * (1-0.5/entree.3) * (1-0.5/greatest(sortie.3,1)) * 0.994 AS x
  FROM (
    SELECT horizon_s, entree,
      arrayLast(y -> y.1 <= entree.1 + toIntervalSecond(horizon_s), serie) AS sortie
    FROM (
      SELECT serie, arrayFirst(y -> y.1 >= t0 + toIntervalSecond(1), serie) AS entree
      FROM pumpfun.tmp_grad_serie WHERE length(serie) >= 10)
    ARRAY JOIN [15, 30, 60, 120, 180, 300] AS horizon_s
    WHERE entree.2 > 0)
  WHERE sortie.2 > 0)
GROUP BY horizon ORDER BY length(horizon), horizon;
SELECT horizon_min, count() AS n,
  round(median(x),4) AS mediane,
  round(avg(x),4)    AS moyenne,
  round((sum(x)-arraySum(arraySlice(arraySort(groupArray(x)), count()-2)))/(count()-3),4)  AS sans_top3,
  round((sum(x)-arraySum(arraySlice(arraySort(groupArray(x)), count()-9)))/(count()-10),4) AS sans_top10,
  round(100*countIf(x>1)/count(),1)   AS pct_gagnants,
  round(100*countIf(x<0.5)/count(),1) AS pct_pertes_lourdes,
  round(max(x),1) AS maxi
FROM (
  SELECT horizon_min,
    (sortie.2 / entree.2) * (1-0.5/entree.3) * (1-0.5/greatest(sortie.3,1)) * 0.994 AS x
  FROM (
    SELECT horizon_min, entree,
      arrayLast(y -> y.1 <= entree.1 + toIntervalMinute(horizon_min), serie) AS sortie
    FROM (
      SELECT serie, arrayFirst(y -> y.1 >= t0 + toIntervalSecond(1), serie) AS entree
      FROM pumpfun.tmp_grad_serie WHERE length(serie) >= 10)
    ARRAY JOIN [5, 15, 30, 60] AS horizon_min
    WHERE entree.2 > 0)
  WHERE sortie.2 > 0)
GROUP BY horizon_min ORDER BY horizon_min;
