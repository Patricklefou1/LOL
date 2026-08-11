-- Décodeur PumpSwap — offsets issus de l'IDL Anchor publié on-chain.
--
--   clickhouse-client --password "$CLICKHOUSE_PASSWORD" -n < etudes/pumpswap-decode.sql
--
-- L'IDL se récupère avec `etudes/outils/recuperer-idl.py` : Anchor le publie à
-- une adresse dérivée du programme, compressé en zlib. C'est la source
-- autoritaire — une première version de ce décodeur, rétro-conçue à la main,
-- était fausse sur trois points que l'IDL a tranchés en une minute :
--
--   * @8 n'est PAS le quote mais le base (base_amount_out / base_amount_in) ;
--     le vrai montant quote est à @56, jamais testé jusque-là ;
--   * l'ordre des réserves est identique dans les deux événements — base puis
--     quote — et non inversé comme supposé ;
--   * les tailles 457 et 472 ne sont pas deux structures mais la même, suivie
--     d'un champ `ix_name` de longueur variable. Elles se décodent à l'identique.
--
-- Disposition (offsets en octets) :
--   @0   timestamp                          i64
--   @8   base_amount_out / base_amount_in   u64
--   @16  max_quote_in / min_quote_out       u64   (paramètre utilisateur)
--   @40  pool_base_token_reserves           u64
--   @48  pool_quote_token_reserves          u64
--   @56  quote_amount_in / quote_amount_out u64   (le montant réel)
--   @104 user_quote_amount_in / _out        u64   (net de frais)
--   @112 pool      @144 user      @304 coin_creator      (pubkeys)

CREATE OR REPLACE TABLE pumpfun.pumpswap_trades ENGINE = MergeTree
PARTITION BY toYYYYMMDD(received_at) ORDER BY (pool, received_at) AS
WITH d AS (
  SELECT slot, signature, received_at, base64Decode(payload) AS b,
         toUInt8(CAST(event_name AS String) = 'BuyEvent') AS is_buy
  FROM pumpfun.pumpswap_events
  WHERE CAST(event_name AS String) IN ('BuyEvent','SellEvent')
    AND length(base64Decode(payload)) >= 336)
SELECT
  slot, signature, received_at, is_buy,
  base58Encode(substring(b, 113, 32)) AS pool,
  base58Encode(substring(b, 145, 32)) AS user,
  base58Encode(substring(b, 305, 32)) AS coin_creator,
  reinterpretAsInt64(substring(b, 1, 8))    AS event_timestamp,
  reinterpretAsUInt64(substring(b, 41, 8))  AS base_reserves,
  reinterpretAsUInt64(substring(b, 49, 8))  AS quote_reserves,
  reinterpretAsUInt64(substring(b, 9, 8))   AS base_amount,
  reinterpretAsUInt64(substring(b, 57, 8))  AS quote_amount,
  reinterpretAsUInt64(substring(b, 105, 8)) AS user_quote_amount,
  -- quote en 9 décimales (WSOL), base en 6 (tokens Pump.fun)
  if(base_reserves > 0, (quote_reserves / 1e9) / (base_reserves / 1e6), 0) AS price_sol
FROM d;

-- CONTRÔLE 1 — NON CIRCULAIRE. Entre deux trades consécutifs d'un même pool, la
-- variation des réserves doit égaler le montant du trade. Il relie deux
-- événements distincts, donc il peut échouer : l'ancien décodeur donnait des
-- ratios de 85 à 1 185.
-- Attendu : médiane ≈ 1,00. La dispersion est normale — quand un trade
-- intermédiaire nous échappe (routage, trou de flux), la variation couvre deux
-- trades et le ratio double.
WITH y AS (
  SELECT pool, toFloat64(quote_reserves) AS q, toFloat64(quote_amount) AS montant,
         lagInFrame(toFloat64(quote_reserves))
           OVER (PARTITION BY pool ORDER BY received_at, signature) AS q_prec
  FROM pumpfun.pumpswap_trades
  WHERE received_at > now() - INTERVAL 30 MINUTE AND quote_reserves > 0)
SELECT count() AS n, round(median(abs(q - q_prec) / greatest(montant, 1)), 4) AS ratio_median
FROM y WHERE q_prec > 0 AND montant > 0;

-- CONTRÔLE 2 — le prix d'exécution doit encadrer le prix des réserves dans le
-- bon sens : un achat s'exécute au-dessus du spot, une vente en dessous.
SELECT if(is_buy = 1, 'achat', 'vente') AS sens, count() AS n,
  round(median(prix_exec / price_sol), 4) AS ratio_median
FROM (
  SELECT is_buy, price_sol,
         (toFloat64(quote_amount) / 1e9) / (toFloat64(base_amount) / 1e6) AS prix_exec
  FROM pumpfun.pumpswap_trades
  WHERE received_at > now() - INTERVAL 30 MINUTE
    AND price_sol > 0 AND base_amount > 0 AND quote_amount > 0)
GROUP BY sens ORDER BY sens;
