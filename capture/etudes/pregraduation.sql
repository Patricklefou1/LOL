-- Étude d'événement : entrée au remplissage de courbe, sortie dans la poussée
-- de graduation.
--
-- Exécution :
--   clickhouse-client --password "$CLICKHOUSE_PASSWORD" -n < etudes/pregraduation.sql
--
-- Hypothèse testée : sur une bonding curve, le prix est une fonction
-- déterministe des réserves. Le rendement entre un niveau de remplissage et la
-- graduation est donc connu d'avance ; le seul aléa est d'y parvenir. La
-- stratégie est un pari de probabilité, pas de prédiction de prix.
--
-- Les deux règles du README s'appliquent :
--   1. aucune constante de courbe — les réserves virtuelles sont lues par trade,
--      y compris pour le calcul d'impact ;
--   2. les graduations instantanées (migration sans accumulation de SOL, 27 % du
--      total) sont exclues explicitement de la population.

-- Étape 1 — population et points d'entrée/sortie, pour quatre seuils.
CREATE OR REPLACE TABLE pumpfun.etude_pg ENGINE = MergeTree ORDER BY (seuil, mint) AS
WITH
  -- Seuil de graduation mesuré sur les tokens réellement gradués par
  -- remplissage de courbe (72,8 % des complétions).
  SEUIL_GRAD AS (SELECT 85.0054e9 AS s),
  -- Règle n°2 : une complétion à moins de 5 SOL de réserves réelles est une
  -- migration instantanée, pas un remplissage. Non tradable.
  vraie_grad AS (
    SELECT c.mint AS mint
    FROM pumpfun.completions c
    INNER JOIN pumpfun.trades t ON t.signature = c.signature AND t.mint = c.mint
    GROUP BY c.mint
    HAVING max(t.real_sol_reserves) >= 5e9),
  -- 45 min de recul pour que l'horizon de sortie soit clos.
  pop AS (
    SELECT mint, min(received_at) AS t0
    FROM pumpfun.creations
    GROUP BY mint
    HAVING t0 < now() - INTERVAL 45 MINUTE),
  niveaux AS (SELECT arrayJoin([0.40, 0.50, 0.60, 0.75]) AS seuil)
SELECT
  n.seuil AS seuil,
  p.mint  AS mint,
  p.mint IN (SELECT mint FROM vraie_grad) AS gradue,
  argMinIf(t.price_sol,            t.received_at, t.real_sol_reserves >= n.seuil * (SELECT s FROM SEUIL_GRAD)) AS p_in,
  argMinIf(t.virtual_sol_reserves, t.received_at, t.real_sol_reserves >= n.seuil * (SELECT s FROM SEUIL_GRAD)) AS v_in,
  minIf(t.received_at,             t.real_sol_reserves >= n.seuil * (SELECT s FROM SEUIL_GRAD))                AS t_in,
  argMaxIf(t.price_sol,            t.received_at, t.real_sol_reserves <  (SELECT s FROM SEUIL_GRAD) * 0.995)   AS p_out,
  argMaxIf(t.virtual_sol_reserves, t.received_at, t.real_sol_reserves <  (SELECT s FROM SEUIL_GRAD) * 0.995)   AS v_out
FROM pop p
CROSS JOIN niveaux n
INNER JOIN pumpfun.trades t ON t.mint = p.mint
GROUP BY seuil, mint, gradue
HAVING p_in > 0 AND v_in > 0 AND t_in > toDateTime64(0, 3);

-- Étape 2 — plus-bas (déclenchement du stop) et prix de repli à 15 min.
CREATE OR REPLACE TABLE pumpfun.etude_pg2 ENGINE = MergeTree ORDER BY (seuil, mint) AS
SELECT
  e.seuil AS seuil, e.mint AS mint, e.gradue AS gradue,
  e.p_in AS p_in, e.v_in AS v_in, e.p_out AS p_out, e.v_out AS v_out, e.t_in AS t_in,
  min(t.price_sol) AS p_min,
  argMaxIf(t.price_sol, t.received_at, t.received_at <= e.t_in + INTERVAL 15 MINUTE) AS p_15
