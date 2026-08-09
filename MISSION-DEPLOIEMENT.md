# Mission de déploiement — à exécuter par Claude Code sur le VPS

> Ce fichier est la mission de la session Claude Code qui tourne sur le VPS.
> Utilisateur : tape simplement dans Claude « Lis MISSION-DEPLOIEMENT.md et exécute la mission étape par étape. »

## Contexte

- Machine : VPS OVH (Ubuntu), c'est la machine de production de la capture.
- Dépôt : `/opt/pumpfun/LOL`, branche `claude/pumpfun-trading-strategy-data-ga4oju`.
- Objectif : dérouler les **étapes 5 à 10** de `pumpfun-guide-pas-a-pas.md` pour mettre la capture Pump.fun en service permanent.
- Références : `pumpfun-guide-pas-a-pas.md` (le runbook, avec les critères de réussite) et `capture/README.md` (le module).

## Mission

0. Commence par `git pull origin claude/pumpfun-trading-strategy-data-ga4oju` pour être à jour, puis lis les deux documents de référence.
0bis. **Étape 2 du runbook (sécurisation, non faite)** : `sudo apt update && sudo apt upgrade -y`, puis `sudo ufw allow OpenSSH && sudo ufw enable` et vérifie `ufw status`. Le système signale un redémarrage requis (nouveau kernel) : ne redémarre pas maintenant — le test de reboot en fin de mission s'en chargera.
1. **Étape 5 — ClickHouse** : installe via le dépôt apt officiel. Au moment où l'installation demande le mot de passe de l'utilisateur `default`, demande à l'utilisateur d'en choisir un. Vérifie `SELECT 1` avec `clickhouse-client --password`. Ne modifie pas `listen_host` (localhost par défaut, c'est voulu).
2. **Étape 6 — Module** : dans `capture/`, `npm install` puis `npm run typecheck` (doit passer sans erreur).
3. **Étape 7 — Configuration** : `cp .env.example .env`, puis demande à l'utilisateur les trois valeurs Triton (`GRPC_ENDPOINT`, `GRPC_X_TOKEN`, `RPC_URL`) et le mot de passe ClickHouse. Écris-les **uniquement dans `.env`** (jamais dans un log, un commit ou une réponse), puis `chmod 600 .env`.
4. **Étape 8 — Tables** : `npm run migrate`. Vérifie avec `SHOW TABLES FROM pumpfun` que les tables existent, **y compris `token_summary`, `token_minute` et `gap_backfills`** (migration 002).
5. **Étape 9 — Premier lancement** : `npm run dev`. Vérifie dans l'ordre : message `[grpc] connecté`, puis 2–3 lignes de santé avec `tx_per_s > 0`, `sink_insert_errors: 0`, `sink_dropped: 0`. Fais les vérifications SQL du runbook (les compteurs croissent, dernières créations visibles) et donne à l'utilisateur **3 signatures récentes** de `pumpfun.trades` pour un spot-check sur solscan.io. Arrête ensuite proprement avec Ctrl+C.
6. **Étape 10 — Service permanent** : `npm run build`, crée l'utilisateur système `pumpfun`, applique le `chown`, installe l'unité systemd `pumpfun-capture` (contenu exact dans le runbook), `systemctl enable --now`, puis montre `systemctl status` et les premières lignes de santé du `journalctl`.
7. **Test de reboot** : propose à l'utilisateur de faire `sudo reboot` — en le prévenant que sa connexion SSH (et cette session tmux/Claude) sera coupée : après le redémarrage, il se reconnecte et vérifie lui-même `systemctl status pumpfun-capture` (attendu : `active (running)` sans intervention). Ce test valide la survie aux maintenances OVH.

## Contrainte disque de ce VPS (important)

Le disque fait ~38 Go au total : c'est peu pour `raw_transactions` (~1–3 Go/jour). Conduite à tenir :
- déploie normalement avec `CAPTURE_RAW=1` (le brut est vital tant que le décodeur n'est pas éprouvé) ;
- ajoute une surveillance : signale à l'utilisateur que `df -h /` doit être vérifié tous les 2–3 jours ;
- explique-lui les deux options pour la suite : **augmenter le disque du VPS** chez OVH (recommandé), ou une fois le décodeur validé sur plusieurs jours, **purger les partitions brutes anciennes** (`ALTER TABLE pumpfun.raw_transactions DROP PARTITION 'AAAAMMJJ'` — partitions journalières `toYYYYMMDD`, garder ~7 jours glissants) ; les tables décodées, elles, restent petites.

## Règles de conduite

- Vérifie le **critère de réussite** de chaque étape (ils sont dans le runbook) avant de passer à la suivante.
- Si `decode_miss_total` grimpe rapidement, si la connexion gRPC échoue, ou si quoi que ce soit ne colle pas avec le runbook : **arrête-toi et produis un diagnostic précis** (message d'erreur exact, étape, contexte) au lieu de contourner. Le décodeur se corrige côté dépôt et le brut se re-décode — rien ne se perd tant que la table `raw_transactions` se remplit.
- Ne désactive jamais une vérification pour « faire passer » une étape.
- À la fin, résume : état du service, débits observés, et tout écart par rapport au runbook.
