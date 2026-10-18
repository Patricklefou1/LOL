-- Suivi des tokens lancés (`npm run listings`) : prix, financement, intérêt
-- ouvert et volume, relevés chaque heure pendant 35 jours après le lancement.
--
-- But : mesurer sur l'historique ce que deviennent les lancements à J+1, J+7 et
-- J+30, au lieu de raisonner au cas par cas. Une ligne par token, source et
-- relevé ; les sources sont les tickers groupés des bourses, un appel chacune.
CREATE TABLE IF NOT EXISTS __DB__.suivi_lancements
(
    base        String,
    releve_le   DateTime,
    bourse      LowCardinality(String),
    marche      LowCardinality(String),
    prix        Float64,
    -- par période de financement de la bourse (souvent 8 h, parfois 1 h ou 4 h)
    financement Nullable(Float64),
    oi_usd      Nullable(Float64),
    volume_usd  Nullable(Float64)
)
ENGINE = MergeTree
ORDER BY (base, releve_le, bourse, marche)
TTL releve_le + INTERVAL 400 DAY;
