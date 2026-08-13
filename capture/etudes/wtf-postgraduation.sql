-- Hypothèse 20 — trois stratégies à contre-courant après la graduation.
-- Les trois sont mortes. Le fichier est gardé parce que la RAISON de leur mort
-- est une loi générale de ce marché (cf. règle 5 du README).
--
--   1. Acheter les cadavres     : entrer après une chute de 80 %.
--   2. Trier sur la 1re minute  : le pump initial comme signal de danger.
--   3. Attraper la mèche        : entrer sur la chute, sortir en secondes.
--
-- Taille de position calée à 2 % des réserves du pool, pour que les tranches
-- soient comparables entre elles quelle que soit la taille du pool.

-- Signal : premier trade a -80 % du prix de reference, pool encore vivant (>= 3 SOL).
-- Entree au fill reel : premier trade au moins 1 s APRES le declencheur.
CREATE OR REPLACE TABLE pumpfun.tmp_cadavre ENGINE = MergeTree ORDER BY pool AS
SELECT pool, t0, serie, p1, decl, entree
FROM (
  SELECT pool, t0, serie,
    arrayFirst(y -> y.1 >= t0 + toIntervalSecond(1), serie).2 AS p1,
    arrayFirst(y -> y.2 <= p1 * 0.20 AND y.3 >= 3, serie) AS decl,
    arrayFirst(y -> y.1 >= decl.1 + toIntervalSecond(1), serie) AS entree
  FROM pumpfun.tmp_grad_serie WHERE length(serie) >= 50)
WHERE p1 > 0 AND decl.2 > 0 AND entree.2 > 0;

SELECT count() AS signaux,
  round(100*count()/(SELECT count() FROM pumpfun.tmp_grad_serie),1) AS pct_des_graduations,
  round(median(entree.2/decl.2),4) AS qualite_du_fill,
  round(median(entree.3),1) AS reserves_sol_a_l_entree,
  round(median(dateDiff('second', t0, entree.1)),0) AS secondes_apres_graduation
FROM pumpfun.tmp_cadavre;

SELECT concat(toString(h), ' min') AS horizon, count() AS n,
  round(median(x),4) AS mediane, round(avg(x),4) AS moyenne,
  round((sum(x)-arraySum(arraySlice(arraySort(groupArray(x)), count()-2)))/(count()-3),4)  AS sans_top3,
  round((sum(x)-arraySum(arraySlice(arraySort(groupArray(x)), count()-9)))/(count()-10),4) AS sans_top10,
  round(100*countIf(x>1)/count(),1) AS pct_gagnants,
  round(100*countIf(x<0.5)/count(),1) AS pct_pertes_lourdes, round(max(x),1) AS maxi
FROM (
  SELECT h, (arrayLast(y -> y.1 <= entree.1 + toIntervalMinute(h), serie).2 / entree.2)
            * 0.98 * 0.98 * 0.994 AS x
  FROM pumpfun.tmp_cadavre ARRAY JOIN [5, 15, 30] AS h)
WHERE x > 0 GROUP BY h ORDER BY h;
-- WTF : et si le pump initial etait le SIGNAL DE DANGER, pas d'achat ?
-- Hypothese mecanique : un token qui s'envole dans la premiere minute est un
-- token snipe. Le pump EST l'inventaire des snipers, qui devra etre vendu.
-- Un token plat n'a pas de surplomb a ecouler.
SELECT tranche_60s, count() AS n,
  round(median(x30),4) AS mediane_30min, round(avg(x30),4) AS moyenne_30min,
  round((sum(x30)-arraySum(arraySlice(arraySort(groupArray(x30)), count()-2)))/(count()-3),4) AS sans_top3,
  round(100*countIf(x30>1)/count(),1) AS pct_gagnants,
  round(100*countIf(x30<0.5)/count(),1) AS pct_pertes_lourdes
FROM (
  SELECT multiIf(r60 < 0.8,'A. -20 % ou pire', r60 < 1.0,'B. baisse legere',
                 r60 < 1.3,'C. hausse < 30 %', r60 < 2.0,'D. hausse 30-100 %',
                 'E. pump > x2') AS tranche_60s,
    (arrayLast(y -> y.1 <= e60.1 + toIntervalMinute(30), serie).2 / e60.2) * 0.98*0.98*0.994 AS x30
  FROM (
    SELECT serie,
      arrayFirst(y -> y.1 >= t0 + toIntervalSecond(1),  serie) AS e1,
      arrayFirst(y -> y.1 >= t0 + toIntervalSecond(60), serie) AS e60,
      e60.2 / e1.2 AS r60
    FROM pumpfun.tmp_grad_serie WHERE length(serie) >= 50)
  WHERE e1.2 > 0 AND e60.2 > 0)
WHERE x30 > 0 GROUP BY tranche_60s ORDER BY tranche_60s;
SELECT concat(toString(h),' s') AS maintien, count() AS n,
  round(median(x),4) AS mediane, round(avg(x),4) AS moyenne,
  round((sum(x)-arraySum(arraySlice(arraySort(groupArray(x)), count()-2)))/(count()-3),4)  AS sans_top3,
  round((sum(x)-arraySum(arraySlice(arraySort(groupArray(x)), count()-9)))/(count()-10),4) AS sans_top10,
  round(100*countIf(x>1)/count(),1) AS pct_gagnants,
  round(100*countIf(x<0.5)/count(),1) AS pct_pertes_lourdes
FROM (
  SELECT h, (arrayFirst(y -> y.1 >= entree.1 + toIntervalSecond(h), serie).2 / entree.2)
            * 0.98 * 0.98 * 0.994 AS x
  FROM pumpfun.tmp_cadavre ARRAY JOIN [5, 10, 20, 40, 90] AS h)
WHERE x > 0 GROUP BY h ORDER BY h;
