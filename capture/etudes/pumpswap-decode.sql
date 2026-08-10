-- Décodeur PumpSwap : transforme pumpswap_events (charges utiles brutes) en
-- trades exploitables.
--
--   clickhouse-client --password "$CLICKHOUSE_PASSWORD" -n < etudes/pumpswap-decode.sql
--
-- Structures rétro-conçues sur 4 000 événements réels, puis VÉRIFIÉES par deux
-- contrôles indépendants (voir plus bas). Deux pièges rencontrés :
--
--   1. BuyEvent existe en deux tailles (457 et 472 octets) — le préfixe utilisé
--      ici est stable entre les deux ;
--   2. l'ordre des réserves est INVERSÉ entre achat et vente :
--        BuyEvent  @40 = quote, @48 = base
--        SellEvent @40 = base,  @48 = quote
--      La formule AMM le confirme : quote_out = R_quote x base_in / (R_base + base_in)
--      reproduit le montant réellement reçu à 0,01 % près sur les cas testés.
--
-- Disposition retenue (offsets en octets, u64 little-endian) :
--   @0   timestamp (i64)
--   @8   montant entrant (quote pour un achat, base pour une vente)
--   @40  /  @48   réserves du pool (ordre selon le sens, cf. ci-dessus)
--   @96  (achat) / @104 (vente)   montant réellement reçu par l'utilisateur
--   @112 pool, @144 utilisateur (pubkeys)

CREATE OR REPLACE TABLE pumpfun.pumpswap_trades ENGINE = MergeTree
PARTITION BY toYYYYMMDD(received_at) ORDER BY (pool, received_at) AS
WITH d AS (
  SELECT slot, signature, received_at, base64Decode(payload) AS b,
         toUInt8(CAST(event_name AS String) = 'BuyEvent') AS is_buy
  FROM pumpfun.pumpswap_events
  WHERE CAST(event_name AS String) IN ('BuyEvent','SellEvent')
    AND length(base64Decode(payload)) >= 176)
SELECT
  slot, signature, received_at, is_buy,
  base58Encode(substring(b, 113, 32)) AS pool,
  base58Encode(substring(b, 145, 32)) AS user,
  reinterpretAsInt64(substring(b, 1, 8)) AS event_timestamp,
  if(is_buy = 1, reinterpretAsUInt64(substring(b, 41, 8)), reinterpretAsUInt64(substring(b, 49, 8))) AS quote_reserves,
  if(is_buy = 1, reinterpretAsUInt64(substring(b, 49, 8)), reinterpretAsUInt64(substring(b, 41, 8))) AS base_reserves,
  reinterpretAsUInt64(substring(b, 9, 8)) AS montant_entrant,
  if(is_buy = 1, reinterpretAsUInt64(substring(b, 97, 8)), reinterpretAsUInt64(substring(b, 105, 8))) AS montant_sortant,
  if(base_reserves > 0, (quote_reserves / 1e9) / (base_reserves / 1e6), 0) AS price_sol
FROM d;

-- CONTRÔLE 1 — le prix issu des réserves doit reproduire le prix exécuté.
-- Attendu : ratio médian ~0,99 à l'achat (les réserves sont post-trade) et
-- ~1,00 à la vente, avec des quantiles serrés.
SELECT if(is_buy = 1, 'achat', 'vente') AS sens, count() AS n,
  round(median(prix_execute / price_sol), 4) AS ratio_median,
  round(quantile(0.05)(prix_execute / price_sol), 3) AS p05,
  round(quantile(0.95)(prix_execute / price_sol), 3) AS p95
FROM (
  SELECT is_buy, price_sol,
    if(is_buy = 1, (montant_entrant/1e9)/(montant_sortant/1e6), (montant_sortant/1e9)/(montant_entrant/1e6)) AS prix_execute
  FROM pumpfun.pumpswap_trades
  WHERE price_sol > 0 AND montant_entrant > 0 AND montant_sortant > 0
    AND received_at > now() - INTERVAL 2 HOUR)
GROUP BY sens ORDER BY sens;

-- CONTRÔLE 2 — le produit des réserves doit être quasi constant d'un trade au
-- suivant sur un même pool. Attendu : > 99 %.
SELECT round(100 * countIf(abs(k/prev_k - 1) < 0.02) / count(), 1) AS pct_produit_stable, count() AS n
FROM (
  SELECT quote_reserves/1e9 * base_reserves/1e6 AS k,
         lagInFrame(quote_reserves/1e9 * base_reserves/1e6)
           OVER (PARTITION BY pool ORDER BY received_at, signature) AS prev_k
  FROM pumpfun.pumpswap_trades
  WHERE received_at > now() - INTERVAL 1 HOUR AND base_reserves > 0)
WHERE prev_k > 0;
