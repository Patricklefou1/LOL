# Guide pas-à-pas : mise en production de la capture (Phase 1)

Runbook complet, à dérouler dans l'ordre, du VPS OVH nu jusqu'à la capture qui tourne en service permanent. Chaque étape indique **quoi faire, comment vérifier que c'est bon, et quoi faire si ça casse**. Temps actif total : ~1 h 30 (hors délais d'ouverture du compte Triton).

> Les étapes 1→2 et 4→8 ne dépendent **pas** de Triton : lance la demande d'endpoint (étape 3) en premier, et avance sur le reste pendant l'attente. Seule l'étape 9 (premier lancement) a besoin du token.

---

## Étape 1 — Le VPS OVH *(15 min)*

- [ ] **1.1 Commander/vérifier le gabarit** : 4–8 vCPU, **16 Go de RAM**, disque NVMe **200 Go+**. Chez OVH, un VPS de gamme intermédiaire suffit ; évite les entrées de gamme à 4–8 Go de RAM.
- [ ] **1.2 OS** : Ubuntu 24.04 LTS (ou 22.04).
- [ ] **1.3 Région** : datacenter le plus proche de l'endpoint Triton visé. Endpoint européen (Amsterdam/Francfort) → Gravelines, Roubaix ou Strasbourg.
- [ ] **1.4 Se connecter** : `ssh ubuntu@IP_DU_VPS` (ou l'utilisateur fourni par OVH).

**Vérification :**
```bash
nproc && free -h && df -h /
# attendu : ≥ 4 CPU, ≥ 15 Gi de RAM, ≥ 180 G libres
```

---

## Étape 2 — Sécuriser le VPS *(10 min)*

- [ ] **2.1 Mise à jour** :
```bash
sudo apt update && sudo apt upgrade -y
```
- [ ] **2.2 Pare-feu — seul SSH ouvert** :
```bash
sudo ufw allow OpenSSH && sudo ufw enable
sudo ufw status   # attendu : OpenSSH ALLOW, rien d'autre
```
- [ ] **2.3 (Recommandé)** Si tu te connectes par clé SSH : désactive l'authentification par mot de passe (`PasswordAuthentication no` dans `/etc/ssh/sshd_config`, puis `sudo systemctl restart ssh`). **Ne fais ça qu'après avoir vérifié que ta clé fonctionne.**

---

## Étape 3 — Le compte Triton et l'endpoint *(à lancer en premier — délai variable)*

- [ ] **3.1** Va sur le site de Triton One et ouvre un compte / contacte-les pour un plan avec **Dragon's Mouth (Yellowstone gRPC)** sur **mainnet**, région Europe si ton VPS est en Europe.
- [ ] **3.2** Récupère les deux informations dont le module a besoin :
  - l'**URL de l'endpoint** (forme typique : `https://xxxx.rpcpool.com:443`),
  - le **x-token** d'authentification.
- [ ] **3.3** Depuis le VPS, vérifie la proximité réseau :
```bash
ping -c 5 xxxx.rpcpool.com   # idéalement < 10–20 ms
```

> **Plan B si Triton traîne** : le module utilise le protocole Yellowstone standard — n'importe quel fournisseur compatible (Helius LaserStream, Shyft, InstantNodes…) fonctionne avec le même code, seuls `GRPC_ENDPOINT` et `GRPC_X_TOKEN` changent. Tu peux démarrer la capture chez l'un et migrer chez Triton ensuite sans rien perdre.

---

## Étape 4 — Node.js 22 *(5 min)*

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
```

**Vérification :** `node -v` → `v22.x`, `npm -v` → présent.

---

## Étape 5 — ClickHouse *(10 min)*

```bash
sudo apt-get install -y apt-transport-https ca-certificates curl gnupg
curl -fsSL https://packages.clickhouse.com/gpg/clickhouse-key.gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/clickhouse-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/clickhouse-keyring.gpg] https://packages.clickhouse.com/deb stable main" \
  | sudo tee /etc/apt/sources.list.d/clickhouse.list
sudo apt-get update
sudo apt-get install -y clickhouse-server clickhouse-client
```

- [ ] Pendant l'installation, un **mot de passe pour l'utilisateur `default`** est demandé : choisis-le fort et **note-le** (il ira dans `.env` à l'étape 7).
- [ ] Démarrage :
```bash
sudo systemctl enable --now clickhouse-server
```

**Vérification :**
```bash
clickhouse-client --password
# taper le mot de passe, puis : SELECT 1;  → doit répondre 1
```

**Sécurité** : ne touche pas à `listen_host` — par défaut ClickHouse n'écoute que sur localhost, c'est exactement ce qu'on veut. Pour requêter depuis ton poste plus tard : `ssh -L 8123:localhost:8123 ubuntu@IP_DU_VPS` puis `http://localhost:8123` côté local.

---

## Étape 6 — Cloner le dépôt et installer le module *(5–10 min)*

```bash
sudo mkdir -p /opt/pumpfun && sudo chown $USER /opt/pumpfun
cd /opt/pumpfun
git clone https://github.com/Patricklefou1/LOL.git
cd LOL
git checkout claude/pumpfun-trading-strategy-data-ga4oju
cd capture
npm install
```

> **Si le dépôt est privé**, le clone demandera une authentification : crée sur GitHub un *fine-grained Personal Access Token* limité à ce dépôt en lecture seule (Settings → Developer settings → Fine-grained tokens), puis :
> ```bash
> git config --global credential.helper store
> git clone https://github.com/Patricklefou1/LOL.git   # username : Patricklefou1, password : le token
> ```

**Vérification :** `npm run typecheck` → se termine sans erreur.

---

## Étape 7 — Configuration `.env` *(5 min)*

```bash
cp .env.example .env
nano .env
```

À remplir :

| Variable | Valeur |
|---|---|
| `GRPC_ENDPOINT` | l'URL Triton de l'étape 3.2 (avec `https://` et le port) |
| `GRPC_X_TOKEN` | le x-token de l'étape 3.2 |
| `COMMITMENT` | `processed` (laisser tel quel) |
| `CLICKHOUSE_URL` | `http://localhost:8123` (laisser tel quel) |
| `CLICKHOUSE_USER` | `default` |
| `CLICKHOUSE_PASSWORD` | le mot de passe de l'étape 5 |
| `CLICKHOUSE_DATABASE` | `pumpfun` |
| `CAPTURE_RAW` | `1` |

- [ ] Protéger le fichier : `chmod 600 .env`

---

## Étape 8 — Créer les tables *(2 min)*

```bash
npm run migrate
# attendu : "[migrate] 7 instructions appliquées sur http://localhost:8123 (base pumpfun)"
```

**Vérification :**
```bash
clickhouse-client --password -q "SHOW TABLES FROM pumpfun"
# attendu : capture_gaps, completions, creations, raw_transactions, slots, trades
```

---

## Étape 9 — Premier lancement en direct *(10 min)*

```bash
npm run dev
```

**Ce que tu dois voir :**
1. `[grpc] connecté à https://… (processed)` en quelques secondes ;
2. toutes les 30 s, une ligne JSON de santé avec `tx_per_s` **> 0** (Pump.fun est actif en permanence — des dizaines à des centaines de tx/s selon l'heure) ;
3. `gaps_total: 0`, `sink_insert_errors: 0`, `sink_dropped: 0`.

**Vérifications en base** (dans un second terminal SSH, après ~2 min) :
```sql
-- clickhouse-client --password puis :
SELECT count() FROM pumpfun.trades;                     -- doit croître à chaque exécution
SELECT * FROM pumpfun.creations ORDER BY received_at DESC LIMIT 3;
SELECT signature, mint, is_buy, sol_amount/1e9 AS sol
FROM pumpfun.trades ORDER BY received_at DESC LIMIT 5;
```
- [ ] **Spot-check** : copie une `signature` et vérifie-la sur solscan.io — le mint, le sens et le montant doivent correspondre.

**Si ça casse :**

| Symptôme | Cause probable | Remède |
|---|---|---|
| Erreur d'authentification / `UNAUTHENTICATED` | x-token faux ou pas activé | revérifier le token dans le dashboard Triton |
| Timeout de connexion | URL/port faux, ou endpoint d'une autre région | revérifier l'URL exacte ; tester `ping` |
| `[sink] échec insertion` en boucle | mot de passe ClickHouse faux dans `.env` | corriger `CLICKHOUSE_PASSWORD` |
| `decode_miss_total` qui grimpe vite | le format des événements a changé | me le signaler : on corrige le décodeur puis on **re-décode depuis `raw_transactions`** — rien n'est perdu |
| Aucune donnée mais connecté | filtre/commitment | vérifier `COMMITMENT=processed` dans `.env` |

Arrête avec `Ctrl+C` (le tampon est flushé proprement) une fois validé.

---

## Étape 10 — Passer en service permanent *(10 min)*

```bash
npm run build
sudo useradd -r -s /usr/sbin/nologin pumpfun || true
sudo chown -R pumpfun:pumpfun /opt/pumpfun/LOL/capture
sudo tee /etc/systemd/system/pumpfun-capture.service > /dev/null <<'UNIT'
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
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now pumpfun-capture
```

**Vérification :**
```bash
systemctl status pumpfun-capture      # attendu : active (running)
journalctl -u pumpfun-capture -f      # les lignes de santé défilent
sudo reboot                            # test du vrai monde : au retour du VPS…
systemctl status pumpfun-capture      # …le service doit être reparti tout seul
```

À partir d'ici : **la capture ne s'arrête plus jamais volontairement.**

---

## Étape 11 — Les premières 48 heures *(5 min, 2–3 fois par jour)*

- [ ] Regarder la ligne de santé : `journalctl -u pumpfun-capture -n 3 --no-pager`
  - `gaps_total` stable (idéalement 0), `reconnects_total` bas, `sink_dropped = 0`, `decode_miss_total` quasi nul, `lag_ms_p99` stable.
- [ ] Surveiller le disque : `df -h /` (le brut consomme ~1–3 Go/jour).

---

## Étape 12 — Valider la Definition of Done *(15 min, après 48 h)*

Exécuter les requêtes de la section « Vérifier la Definition of Done » de `capture/README.md` :

- [ ] Débit par minute **continu** sur 48 h (pas de trous de plusieurs minutes) ;
- [ ] `capture_gaps` : zéro trou inexpliqué (les reconnexions loggées expliquent les leurs) ;
- [ ] Spot-check de **10 signatures** contre solscan : 10/10 correctes ;
- [ ] Taux de graduation observé cohérent (créations 24 h vs complétions 24 h : de l'ordre du pour-cent).

**Quand ces quatre cases sont cochées, la Phase 1 est terminée.** Signale-le-moi et je construis la Phase 2 : le job de labellisation des issues (multiple max, mort, graduation, rug par token), le backfill Bitquery, et la réconciliation RPC des trous enregistrés dans `capture_gaps`.

---

## Récapitulatif du chemin critique

```
[3] Demande endpoint Triton  ──────────────┐  (en parallèle, dès maintenant)
[1] VPS OVH → [2] Sécurisation             │
→ [4] Node → [5] ClickHouse                │
→ [6] Clone + install → [7] .env ◄─────────┘  (le token arrive ici)
→ [8] Tables → [9] Premier lancement + spot-check
→ [10] systemd → [11] 48 h de surveillance → [12] DoD ✔ → Phase 2
```
