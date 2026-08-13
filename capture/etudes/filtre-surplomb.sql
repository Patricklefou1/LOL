-- Hypothèse 18 — prédire le rug plutôt que le fuir.
--
-- L'étude 17 a montré qu'aucune sortie ne protège d'un retrait de liquidité.
-- Reste à ne pas entrer. Cinq prédicteurs FIXÉS AVANT MESURE (donc seuil de
-- significativité à p < 0,01 après correction pour cinq tests), tous calculés
-- sur des trades STRICTEMENT antérieurs au signal.
--
-- LIMITE STRUCTURELLE À CONNAÎTRE : les positions issues de la bonding curve
-- sont invisibles pour cette cohorte — ces tokens ont gradué AVANT le début de
-- la capture (médiane : 1 trade de courbe connu). La concentration n'est donc
-- mesurée que sur l'accumulation visible sur l'AMM. Cela s'améliorera
-- mécaniquement à mesure que de nouveaux tokens graduent sous capture.

CREATE OR REPLACE TABLE pumpfun.tmp_pos ENGINE = MergeTree ORDER BY (pool, user) AS
SELECT t.pool AS pool, t.user AS user, any(r.t_ref) AS t_ref,
  sum(if(t.is_buy = 1, toFloat64(t.base_amount), -toFloat64(t.base_amount))) AS net_base,
  min(t.received_at) AS premiere_fois
FROM pumpfun.pumpswap_trades t INNER JOIN pumpfun.tmp_rug r ON r.pool = t.pool
WHERE t.received_at <= r.t_ref
GROUP BY t.pool, t.user;

CREATE OR REPLACE TABLE pumpfun.tmp_pred ENGINE = MergeTree ORDER BY pool AS
SELECT r.pool AS pool, r.rug AS rug,
  greatest(pos.plus_gros, 0) / greatest(etat.base_res, 1) AS concentration,
  toFloat64(pos.nouveaux) / greatest(pos.n_wallets, 1)    AS part_nouveaux,
  pos.n_wallets                                           AS n_wallets,
  flux.net_sol AS flux_net_sol, flux.part_achat AS part_achat,
  flux.createur_vend AS createur_vend
FROM pumpfun.tmp_rug r
INNER JOIN (
  SELECT pool, max(net_base) AS plus_gros, count() AS n_wallets,
         countIf(premiere_fois >= t_ref - toIntervalMinute(30)) AS nouveaux
  FROM pumpfun.tmp_pos GROUP BY pool) pos ON pos.pool = r.pool
INNER JOIN (
  SELECT t.pool AS pool, argMax(toFloat64(t.base_reserves), t.received_at) AS base_res
  FROM pumpfun.pumpswap_trades t INNER JOIN pumpfun.tmp_rug r3 ON r3.pool = t.pool
  WHERE t.received_at <= r3.t_ref GROUP BY t.pool) etat ON etat.pool = r.pool
INNER JOIN (
  SELECT t.pool AS pool,
    (sumIf(toFloat64(t.quote_amount), t.is_buy=1) - sumIf(toFloat64(t.quote_amount), t.is_buy=0))/1e9 AS net_sol,
    sumIf(toFloat64(t.quote_amount), t.is_buy=1) / greatest(sum(toFloat64(t.quote_amount)),1) AS part_achat,
    max(t.user = t.coin_creator AND t.is_buy = 0) AS createur_vend
  FROM pumpfun.pumpswap_trades t INNER JOIN pumpfun.tmp_rug r4 ON r4.pool = t.pool
  WHERE t.received_at <= r4.t_ref AND t.received_at >= r4.t_ref - toIntervalMinute(30)
  GROUP BY t.pool) flux ON flux.pool = r.pool;

SELECT rug, count() AS pools,
  round(median(concentration),4) AS concentration,
  round(median(part_nouveaux),4) AS part_nouveaux,
  round(median(flux_net_sol),2)  AS flux_net_sol,
  round(median(part_achat),4)    AS part_achat,
  round(avg(createur_vend),4)    AS createur_vend,
  round(median(n_wallets),0)     AS n_wallets
FROM pumpfun.tmp_pred GROUP BY rug ORDER BY rug;
