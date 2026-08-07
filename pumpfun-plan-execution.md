# Plan d'exécution — de zéro au premier edge en production

Ce document transforme la méthode (`pumpfun-trouver-un-edge.md`) en plan d'action séquencé, avec pour chaque phase : les tâches, et un **critère de sortie** (« definition of done ») mesurable. Infrastructure cible : bot sous Triton (Yellowstone gRPC).

---

## La prochaine étape, en une phrase

> **Mettre en route la capture de données (gRPC → décodeur → ClickHouse) et la laisser tourner.**

Pourquoi celle-là et aucune autre :
1. **Toute la suite en dépend** — études d'événement, bases propriétaires, shadow bot : tout consomme cette capture.
2. **L'historique ne se rattrape pas** : les tokens morts disparaissent des API publiques. Chaque jour sans capture est un jour de dataset perdu définitivement.
3. Elle **valide l'infra Triton à risque nul** : tu mesures ta latence réelle et la fiabilité du flux avant qu'un euro soit en jeu.
4. Le shadow bot (phase 5) réutilisera **le même flux et le même code** : rien n'est jetable.

---

## Décision à prendre cette semaine : la stack

Recommandation (défaut raisonnable, à ajuster à tes compétences) :

| Couche | Choix recommandé | Pourquoi |
|---|---|---|
| Capture temps réel | **TypeScript** (client officiel `@triton-one/yellowstone-grpc`, décodage via `@coral-xyz/anchor`) | Vélocité de développement, écosystème Solana le plus riche, `jito-ts` disponible pour la phase 6 |
| Alternative | Rust (client `yellowstone-grpc` natif) | Perf maximale — mais ne réécrire le chemin chaud en Rust **que si** la courbe de décroissance du signal l'exige (§ 6.2 du doc edge) |
| Stockage | **ClickHouse** mono-nœud | Standard de fait pour ce débit ; un VPS NVMe 4–8 vCPU / 16 Go suffit longtemps, dans la **même région que l'endpoint Triton** |
| Recherche | **Python** (polars + clickhouse-connect + notebooks) | Outillage statistique |

**Le piège de ce split TS/Python** : implémenter les features deux fois (une fois en recherche, une fois en prod) avec deux définitions qui divergent. Parade : définir les features en SQL ClickHouse partagé, ou dans une lib unique consommée des deux côtés. Décision à acter dès la phase 1.

Budget d'ordre de grandeur (à vérifier, les tarifs bougent) : endpoint Triton selon plan (partagé → dédié), VPS ~30–80 €/mois, Bitquery pour le backfill selon usage.

---

## Phase 1 — Capture minimale viable *(semaines 1–2)* ← **TU ES ICI**

**Tâches, dans l'ordre :**
1. Compte Triton, choix de l'endpoint (même région que ton serveur), **mesure du ping et du lag** dès le premier jour.
2. Souscription gRPC : transactions du programme Pump.fun (`6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`) + slots. Commitment `processed` pour la latence ; réconciliation en `confirmed` pour l'archive (les deux flux, ou re-vérification en aval).
3. **Capture brute d'abord** : archiver les payloads de transactions tels quels dans une table `raw` AVANT d'avoir un décodeur complet. Si ton décodeur a un bug (il en aura), tu re-décodes l'historique au lieu de l'avoir perdu. Le décodage devient un job **rejouable**.
4. Décodeur des événements `Create` / `Trade` / `Complete` (IDL Anchor, discriminators) → extraire par trade : slot, signature, wallet, sens, SOL, tokens, réserves virtuelles après trade, timestamp de réception local.
5. Écriture ClickHouse par lots (~1 s), tables : `raw_transactions`, `creations`, `trades`, `completions`, `sol_transfers` (phase 3), plus une table `capture_health`.
6. Monitoring dès le jour 1 : gaps de slots, reconnexion automatique, **lag de réception** (timestamp local vs slot) en histogramme, alerte si gap > N slots.

**Definition of done :** 48 h de capture continue sans gap ; < 0,1 % de transactions manquantes sur un échantillon réconcilié contre un explorateur ; lag p50/p99 mesuré, loggé, et affiché quelque part que tu regardes.

