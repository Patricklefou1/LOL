-- Tickers exclus des événements du relevé : actions, ETF et autres produits de
-- finance traditionnelle que certaines bourses cotent sans les catégoriser
-- (Binance spot, Hyperliquid, MEXC spot).
--
-- S'ajoutent aux règles automatiques du rapport : nom CoinGecko contenant
-- « Tokenized », « bStocks », « xStock » ou « Ondo », et préfixe EQ des actions
-- tokenisées des bourses de rang 2. Pour exclure un ticker à la main :
--   INSERT INTO pumpfun.cex_exclus (base, raison) VALUES ('XYZ', 'action');
CREATE TABLE IF NOT EXISTS __DB__.cex_exclus
(
    base   String,
    raison String,
    maj    DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(maj)
ORDER BY base;

-- Cas relevés dans le rapport du 27/10, que les règles automatiques ne couvrent
-- pas tous. Rejouer la migration ne crée pas de doublon : la clé est le ticker.
INSERT INTO __DB__.cex_exclus (base, raison) VALUES
    ('KSTRB', 'action Binance bStocks'), ('VSTB', 'action Binance bStocks'),
    ('BRKBB', 'action Binance bStocks'), ('BOTB', 'ETF Binance bStocks'),
    ('TMFB', 'ETF Binance bStocks'), ('PENGB', 'action Binance bStocks'),
    ('BBB', 'action Binance bStocks'), ('MDBB', 'action Binance bStocks'),
    ('UVXYB', 'ETF Binance bStocks'),
    ('TAIYOYUDEN', 'action japonaise'), ('FASTRETAILING', 'action japonaise'),
    ('IBKR', 'action'), ('VLO', 'action'),
    ('BMNU', 'ETF'), ('BWET', 'ETF'), ('URNM', 'ETF');
