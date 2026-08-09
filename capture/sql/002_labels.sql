-- Phase 2 : provenance des données, labels d'issues, réconciliation des trous

-- Provenance : 'grpc' (capture live), 'rpc_backfill' (réconciliation getBlock), 'bitquery' (backfill historique)
ALTER TABLE __DB__.raw_transactions ADD COLUMN IF NOT EXISTS source LowCardinality(String) DEFAULT 'grpc';
ALTER TABLE __DB__.trades ADD COLUMN IF NOT EXISTS source LowCardinality(String) DEFAULT 'grpc';
ALTER TABLE __DB__.creations ADD COLUMN IF NOT EXISTS source LowCardinality(String) DEFAULT 'grpc';
ALTER TABLE __DB__.completions ADD COLUMN IF NOT EXISTS source LowCardinality(String) DEFAULT 'grpc';

-- Une ligne par token : le résumé de sa vie (recalculé par npm run labels, partition par jour de création)
CREATE TABLE IF NOT EXISTS __DB__.token_summary (
  mint                   String,
  created_day            Date,
  created_at             DateTime64(3, 'UTC'),
  created_slot           UInt64,
  dev                    String,
  name                   String,
  symbol                 String,
  n_trades               UInt32,
  n_buys                 UInt32,
  n_sells                UInt32,
  uniq_traders           UInt32,
  uniq_buyers            UInt32,
  vol_sol                Float64,
  first_price            Float64,
  max_price              Float64,
  max_mult               Float64,
  minutes_to_max         Float32,
  last_trade_at          DateTime64(3, 'UTC'),
  lifespan_min           Float32,
  graduated              UInt8,
  minutes_to_graduation  Nullable(Float32),
  dev_buy_sol            Float64,
  dev_tokens_bought      Float64,
  dev_tokens_sold        Float64,
  dev_sold_fraction      Float32,
  dev_first_sell_minutes Nullable(Float32),
  rug_dev_dump           UInt8,
  snipe_slot0_sol        Float64,
  snipe_slot0_share      Float32,
  snipe_slot0_buyers     UInt16,
  labeled_at             DateTime64(3, 'UTC')
) ENGINE = MergeTree
PARTITION BY created_day
ORDER BY mint;

-- La matrice token × minute × horizon : rendements forward pour les études d'événement.
-- Prix en carry-forward (dernier trade connu) ; les fwd_* au-delà de la fin de série
-- utilisent le dernier prix (plat) — l'illiquidité réelle est traitée par le modèle
-- de coûts des études, pas ici.
CREATE TABLE IF NOT EXISTS __DB__.token_minute (
  mint            String,
  created_day     Date,
  minute_idx      UInt16,
  ts              DateTime('UTC'),
  price           Float64,
  n_buys          UInt16,
  n_sells         UInt16,
  uniq_buyers     UInt16,
  uniq_sellers    UInt16,
  vol_buy_sol     Float32,
  vol_sell_sol    Float32,
  net_flow_sol    Float32,
  real_sol_curve  Float32,
  fwd_ret_1m      Float32,
  fwd_ret_5m      Float32,
  fwd_ret_15m     Float32,
  fwd_ret_60m     Float32,
  fwd_ret_240m    Float32,
  fwd_max_ret_5m   Float32,
  fwd_max_ret_15m  Float32,
  fwd_max_ret_60m  Float32,
  fwd_max_ret_240m Float32
) ENGINE = MergeTree
PARTITION BY created_day
ORDER BY (mint, minute_idx);

-- Journal des réconciliations de trous (npm run reconcile)
CREATE TABLE IF NOT EXISTS __DB__.gap_backfills (
  from_slot     UInt64,
  to_slot       UInt64,
  backfilled_at DateTime64(3, 'UTC'),
  slots_ok      UInt32,
  slots_skipped UInt32,
  txs_recovered UInt32,
  errors        UInt32
) ENGINE = MergeTree
ORDER BY backfilled_at;
