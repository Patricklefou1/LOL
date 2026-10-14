-- Relevé des cotations sur six bourses centralisées (`npm run listings`).
--
-- Aucune de ces bourses ne publie d'historique de ses listings : on photographie
-- leur liste de paires spot chaque heure et une paire jamais vue est une
-- cotation. La précision est donc celle du relevé, une heure.
--
-- Une ligne par paire et par bourse. ReplacingMergeTree : la ligne est réécrite
-- une seule fois, quand une paire annoncée devient échangeable.
CREATE TABLE IF NOT EXISTS __DB__.cex_paires
(
    bourse      LowCardinality(String),
    symbole     String,
    -- ticker en majuscules : deux tokens différents peuvent porter le même
    -- ticker sur deux bourses, la jointure par ticker est une approximation
    base        String,
    quote       LowCardinality(String),
    -- premier relevé qui a vu la paire, échangeable ou non
    vu_le       DateTime,
    -- premier relevé où la paire était échangeable : c'est la date de cotation
    ouvert_le   Nullable(DateTime),
    -- date de cotation déclarée par la bourse (OKX listTime, Gate buy_start) :
    -- la seule source d'historique antérieur au premier relevé
    date_bourse Nullable(DateTime),
    -- présente dès le premier relevé de cette bourse : sa date réelle de
    -- cotation est inconnue, elle ne doit jamais compter comme un lancement
    initiale    UInt8,
    maj         DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(maj)
ORDER BY (bourse, symbole);

-- Journal des relevés. Une heure sans relevé réussi sur une bourse est un trou :
-- les cotations de cette heure y seront datées en retard, pas perdues.
CREATE TABLE IF NOT EXISTS __DB__.cex_releves
(
    releve_le DateTime,
    bourse    LowCardinality(String),
    paires    UInt32,
    nouvelles UInt32,
    erreur    String
)
ENGINE = MergeTree
ORDER BY (bourse, releve_le);
