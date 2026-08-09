# Capture Pump.fun — Phase 1 du plan d'exécution

Capture en continu du programme Pump.fun (`6EF8rre…`) via **Triton Yellowstone gRPC** vers **ClickHouse** : créations, trades, complétions de courbe, flux de slots, transactions brutes rejouables, et monitoring de trous.

## Prérequis

- Node.js ≥ 20
- Un endpoint Triton (Yellowstone gRPC) + x-token
- ClickHouse accessible (local ou VPS — même région que l'endpoint Triton)

## Mise en route

```bash
cd capture
npm install
cp .env.example .env      # renseigner GRPC_ENDPOINT, GRPC_X_TOKEN, CLICKHOUSE_*
npm run migrate           # crée la base et les tables (idempotent)
npm run dev               # démarre la capture (ou: npm run build && npm start)
```

En production : lancer sous systemd/pm2 avec redémarrage automatique. Le process gère déjà la reconnexion gRPC (backoff exponentiel) et le flush propre sur SIGINT/SIGTERM.

## Ce qui est capturé

| Table | Contenu |
|---|---|
| `creations` | Événements `CreateEvent` : mint, bonding curve, créateur, nom/symbole/URI |
| `trades` | Événements `TradeEvent` : wallet, sens, montants, **réserves virtuelles et réelles après trade**, prix spot calculé |
| `completions` | Événements `CompleteEvent` (graduation) |
| `slots` | Flux de slots — l'horloge on-chain, référence de temps de toute la recherche |
| `raw_transactions` | Payload complet normalisé (bytes en base64, ZSTD) — **rejouable** si le décodeur évolue |
| `capture_gaps` | Trous de slots détectés, à réconcilier par RPC en phase 2 |
| `tx_costs` | Contexte d'exécution par transaction : frais, unités de calcul, priority fee, tip Jito, échec et code d'erreur décodé — le **modèle de coûts** mesuré sur le marché réel |
| `sol_transfers` | Transferts SOL des instructions System (transactions réussies uniquement) — socle du **graphe de financement** : bundles, wallets snipers financés, tips |

### Ce que `tx_costs` permet de mesurer

On ne peut pas retrancher des coûts qu'on n'a jamais observés. Cette table donne, sur le marché réel : la distribution des priority fees payées par les autres, les tips Jito du moment (~1 % des transactions en portent un), et le taux d'échec par instruction.

Deux résultats à connaître avant de lire les chiffres, tous deux liés au filtre `accountInclude` qui matche la *référence* au compte du programme, pas son invocation :

- **~35 % du flux capturé n'invoque jamais Pump.fun** (`invoked_pump = 0`) — des bots tiers qui référencent le compte. Ils ne sont pas stockés par défaut (`CAPTURE_COSTS_FOREIGN=0`), seulement comptés dans `foreign_per_s`.
- **~94 % des transactions capturées échouent**, mais c'est trompeur : l'écrasante majorité sont ces mêmes bots tiers qui ratent leurs propres gardes. Les vraies instructions Pump.fun échouent à **6–11 %** (`Buy` 8,1 %, `Sell` 6,4 %) — c'est ça, le coût de la course au slippage.

Les transactions échouées paient leurs frais (elles restent dans `tx_costs`) mais ne déplacent aucun lamport : leurs transferts sont donc exclus de `sol_transfers`, sans quoi le graphe de financement contiendrait des arêtes qui n'ont jamais existé.

Le décodage lit les événements Anchor via **event-CPI** (inner instructions du programme), avec repli sur les logs `Program data:` — les logs seuls sont tronqués sous charge. Les discriminators sont calculés à l'exécution (`sha256("event:<Nom>")[0..8]`), pas codés en dur. Les versions du programme qui ajoutent des champs en fin d'événement (creator, fees…) sont tolérées : le préfixe stable est parsé, le reste ignoré.

## Monitoring

Une ligne JSON de santé est émise toutes les 30 s :

```json
{"t":"…","slot":…,"tx_per_s":"…","trades_per_s":"…","creates_per_s":"…",
 "gaps_total":0,"reconnects_total":0,"decode_miss_total":0,
 "lag_ms_p50":…,"lag_ms_p99":…,"sink_buffered":0,"sink_dropped":0,"sink_insert_errors":0}
```

À surveiller : `gaps_total` (trous de flux), `decode_miss_total` (tx du programme sans événement décodé — si ça monte, le format a changé : corriger le décodeur puis **re-décoder depuis `raw_transactions`**), `sink_dropped` (pertes par saturation du tampon, jamais silencieuses), `lag_ms_p99`.

## Vérifier la Definition of Done de la phase 1

48 h de capture continue, puis :

```sql
-- Débit par minute (doit être continu, sans trous de plusieurs minutes)
SELECT toStartOfMinute(received_at) AS m, count() AS trades
FROM pumpfun.trades WHERE received_at > now() - INTERVAL 1 HOUR
GROUP BY m ORDER BY m;

-- Trous détectés
SELECT count() AS gaps, sum(to_slot - from_slot + 1) AS slots_manques
FROM pumpfun.capture_gaps WHERE detected_at > now() - INTERVAL 48 HOUR;

-- Créations vs complétions (taux de graduation observé)
SELECT
  (SELECT count() FROM pumpfun.creations WHERE received_at > now() - INTERVAL 24 HOUR) AS creations_24h,
  (SELECT count() FROM pumpfun.completions WHERE received_at > now() - INTERVAL 24 HOUR) AS graduations_24h;

-- Spot-check : comparer 10 signatures récentes avec un explorateur
SELECT signature, slot, mint, is_buy, sol_amount / 1e9 AS sol
FROM pumpfun.trades ORDER BY received_at DESC LIMIT 10;
```

Critères : zéro gap non expliqué, < 0,1 % d'écart sur l'échantillon réconcilié, `lag_ms_p99` stable, `decode_miss_total` proche de zéro (les instructions du programme qui n'émettent pas d'événement — création de comptes, etc. — peuvent en produire un peu : vérifier la nature des tx concernées via `raw_transactions` avant de s'alarmer).

## Phase 2 — Labellisation des issues et réconciliation

### `npm run labels` — la matrice de recherche

Produit, pour chaque token créé un jour J (par défaut **J-4**, pour que les 72 h de vie + horizons soient clos) :

- **`token_summary`** (1 ligne/token) : volumes, prix max et multiple, durée de vie, graduation, comportement du dev (achats, ventes, `dev_sold_fraction`, `rug_dev_dump`), snipe au slot de création (`snipe_slot0_share`, `snipe_slot0_buyers`).
- **`token_minute`** (1 ligne/token/minute, 72 h max) : prix carry-forward, flux par minute (achats/ventes, acheteurs/vendeurs uniques, net flow, remplissage de courbe) et **rendements forward** `fwd_ret_{1,5,15,60,240}m` + `fwd_max_ret_{5,15,60,240}m` — la matrice token × temps × horizon des études d'événement.

```bash
npm run labels                        # labellise J-4
npm run labels -- --day 2026-08-10    # un jour précis
npm run labels -- --from 2026-08-05 --to 2026-08-12   # une plage
```

Relançable sans risque : la partition du jour est remplacée (idempotent). En cron quotidien :
`15 6 * * * cd /opt/pumpfun/LOL/capture && npm run labels >> labels.log 2>&1`

Conventions à connaître pour les études : prix **carry-forward** (un token mort reste à son dernier prix → les `fwd_*` post-mortem valent ~0 ; l'illiquidité réelle se traite dans le modèle de coûts) ; le « dev » est le wallet `user` du Create ; `rug_dev_dump` = dev qui revend ≥ 80 % de ses tokens avec première vente < 24 h (les ventes via wallets tiers relèvent des clusters, phase 3).

Exemple d'étude en une requête (espérance inconditionnelle à 30 min de vie, l'étude n°1 du plan) :

```sql
SELECT quantile(0.5)(fwd_max_ret_60m) AS mediane_max_60m,
       avg(fwd_ret_60m) AS moyenne_60m, count() AS n
FROM pumpfun.token_minute WHERE minute_idx = 30;
```

### `npm run reconcile` — reboucher les trous

Nécessite `RPC_URL` dans `.env` (l'endpoint HTTP du plan Triton convient — la latence est sans importance ici).

```bash
npm run reconcile                     # rejoue les trous de capture_gaps via getBlock (finalized)
npm run reconcile -- --limit-slots 2000   # borne le budget RPC du run
npm run reconcile -- --verify 200     # DoD : échantillonne 200 slots capturés et mesure le taux de tx manquantes
```

Les transactions récupérées passent par le **même décodeur** que la capture et sont insérées dans les mêmes tables avec `source='rpc_backfill'` (dédoublonnage par signature au préalable). Chaque trou traité est journalisé dans `gap_backfills` ; les trous > 3000 slots (panne longue) sont signalés pour traitement séparé. Le backfill historique pré-capture (Bitquery) reste optionnel et sera outillé si besoin — si la capture tourne dès maintenant, il n'est pas nécessaire.

## Déploiement sur un VPS OVH

OVHcloud n'offre pas de ClickHouse managé (leur offre « Public Cloud Databases » couvre PostgreSQL, MySQL, MongoDB, Kafka, OpenSearch…, pas ClickHouse). Ce n'est pas un problème : ClickHouse est open-source et s'auto-héberge très bien sur un VPS — c'est le montage prévu ici, capture et base sur la même machine.

### 1. Choix du VPS

- **Gabarit** : 4–8 vCPU, 16 Go de RAM, disque NVMe. ClickHouse est à l'aise à partir de 8 Go ; en dessous de 4 Go il souffre.
- **Région** : choisis le datacenter OVH **le plus proche de ton endpoint Triton** et vérifie au ping (< 10–20 ms idéalement). Les validateurs Solana et les endpoints des fournisseurs sont concentrés en Europe (Amsterdam/Francfort) et aux US — un VPS OVH à Gravelines/Roubaix/Strasbourg convient bien pour un endpoint européen.
- **Disque** : la table `raw_transactions` est le poste principal — ordre de grandeur de 1 à 3 Go/jour compressé ZSTD (dépend de l'activité de Pump.fun). Prévois 200 Go+ ou surveille ; les partitions journalières permettent de purger le brut ancien si besoin (`ALTER TABLE … DROP PARTITION`), les tables décodées restant petites.

### 2. Installer ClickHouse (Ubuntu/Debian)

```bash
sudo apt-get install -y apt-transport-https ca-certificates curl gnupg
curl -fsSL https://packages.clickhouse.com/gpg/clickhouse-key.gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/clickhouse-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/clickhouse-keyring.gpg] https://packages.clickhouse.com/deb stable main" \
  | sudo tee /etc/apt/sources.list.d/clickhouse.list
sudo apt-get update
sudo apt-get install -y clickhouse-server clickhouse-client   # définir le mot de passe de `default` quand demandé
sudo systemctl enable --now clickhouse-server
clickhouse-client --password   # sanity check : SELECT 1
```

Sécurité :
- **Ne pas exposer ClickHouse sur Internet.** Par défaut il n'écoute que sur localhost — garde ça (la capture tourne sur la même machine). N'ajoute jamais `listen_host: 0.0.0.0` ; pour requêter depuis ton poste, passe par un tunnel SSH : `ssh -L 8123:localhost:8123 user@vps`.
- Mets un mot de passe à l'utilisateur `default` (proposé à l'installation) et reporte-le dans `.env`.
- Pare-feu minimal : `ufw allow ssh && ufw enable` (rien d'autre d'ouvert).

### 3. Lancer la capture en service systemd

```bash
sudo useradd -r -m -s /usr/sbin/nologin pumpfun
sudo mkdir -p /opt/pumpfun && sudo chown pumpfun /opt/pumpfun
# en tant que pumpfun : cloner le repo dans /opt/pumpfun, puis
cd /opt/pumpfun/LOL/capture && npm install && cp .env.example .env  # remplir .env
npm run migrate && npm run build
```

`/etc/systemd/system/pumpfun-capture.service` :

```ini
[Unit]
Description=Capture Pump.fun (Triton gRPC -> ClickHouse)
After=network-online.target clickhouse-server.service
Wants=network-online.target

[Service]
User=pumpfun
WorkingDirectory=/opt/pumpfun/LOL/capture
ExecStart=/usr/bin/env node dist/index.js
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pumpfun-capture
journalctl -u pumpfun-capture -f    # suivre la ligne de santé toutes les 30 s
```

`Restart=always` + la reconnexion gRPC interne = la capture survit aux redémarrages du VPS, aux coupures réseau et aux incidents de l'endpoint. Les trous éventuels sont enregistrés dans `capture_gaps` pour la réconciliation de phase 2.

## Notes de conception

- **L'horloge de référence est le slot**, pas l'horloge murale : toutes les études de la phase 4 se font en temps-slot (~400 ms), ce qui rend la recherche indépendante du jitter de réception.
- **`raw_transactions` d'abord** : tout bug de décodeur est récupérable tant que le brut est là. Désactivable via `CAPTURE_RAW=0` si le disque devient une contrainte (déconseillé au début).
- Commitment `processed` par défaut : latence minimale, au prix de rares slots de forks abandonnés — acceptables pour la capture, la réconciliation `confirmed` arrive en phase 2.
