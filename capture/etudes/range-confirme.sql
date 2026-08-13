-- Hypothese 23 — le range CONFIRME, sur quatre durees.
-- 30 minutes est un PLANCHER, pas une duree fixe : FROGGY consolidait 4 heures.
-- Une touche = une minute passee a moins de 2 % d'une borne. Toutes les fenetres
-- sont strictement anterieures a la minute de decision.
CREATE OR REPLACE TABLE pumpfun.tmp_osc ENGINE = MergeTree ORDER BY (pool, m) AS
SELECT pool, m, prix, p_e, qr_e, h30, h60,
  arrayMin(f30) AS bas30, arrayMax(f30) AS haut30, arraySum(a30) AS tr30,
  arrayCount(x -> x <= arrayMin(f30)*1.02, f30) AS tb30,
  arrayCount(x -> x >= arrayMax(f30)*0.98, f30) AS th30,
  arrayMin(f60) AS bas60, arrayMax(f60) AS haut60, arraySum(a60) AS tr60,
  arrayCount(x -> x <= arrayMin(f60)*1.02, f60) AS tb60,
  arrayCount(x -> x >= arrayMax(f60)*0.98, f60) AS th60,
  arrayMin(f120) AS bas120, arrayMax(f120) AS haut120, arraySum(a120) AS tr120,
  arrayCount(x -> x <= arrayMin(f120)*1.02, f120) AS tb120,
  arrayCount(x -> x >= arrayMax(f120)*0.98, f120) AS th120,
  arrayMin(f240) AS bas240, arrayMax(f240) AS haut240, arraySum(a240) AS tr240,
  arrayCount(x -> x <= arrayMin(f240)*1.02, f240) AS tb240,
  arrayCount(x -> x >= arrayMax(f240)*0.98, f240) AS th240
FROM (
  SELECT pool, toUInt16(i-1) AS m, px[i] AS prix,
    px[i+1] AS p_e, rs[i+1] AS qr_e, px[i+31] AS h30, px[i+61] AS h60,
    arraySlice(px, i-30, 30)  AS f30,  arraySlice(ac, i-30, 30)  AS a30,
    if(i > 60,  arraySlice(px, i-60, 60),   [px[i]]) AS f60,
    if(i > 60,  arraySlice(ac, i-60, 60),   [toUInt32(0)]) AS a60,
    if(i > 120, arraySlice(px, i-120, 120), [px[i]]) AS f120,
    if(i > 120, arraySlice(ac, i-120, 120), [toUInt32(0)]) AS a120,
    if(i > 240, arraySlice(px, i-240, 240), [px[i]]) AS f240,
    if(i > 240, arraySlice(ac, i-240, 240), [toUInt32(0)]) AS a240
  FROM (
    SELECT pool,
      groupArrayInsertAt(toFloat64(0), 481)(prix, m)    AS px,
      groupArrayInsertAt(toFloat64(0), 481)(reserve, m) AS rs,
      groupArrayInsertAt(toUInt32(0), 481)(toUInt32(activite), m) AS ac
    FROM pumpfun.tmp_ps_dense GROUP BY pool)
  ARRAY JOIN range(32, 420) AS i
  WHERE px[i] > 0 AND px[i+1] > 0 AND px[i+31] > 0)
WHERE arrayMin(f30) > 0 AND qr_e >= 5;

SELECT count() AS lignes, uniqExact(pool) AS pools FROM pumpfun.tmp_osc;
