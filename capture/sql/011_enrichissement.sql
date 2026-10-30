-- Tokenomics des tokens suivis, lue sur CoinGecko à chaque relevé : le flottant
-- et le rapport FDV / capitalisation au lancement sont les deux variables que
-- le suivi confronte au rendement.
CREATE TABLE IF NOT EXISTS __DB__.suivi_tokenomics
(
    base      String,
    releve_le DateTime,
    cg_id     String,
    prix      Float64,
    mcap      Float64,
    fdv       Float64,
    circulant Float64,
    total     Float64
)
ENGINE = MergeTree
ORDER BY (base, releve_le)
TTL releve_le + INTERVAL 400 DAY;

-- Annonces de listing publiées par Binance, OKX et Bybit, souvent plusieurs
-- heures avant l'ouverture de la paire.
CREATE TABLE IF NOT EXISTS __DB__.cex_annonces
(
    bourse    LowCardinality(String),
    id        String,
    titre     String,
    url       String,
    publie_le DateTime,
    -- tickers repérés dans le titre, entre parenthèses ou en paire USDT
    tickers   Array(String),
    vu_le     DateTime,
    -- présente dès le premier relevé de cette bourse : jamais alertée
    initiale  UInt8
)
ENGINE = ReplacingMergeTree(vu_le)
ORDER BY (bourse, id);

-- Alertes déjà envoyées, pour n'envoyer chaque événement qu'une fois
CREATE TABLE IF NOT EXISTS __DB__.alertes_envoyees
(
    cle       String,
    envoye_le DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(envoye_le)
ORDER BY cle;