FROM pumpfun.etude_pg e
INNER JOIN pumpfun.trades t ON t.mint = e.mint
WHERE t.received_at BETWEEN e.t_in AND e.t_in + INTERVAL 30 MINUTE
GROUP BY seuil, mint, gradue, p_in, v_in, p_out, v_out, t_in;

-- Étape 3 — espérance nette par seuil et par taille de position.
--
-- Rendement net = brut x (1 - impact entrée) x (1 - impact sortie) x frais.
-- L'impact d'une position de taille S dans une réserve virtuelle V vaut S/V par
-- sens sur une courbe à produit constant : le prix d'exécution moyen est
-- (1 + S/V) fois le spot. À ne pas confondre avec le *mouvement* de prix, qui
-- vaut 2S/V — c'est la confusion qui avait faussé une première estimation.
-- Frais protocole : 1 % à l'aller, 1 % au retour.
WITH t AS (
  SELECT seuil, taille,
    multiIf(p_min <= p_in * 0.8, 0.80,              -- stop à -20 %
            gradue AND p_out > 0, p_out / p_in,     -- sortie dans la poussée
            p_15 / p_in)                            -- ni stop ni graduation
    * (1 - taille / (v_in  / 1e9))
    * (1 - taille / (v_out / 1e9))
    * 0.98 AS net
  FROM pumpfun.etude_pg2
  CROSS JOIN (SELECT arrayJoin([0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9]) AS taille) AS tailles
  WHERE v_out > 0)
SELECT
  seuil,
  taille AS taille_sol,
  round(avg(net), 4)                  AS esperance_nette,
  round(100 * (avg(net) - 1), 2)      AS edge_pct,
  round(taille * (avg(net) - 1), 5)   AS gain_sol_par_trade,
  count()                             AS n
FROM t
GROUP BY seuil, taille
ORDER BY seuil, taille;

-- Étape 4 — robustesse n°1 : l'edge survit-il au retrait des meilleurs trades ?
-- Un edge qui meurt ici est une loterie, pas un edge.
WITH s AS (
  SELECT multiIf(p_min <= p_in * 0.8, 0.80, gradue AND p_out > 0, p_out / p_in, p_15 / p_in)
         * (1 - 0.25 / (v_in / 1e9)) * (1 - 0.25 / (v_out / 1e9)) * 0.98 AS x
  FROM pumpfun.etude_pg2 WHERE seuil = 0.4 AND v_out > 0)
SELECT
  (SELECT round(avg(x), 4) FROM s) AS avec_tout,
  (SELECT round(avg(x), 4) FROM (SELECT x FROM s ORDER BY x DESC LIMIT 18446744073709551615 OFFSET 3))  AS sans_top3,
  (SELECT round(avg(x), 4) FROM (SELECT x FROM s ORDER BY x DESC LIMIT 18446744073709551615 OFFSET 10)) AS sans_top10,
  (SELECT round(avg(x), 4) FROM (SELECT x FROM s ORDER BY x DESC LIMIT 18446744073709551615 OFFSET 25)) AS sans_top25;

-- Étape 5 — robustesse n°2 : stabilité dans le temps. Un edge réel décline
-- progressivement ; un artefact disparaît hors de la fenêtre où on l'a vu.
SELECT
  toStartOfInterval(t_in, INTERVAL 3 HOUR) AS tranche,
  count() AS n,
  round(avg(multiIf(p_min <= p_in * 0.8, 0.80, gradue AND p_out > 0, p_out / p_in, p_15 / p_in)
        * (1 - 0.25 / (v_in / 1e9)) * (1 - 0.25 / (v_out / 1e9)) * 0.98), 4) AS esperance_nette
FROM pumpfun.etude_pg2
WHERE seuil = 0.4 AND v_out > 0
GROUP BY tranche
ORDER BY tranche;
