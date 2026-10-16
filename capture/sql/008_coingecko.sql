-- Relevé des tokens référencés par CoinGecko (`npm run listings`, source coingecko).
--
-- Les bourses centralisées ne voient pas les lancements sur DEX. CoinGecko les
-- référence après une vérification manuelle, en général un à trois jours après
-- la création du pool : un token jamais vu dans sa liste est un nouvel ajout.
-- L'adresse de contrat lève l'ambiguïté des tickers que portent deux tokens.
CREATE TABLE IF NOT EXISTS __DB__.cg_tokens
(
    id        String,
    symbole   String,
    nom       String,
    -- {"binance-smart-chain": "0x…", …} tel que renvoyé par CoinGecko
    contrats  String,
    vu_le     DateTime,
    -- présent dès le premier relevé : un token ancien, jamais un ajout
    initiale  UInt8,
    maj       DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(maj)
ORDER BY id;

-- Capitalisation et volume des tokens récemment ajoutés, relevés à chaque
-- passage : au jour de l'ajout ils sont souvent nuls, le seuil du rapport
-- s'applique à la dernière valeur.
CREATE TABLE IF NOT EXISTS __DB__.cg_marches
(
    id        String,
    releve_le DateTime,
    prix      Float64,
    mcap      Float64,
    volume    Float64
)
ENGINE = MergeTree
ORDER BY (id, releve_le)
TTL releve_le + INTERVAL 90 DAY;

CREATE TABLE IF NOT EXISTS __DB__.cg_releves
(
    releve_le DateTime,
    tokens    UInt32,
    nouveaux  UInt32,
    erreur    String
)
ENGINE = MergeTree
ORDER BY releve_le;
