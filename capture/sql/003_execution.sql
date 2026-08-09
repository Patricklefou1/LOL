-- Contexte d'exécution et flux SOL.
--
-- Deux besoins de la phase 4 que la capture v1 ne couvrait pas :
--   1. le modèle de coûts (§ 6.1 de la méthode) — on ne peut pas retrancher des
--      coûts qu'on n'a jamais mesurés : priority fees réellement payées par les
--      autres, tips Jito du moment, taux de transactions échouées ;
--   2. le graphe de financement — socle des empreintes de devs et des clusters
--      de wallets, les deux signaux les plus chers à falsifier du référentiel.

CREATE TABLE IF NOT EXISTS __DB__.tx_costs (
  slot                  UInt64,
  signature             String CODEC(ZSTD(3)),
  received_at           DateTime64(3, 'UTC'),
  is_failed             UInt8,
  -- Étiquette décodée du TransactionError (ex. `custom:6002`) et octets bruts :
  -- si la table des variantes bincode bouge, l'historique reste re-décodable.
  err                   LowCardinality(String),
  err_raw               String CODEC(ZSTD(3)),
  failed_program        LowCardinality(String),
  fee_payer             String CODEC(ZSTD(3)),
  fee_lamports          UInt64,
  compute_units         UInt32,
  cu_limit              UInt32,
  cu_price_micro        UInt64,
  priority_fee_lamports UInt64,
  jito_tip_lamports     UInt64,
  -- Le filtre gRPC `accountInclude` matche aussi les transactions qui se
  -- contentent de *référencer* le compte du programme sans jamais l'invoquer
  -- (~35 % du flux observé). Par défaut elles ne sont pas stockées ; le drapeau
  -- reste pour les runs où CAPTURE_COSTS_FOREIGN=1.
  invoked_pump          UInt8,
  pump_instructions     Array(LowCardinality(String)),
  mint                  String CODEC(ZSTD(3)),
  n_instructions        UInt16,
  source                LowCardinality(String) DEFAULT 'grpc'
) ENGINE = MergeTree
PARTITION BY toYYYYMMDD(received_at)
ORDER BY (received_at, signature);

-- Transferts SOL extraits des instructions System des transactions capturées.
-- Uniquement des transactions *réussies* : dans une transaction échouée, aucun
-- lamport n'a bougé — les y lire inventerait des arêtes de financement.
-- Portée : ce qui se passe *dans* les transactions touchant Pump.fun — bundles,
-- financement des wallets snipers, tips. L'ascendance complète d'un wallet
-- (financé depuis un exchange hors Pump.fun) se résout à la demande par RPC.
CREATE TABLE IF NOT EXISTS __DB__.sol_transfers (
  slot        UInt64,
  signature   String CODEC(ZSTD(3)),
  received_at DateTime64(3, 'UTC'),
  ix_index    UInt16,
  from_wallet String CODEC(ZSTD(3)),
  to_wallet   String CODEC(ZSTD(3)),
  lamports    UInt64,
  kind        LowCardinality(String),
  is_jito_tip UInt8,
  source      LowCardinality(String) DEFAULT 'grpc'
) ENGINE = MergeTree
PARTITION BY toYYYYMMDD(received_at)
ORDER BY (from_wallet, to_wallet, received_at);
