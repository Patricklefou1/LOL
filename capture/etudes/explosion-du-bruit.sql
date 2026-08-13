-- Hypothèse 22 — l'explosion du bruit après consolidation.
--
-- Née d'une observation sur FROGGY (The Fomo Frog,
-- 7SNuFkbD7aVs5LMM6DWsSFTq4zsXNxYuD8Hdsp1Kpump) le 10 août : quatre heures de
-- calme entre 11h30 et 15h30 UTC, puis l'activité quadruple à 15h45 et le prix
-- fait ×8,8 en 45 minutes.
--
-- TUÉE. Le signal perd à toutes les largeurs de consolidation testées, et perd
-- PLUS que l'achat au hasard. La raison est dans le fichier README : l'explosion
-- du bruit n'est pas un précurseur, c'est l'événement lui-même.

-- Hypothese 22 — l'explosion du bruit apres une longue consolidation.
-- Activite des 15 dernieres minutes comparee a son rythme des 2 heures
-- precedentes. Tout est calcule sur du passe strict ; entree a la minute
-- suivante, comme partout ailleurs.
CREATE OR REPLACE TABLE pumpfun.tmp_bruit ENGINE = MergeTree ORDER BY (pool, m) AS
SELECT pool, m, prix, reserve,
  sum(activite) OVER r15  AS act15,
  sum(activite) OVER r120 AS act120,
  min(prix) OVER r120 AS bas120, max(prix) OVER r120 AS haut120,
  lagInFrame(prix, 15) OVER f AS prix_avant15,
  leadInFrame(prix, 1)    OVER f AS p_e,
  leadInFrame(reserve, 1) OVER f AS qr_e,
  leadInFrame(prix, 31)   OVER f AS s30,
  leadInFrame(prix, 61)   OVER f AS s60
FROM pumpfun.tmp_ps_dense
WINDOW r15  AS (PARTITION BY pool ORDER BY m ROWS BETWEEN 14 PRECEDING AND CURRENT ROW),
       r120 AS (PARTITION BY pool ORDER BY m ROWS BETWEEN 134 PRECEDING AND 15 PRECEDING),
       f    AS (PARTITION BY pool ORDER BY m ROWS BETWEEN 15 PRECEDING AND 61 FOLLOWING);

SELECT regime, concat('+', toString(k),' min') AS horizon, count() AS n,
  round(median(x),4) AS mediane, round(avg(x),4) AS moyenne,
  round((sum(x)-arraySum(arraySlice(arraySort(groupArray(x)), count()-2)))/(count()-3),4) AS sans_top3,
  round((sum(x)-arraySum(arraySlice(arraySort(groupArray(x)), count()-9)))/(count()-10),4) AS sans_top10,
  round(100*countIf(x>1)/count(),1) AS pct_gagnants,
  round(100*countIf(x<0.5)/count(),1) AS pct_pertes_lourdes
FROM (
  SELECT 'A. explosion du bruit' AS regime, k, (s/p_e)*(1-0.5/qr_e)*(1-0.5/qr_e)*0.994 AS x
  FROM pumpfun.tmp_bruit ARRAY JOIN [30,60] AS k, [s30,s60] AS s
  WHERE m >= 136 AND act120 >= 120 AND qr_e >= 5 AND p_e > 0 AND s > 0
    AND act15 >= 4 * (act120 / 8)          -- le bruit quadruple
    AND prix > prix_avant15 * 1.02         -- et il pousse vers le haut
    AND bas120 > 0 AND haut120/bas120 <= 1.6   -- apres une vraie consolidation
  UNION ALL
  SELECT 'B. baseline apparie', k, (s/p_e)*(1-0.5/qr_e)*(1-0.5/qr_e)*0.994
  FROM pumpfun.tmp_bruit ARRAY JOIN [30,60] AS k, [s30,s60] AS s
  WHERE m >= 136 AND act120 >= 120 AND qr_e >= 5 AND p_e > 0 AND s > 0)
GROUP BY regime, k ORDER BY regime, k;
