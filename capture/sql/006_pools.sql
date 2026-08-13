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

-- Orientation du pool. 5 519 pools ont le SOL du côté BASE : leur `price_sol`
-- est alors le prix du SOL libellé dans l'autre token, soit l'inverse de ce
-- qu'on veut. Colonnes ALIAS — calculées à la lecture, aucun stockage, et
-- valables rétroactivement sur les lignes déjà écrites.
--
-- Usage dans une étude :
--   prix  = if(sol_en_base, 1 / price_sol, price_sol)
--   SOL   = if(sol_en_base, base_reserves, quote_reserves) / 1e9
-- Le facteur de décimales que l'inversion déplace est constant par pool : il
-- s'annule dans tout ratio de prix, seul usage qu'en font les études.
ALTER TABLE __DB__.pumpswap_pools ADD COLUMN IF NOT EXISTS
  sol_en_base UInt8 ALIAS base_mint = 'So11111111111111111111111111111111111111112';
ALTER TABLE __DB__.pumpswap_pools ADD COLUMN IF NOT EXISTS
  exploitable UInt8 ALIAS est_sol = 1 OR base_mint = 'So11111111111111111111111111111111111111112';