---

## Phase 2 — Labels et backfill *(semaines 2–3, en parallèle de la fin de phase 1)*

1. Job offline quotidien de **labellisation des issues** par token : multiple maximal atteint depuis chaque minute de vie, temps jusqu'à la mort (volume 5 min < seuil), gradué o/n, rug o/n (dev sell > seuil), type de fin.
2. **Backfill historique** via Bitquery pour donner de la profondeur aux premières études pendant que ta capture s'accumule (en marquant la provenance : la précision slot n'est pas équivalente).

**DoD :** la requête « rendement forward à horizon h depuis l'instant t pour le token X » répond en < 1 s ; la matrice token × temps × horizon est requêtable en masse.

---

## Phase 3 — Bases propriétaires v0 *(semaines 3–4)*

1. **Graphe de financement** : transferts SOL des wallets actifs sur Pump.fun → clusters par ancêtre commun.
2. **Empreintes de devs** : par cluster créateur, historique complet (tokens créés, issues, taux de graduation, taux de rug, habitudes de bundle).
3. **Registre PnL par wallet** : reconstruction du PnL réalisé par wallet sur l'historique → liste smart money (top 1 % persistant) et liste dumb money.

**DoD :** à chaque `Create` reçu, le dossier du dev est disponible en < 500 ms ; à chaque `Trade`, le flag smart/dumb money du wallet est résolu en mémoire.

---

## Phase 4 — Les trois études fondatrices *(semaines 4–6)*

Dans l'ordre du doc edge (§ 10) :
1. **Élimination** : espérance inconditionnelle d'achat à 10 % de courbe vs espérance après checklist anti-rug. L'écart = ton premier edge.
2. **Déciles de devs** : rendement forward conditionné à l'empreinte du déployeur.
3. **Décroissance smart money** : courbe E[r | achat d'élite, délai d] pour d = 0,2 s → 30 s. C'est l'étude qui chiffre ce que Triton t'achète.

**DoD :** un rapport par étude (courbes forward moyenne/médiane/quantiles, baseline appariée, coûts complets, verdict go/no-go) ; le **registre d'hypothèses** est ouvert et tient à jour les échecs aussi.

---

## Phase 5 — Shadow bot *(semaines 6–8)*

1. Moteur de features **incrémental** branché sur le flux live (état par token, mise à jour O(1) par événement).
2. Règles de décision issues des études go de la phase 4.
3. Fills **simulés** réalistes : exécution à slot+1/+2, tip au percentile du moment, impact exact par produit constant, probabilité d'échec.
4. Journal complet : features à l'entrée, signal déclencheur, latences.

**DoD :** 2 semaines de shadow ; PnL simulé cohérent avec le backtest (écart expliqué, pas excusé).

---

## Phase 6 — Micro-réel *(semaines 8+)*

1. Exécuteur : bundles Jito, tip dynamique, simulation d'impact avant envoi, retry borné.
2. Tailles minuscules, plafond par trade, kill switch de drawdown journalier.
3. Attribution par signal en continu.

**DoD :** 300–500 trades réels ; slippage réel ≈ modélisé ; edge net > 0. Sinon : c'est la sélection adverse qui parle → retour phase 4, montée en coût de falsification. Ce n'est pas un échec du plan, c'est le plan qui fonctionne (il t'a coûté des miettes au lieu d'un capital).

---

## Checklist de la semaine en cours

- [ ] Compte Triton ouvert, endpoint choisi, ping/lag mesurés
- [ ] VPS provisionné (même région), ClickHouse installé
- [ ] IDL Pump.fun récupéré, discriminators listés, **10 transactions décodées à la main** pour valider la compréhension du format
- [ ] Subscriber v0 qui archive les transactions **brutes** en continu
- [ ] Monitoring de gaps + reconnexion auto en place
- [ ] Décision de stack actée (et l'endroit unique où vivront les définitions de features)

Règle de conduite pour toute la suite : **la capture ne s'arrête plus jamais** — c'est le seul composant du système qui n'a pas le droit d'avoir un jour de panne, parce que c'est le seul dont les pannes sont irréversibles.
