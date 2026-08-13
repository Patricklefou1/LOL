-- Identité des pools PumpSwap.
--
-- Sans les mints, rien ne distingue un pool libellé en SOL d'un pool libellé en
-- autre chose. Ces derniers ont faussé trois études : leurs réserves lues comme
-- des SOL donnaient des « 54 millions de SOL », et un pool dont le côté base est
-- vidé voit son prix exploser sans qu'on puisse rien y vendre.
--
-- Table à part, et non deux colonnes sur `pumpswap_trades` : le mapping est
-- statique par pool, le dupliquer sur 47 millions de lignes coûterait 3 Go pour
-- 32 000 valeurs distinctes.
--
-- Alimentée par deux sources qui se recoupent : `npm run pools` (lecture RPC du
-- compte Pool) et la capture en direct (comptes 3 et 4 de l'instruction).
CREATE TABLE IF NOT EXISTS __DB__.pumpswap_pools
(
    pool         String,
    base_mint    String,
    quote_mint   String,
    coin_creator String,
    -- vrai si le quote est WSOL : la seule population où les réserves se lisent
    -- en SOL et où le modèle d'impact a un sens
    est_sol      UInt8,
    source       LowCardinality(String) DEFAULT 'rpc',
    updated_at   DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY pool
SETTINGS index_granularity = 8192;
