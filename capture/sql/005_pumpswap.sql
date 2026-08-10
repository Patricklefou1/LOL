-- PumpSwap : l'AMM de destination des tokens qui graduent.
--
-- Toute l'activité post-graduation s'y déroule. Sans cette table, le point
-- d'entrée « post-graduation » du comparatif de stratégies est structurellement
-- invisible : après migration il ne reste que ~1,6 trade par token sur la
-- bonding curve.
--
-- On archive ici la charge utile brute de chaque event-CPI, pas des champs
-- décodés. Raison : les structures BuyEvent et SellEvent diffèrent et n'ont pas
-- encore été rétro-conçues sur un échantillon suffisant. Conformément au
-- principe de la capture — le brut d'abord, le décodeur ensuite — on collecte
-- dès maintenant ce qui serait définitivement perdu, et on re-décodera.
-- Coût : ~472 octets par événement avant compression, contre ~1 Ko pour une
-- transaction entière.

CREATE TABLE IF NOT EXISTS __DB__.pumpswap_events (
  slot          UInt64,
  signature     String CODEC(ZSTD(3)),
  received_at   DateTime64(3, 'UTC'),
  -- Nom résolu quand le discriminator est connu, vide sinon : un événement
  -- non identifié est archivé plutôt que jeté.
  event_name    LowCardinality(String),
  discriminator FixedString(16),
  payload       String CODEC(ZSTD(3)),
  source        LowCardinality(String) DEFAULT 'grpc'
) ENGINE = MergeTree
PARTITION BY toYYYYMMDD(received_at)
ORDER BY (received_at, signature);
