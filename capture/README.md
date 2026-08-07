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

## Notes de conception

- **L'horloge de référence est le slot**, pas l'horloge murale : toutes les études de la phase 4 se font en temps-slot (~400 ms), ce qui rend la recherche indépendante du jitter de réception.
- **`raw_transactions` d'abord** : tout bug de décodeur est récupérable tant que le brut est là. Désactivable via `CAPTURE_RAW=0` si le disque devient une contrainte (déconseillé au début).
- Commitment `processed` par défaut : latence minimale, au prix de rares slots de forks abandonnés — acceptables pour la capture, la réconciliation `confirmed` arrive en phase 2.
