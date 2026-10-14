-- Relevé des cotations spot et perps sur six bourses centralisées (`npm run listings`).
--
-- Aucune de ces bourses ne publie d'historique complet de ses listings : on
-- photographie leurs listes de paires spot et de contrats perpétuels chaque
-- heure, et une paire jamais vue est une cotation. La précision est donc celle
-- du relevé, une heure, sauf quand la bourse déclare elle-même la date.
--
-- Une ligne par paire, par marché et par bourse. ReplacingMergeTree : la ligne
-- est réécrite une seule fois, quand une paire annoncée devient échangeable.
-- `marche` est dans la clé : BTCUSDT existe en spot et en perp sur Binance.
CREATE TABLE IF NOT EXISTS __DB__.cex_paires
(
    bourse      LowCardinality(String),
    marche      LowCardinality(String),
    symbole     String,
    -- ticker en majuscules, multiplicateurs retirés (1000PEPE -> PEPE) : deux
    -- tokens différents peuvent porter le même ticker sur deux bourses, la
    -- jointure par ticker est une approximation
    base        String,
    quote       LowCardinality(String),
    -- premier relevé qui a vu la paire, échangeable ou non
    vu_le       DateTime,
    -- premier relevé où la paire était échangeable
    ouvert_le   Nullable(DateTime),
    -- date de cotation déclarée par la bourse (OKX listTime, Gate buy_start,
    -- Binance onboardDate, Bybit launchTime, KuCoin firstOpenDate) : prioritaire
    -- sur ouvert_le, et seule source d'historique antérieur au premier relevé
    date_bourse Nullable(DateTime),
    -- présente dès le premier relevé de cette source : sans date de bourse, elle
    -- est réputée ancienne et ne compte jamais comme un lancement
    initiale    UInt8,
    -- démarrée en pré-marché (OKX, Bybit : les seules API qui le déclarent)
    premarche   UInt8 DEFAULT 0,
    maj         DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(maj)
ORDER BY (bourse, marche, symbole);

-- Journal des relevés. Une heure sans relevé réussi sur une source est un trou :
-- les cotations de cette heure y seront datées en retard, pas perdues.
CREATE TABLE IF NOT EXISTS __DB__.cex_releves
(
    releve_le DateTime,
    bourse    LowCardinality(String),
    marche    LowCardinality(String),
    paires    UInt32,
    nouvelles UInt32,
    erreur    String
)
ENGINE = MergeTree
ORDER BY (bourse, marche, releve_le);
