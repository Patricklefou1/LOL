-- Hypothèse 16 : la liquidité discrimine le réveil après consolidation.
--
-- Née d'une objection juste : retirer les extrêmes d'une loi de puissance retire
-- le mécanisme, pas le bruit. La bonne question n'est pas « la moyenne survit-elle
-- au trim » mais « qu'ont ces tokens en commun ».
--
-- Exclusion préalable : 23 pools dont le quote n'est pas du SOL (réserves de
-- 306 710 à 54 653 490, taille médiane de transaction 5 122 unités). Leurs
-- rendements restent valides — les unités s'annulent dans un ratio de prix —
-- mais le filtre de liquidité et le modèle d'impact sont libellés en SOL.
-- Exclusion justifiée par les unités, jamais par le résultat.

SELECT quintile, count() AS n,
  round(min(qr_e),0)  AS sol_min,
  round(max(qr_e),0)  AS sol_max,
  round(median(x),4)  AS mediane,
  round(100*countIf(x>1)/count(),1) AS pct_gagnants,
  countIf(x>3)        AS extremes,
  round(avgIf(x, x<=3),4) AS moyenne_hors_queue  -- le « grind », queue exclue
FROM (
  SELECT ntile(5) OVER (ORDER BY qr_e) AS quintile, qr_e,
         -- impact d'entrée et de sortie pour 0,5 SOL, puis 0,6 % de frais
         (h30/p_e) * (1-0.5/qr_e) * (1-0.5/qr_e) * 0.994 AS x
  FROM pumpfun.tmp_ps_ok
  WHERE m >= 31                 -- au moins 30 min d'historique de range
    AND bas > 0 AND haut/bas <= 1.10   -- couloir de 10 %
    AND tr30 >= 60              -- pool réellement actif pendant le range
    AND prix > haut*1.01        -- cassure d'au moins 1 %
    AND p_e > 0 AND h30 > 0
    AND qr_e >= 5 AND qr_e <= 20000    -- pools libellés en SOL uniquement
)
GROUP BY quintile ORDER BY quintile;
