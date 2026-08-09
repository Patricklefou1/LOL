-- Phase 3 — bases propriétaires.
--
-- Trois tables dérivées, reconstruites intégralement à chaque exécution de
-- `npm run profiles` : ce sont des agrégats, pas de la capture. Elles portent
-- les deux signaux les plus chers à falsifier du référentiel (historique de
-- graduation d'un dev, track record PnL d'un wallet) plus les clusters qui
-- relient les identités jetables.

-- Registre PnL par wallet. Une "position" = un couple (wallet, mint).
-- Elle est dite close quand le wallet a revendu ≥ 99 % des tokens achetés :
-- seules les positions closes entrent dans le PnL réalisé, les positions
-- ouvertes seraient valorisées à un prix que la courbe ne donnerait pas.
CREATE TABLE IF NOT EXISTS __DB__.wallet_pnl (
  wallet           String,
  n_positions      UInt32,
  n_closed         UInt32,
  n_win            UInt32,
  win_rate         Float32,
  buys_sol         Float64,
  sells_sol        Float64,
  realized_sol     Float64,
  net_sol          Float64,
  median_multiple  Float32,
  first_seen       DateTime,
  last_seen        DateTime,
  computed_at      DateTime
) ENGINE = MergeTree
ORDER BY wallet;

-- Empreintes de devs. Le dev est le `creator` de l'événement Create, avec repli
-- sur `user` pour les versions du programme qui ne le portaient pas.
CREATE TABLE IF NOT EXISTS __DB__.dev_profiles (
  dev                    String,
  n_tokens               UInt32,
  n_graduated            UInt32,
  graduation_rate        Float32,
  n_rug_dump             UInt32,
  rug_rate               Float32,
  dev_buy_sol            Float64,
  dev_sell_sol           Float64,
  median_sec_first_sell  Int32,
  modal_launch_hour      UInt8,
  median_min_between     Float32,
  first_seen             DateTime,
  last_seen              DateTime,
  computed_at            DateTime
) ENGINE = MergeTree
ORDER BY dev;

-- Clusters de wallets par ancêtre commun dans le graphe de financement.
-- `cluster_id` est le wallet le plus anciennement vu de la composante connexe.
-- Les hubs (exchanges, routeurs, payeurs de frais mutualisés) sont exclus du
-- graphe avant le calcul : sans ça, une seule adresse d'infrastructure fusionne
-- tout le réseau en une composante géante et le signal disparaît.
CREATE TABLE IF NOT EXISTS __DB__.wallet_clusters (
  wallet       String,
  cluster_id   String,
  cluster_size UInt32,
  degree       UInt32,
  computed_at  DateTime
) ENGINE = MergeTree
ORDER BY (cluster_id, wallet);
