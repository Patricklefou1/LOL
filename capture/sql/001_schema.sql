CREATE DATABASE IF NOT EXISTS __DB__;

-- Archive brute rejouable : si le décodeur a un bug, on re-décode depuis ici
CREATE TABLE IF NOT EXISTS __DB__.raw_transactions (
  slot          UInt64,
  signature     String,
  received_at   DateTime64(3, 'UTC'),
  is_failed     UInt8,
  payload       String CODEC(ZSTD(3))
) ENGINE = MergeTree
PARTITION BY toYYYYMMDD(received_at)
ORDER BY (slot, signature);

CREATE TABLE IF NOT EXISTS __DB__.creations (
  slot          UInt64,
  signature     String,
  received_at   DateTime64(3, 'UTC'),
  mint          String,
  bonding_curve String,
  user          String,
  creator       String,
  name          String,
  symbol        String,
  uri           String
) ENGINE = MergeTree
PARTITION BY toYYYYMMDD(received_at)
ORDER BY (mint, slot);

CREATE TABLE IF NOT EXISTS __DB__.trades (
  slot                   UInt64,
  signature              String,
  received_at            DateTime64(3, 'UTC'),
  mint                   String,
  user                   String,
  is_buy                 UInt8,
  sol_amount             UInt64,
  token_amount           UInt64,
  event_timestamp        Int64,
  virtual_sol_reserves   UInt64,
  virtual_token_reserves UInt64,
  real_sol_reserves      UInt64,
  real_token_reserves    UInt64,
  price_sol              Float64
) ENGINE = MergeTree
PARTITION BY toYYYYMMDD(received_at)
ORDER BY (mint, slot, signature);

CREATE TABLE IF NOT EXISTS __DB__.completions (
  slot            UInt64,
  signature       String,
  received_at     DateTime64(3, 'UTC'),
  mint            String,
  user            String,
  bonding_curve   String,
  event_timestamp Int64
) ENGINE = MergeTree
PARTITION BY toYYYYMMDD(received_at)
ORDER BY (mint, slot);

-- Flux de slots : l'horloge on-chain, sert à la détection de trous et au lag
CREATE TABLE IF NOT EXISTS __DB__.slots (
  slot        UInt64,
  status      Int8,
  received_at DateTime64(3, 'UTC')
) ENGINE = MergeTree
PARTITION BY toYYYYMMDD(received_at)
ORDER BY slot;

-- Trous détectés dans le flux (à réconcilier par RPC getBlock en phase 2)
CREATE TABLE IF NOT EXISTS __DB__.capture_gaps (
  from_slot   UInt64,
  to_slot     UInt64,
  detected_at DateTime64(3, 'UTC'),
  reason      String
) ENGINE = MergeTree
ORDER BY detected_at;
