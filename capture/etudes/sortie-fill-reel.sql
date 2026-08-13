-- Signaux, avec le haut du couloir (niveau de reintegration)
CREATE OR REPLACE TABLE pumpfun.tmp_stop_sig ENGINE = MergeTree ORDER BY (pool, m) AS
WITH vivants AS (
  SELECT pool, min(received_at) AS t0 FROM pumpfun.pumpswap_trades GROUP BY pool
  HAVING dateDiff('minute', min(received_at), max(received_at)) >= 120 AND count() >= 200),
mins AS (
  SELECT t.pool AS pool, toUInt16(dateDiff('minute', v.t0, t.received_at)) AS mm,
         max(t.received_at) AS t_fin
  FROM pumpfun.pumpswap_trades t INNER JOIN vivants v ON v.pool = t.pool
  WHERE dateDiff('minute', v.t0, t.received_at) BETWEEN 0 AND 480
  GROUP BY pool, mm)
SELECT s.pool AS pool, s.m AS m, s.p_e AS p_e, s.qr_e AS qr_e, s.h30 AS h30,
       s.haut AS haut, mn.t_fin AS t_entree
FROM pumpfun.tmp_ps_ok s
INNER JOIN mins mn ON mn.pool = s.pool AND mn.mm = s.m + 1
WHERE s.m >= 31 AND s.bas > 0 AND s.haut/s.bas <= 1.10 AND s.tr30 >= 60
  AND s.prix > s.haut*1.01 AND s.p_e > 0 AND s.h30 > 0
  AND s.qr_e >= 5 AND s.qr_e <= 20000;

-- Serie de trades reels des 30 minutes suivant l'entree, horodatee a la ms
CREATE OR REPLACE TABLE pumpfun.tmp_stop_serie ENGINE = MergeTree ORDER BY (pool, m) AS
SELECT g.pool AS pool, g.m AS m, any(g.p_e) AS p_e, any(g.qr_e) AS qr_e,
       any(g.h30) AS h30, any(g.haut) AS haut, any(g.t_entree) AS t_entree,
       arraySort(x -> x.1, groupArray((t.received_at, t.price_sol))) AS serie
FROM pumpfun.tmp_stop_sig g
INNER JOIN pumpfun.pumpswap_trades t ON t.pool = g.pool
WHERE t.received_at > g.t_entree AND t.received_at <= g.t_entree + INTERVAL 30 MINUTE
GROUP BY g.pool, g.m;

SELECT count() AS signaux, round(median(length(serie)),0) AS trades_median_30min,
       round(median(p_e/haut),4) AS distance_au_niveau_reintegration
FROM pumpfun.tmp_stop_serie;

-- Étape 3 — les règles de sortie, mesurées au FILL RÉEL.
-- Le déclenchement se lit sur les trades bruts (486 par fenêtre de 30 min à la
-- médiane), jamais sur la série par minute : un stop se déclenche ET se remplit
-- à l'intérieur d'une minute. Le fill est le premier trade au moins 1 seconde
-- APRÈS le trade déclencheur — on ne peut pas vendre au prix qu'on découvre.
SELECT regle, count() AS n, round(100*countIf(declenche)/count(),1) AS pct_declenche,
  round(median(x),4) AS mediane, round(avg(x),4) AS moyenne,
  round(100*countIf(x>1)/count(),1) AS pct_gagnants,
  round((sum(x)-arraySum(arraySlice(arraySort(groupArray(x)), count()-2)))/(count()-3),4) AS sans_top3
FROM (
  SELECT regle, idx > 0 AS declenche,
    (if(idx = 0, serie[length(serie)].2, serie[fidx].2)/p_e)*(1-0.5/qr_e)*(1-0.5/qr_e)*0.994 AS x
  FROM (
    SELECT regle, p_e, qr_e, serie,
      arrayFirstIndex(y -> y.2 <= seuil, serie) AS idx,
      if(idx=0,0, arrayFirstIndex(y -> y.1 >= serie[idx].1 + toIntervalSecond(1), serie)) AS f0,
      if(idx=0,0, if(f0=0, length(serie), f0)) AS fidx
    FROM pumpfun.tmp_stop_serie
    ARRAY JOIN ['A. sans stop','E. stop -20 %','F. reintegration'] AS regle,
               [0., p_e*0.80, haut] AS seuil
    WHERE length(serie) > 1
      -- retirer ce filtre pour la population complète ; le garder isole l'effet
      -- des règles hors rugs, seul cas où elles pourraient servir
      AND serie[length(serie)].2 / p_e >= 0.5))
GROUP BY regle ORDER BY regle;
