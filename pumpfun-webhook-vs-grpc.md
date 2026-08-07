# Webhooks vs Triton (Yellowstone gRPC) — avantages, inconvénients, et la troisième voie

Question : remplacer Triton (flux Yellowstone gRPC) par des **webhooks** (type Helius Enhanced Webhooks / QuickNode Streams). Ce document compare les deux, mesure l'impact sur chaque phase du plan et chaque famille d'edge, et montre pourquoi le dilemme est en réalité un **spectre à quatre niveaux**.

## 0. Clarification préalable : webhook ≠ WebSocket

Les deux se confondent souvent, et la réponse diffère :

- **Webhook** : le fournisseur vous **pousse un HTTP POST** sur un endpoint public à vous, à chaque événement qui matche votre filtre. Pas de connexion permanente ; c'est le fournisseur qui vous appelle.
- **WebSocket** : **vous** ouvrez une connexion permanente vers le fournisseur (ex. `logsSubscribe` RPC standard, ou PumpPortal) et recevez le flux dedans. Pas d'endpoint public à exposer.
- **gRPC Geyser (Triton/Yellowstone)** : connexion permanente aussi, mais branchée directement sur le plugin Geyser d'un validateur — le chemin le plus court entre l'événement on-chain et votre process.

Ce document traite le webhook au sens strict, et positionne le WebSocket comme voie intermédiaire.

---

## 1. Mécanique : ce que le webhook change concrètement

Chaîne de latence gRPC : `validateur → plugin Geyser → votre stream → votre process` (~50–300 ms, jitter faible).

Chaîne de latence webhook : `validateur → infra du fournisseur → matching de filtre → file d'attente → requête HTTP sortante → votre serveur web → votre process` (~1–5 s typiquement, **jitter élevé**, pics bien pires en congestion — précisément les moments où tout se joue sur Pump.fun).

## 2. Tableau comparatif

| Critère | Webhook | Triton gRPC | Commentaire |
|---|---|---|---|
| **Latence** | ~1–5 s, jitter fort | ~50–300 ms, jitter faible | Facteur ~10× ; le jitter est aussi grave que la moyenne (il rend la latence non modélisable) |
| **Ordre des événements** | Non garanti (POST concurrents, retries) | Quasi ordonné par le flux | En webhook, il faut ré-ordonner par slot vous-même |
| **Détection des trous** | Faible : pas de flux de slots, un événement manqué est **silencieux** | Forte : stream de slots → gap détectable déterministiquement | Le point le plus sous-estimé ; une capture pleine de trous silencieux empoisonne toute la recherche |
| **Doublons** | Fréquents (retries HTTP) | Rares (reconnexions) | Dédup par signature obligatoire dans les deux cas, vitale en webhook |
| **Débit supportable** | Conçu pour surveiller des comptes, pas pour le **firehose** d'un programme entier (des centaines de tx/s sur Pump.fun) ; limites fournisseur | Conçu exactement pour ça | Un webhook sur tout le programme Pump.fun teste les limites du produit |
| **Données accessibles** | Transactions (parfois enrichies) ; comptes limités ; **pas de flux de slots** | Transactions + mises à jour des comptes `bonding_curve` + slots | Les réserves de courbe en continu et l'horloge slot manquent au webhook |
| **Coût** | Inclus dans des plans à quelques dizaines d'€/mois | Endpoint dédié : centaines à > 1 000 €/mois (partagé : intermédiaire) | **L'avantage réel du webhook : le prix** |
| **Complexité opérationnelle** | Serveur HTTP simple, pas de gestion de stream ; mais endpoint **public** à exposer, sécuriser (header d'auth), et qui doit répondre vite sous rafales | Client de stream, reconnexions, backpressure — plus de code, pas d'exposition publique | Avantage simplicité au webhook au démarrage, qui s'inverse dès qu'on traite les rafales et les trous |
| **Shadow trading fidèle** | Non représentatif si la prod visée est gRPC | Le shadow tourne sur l'infra de prod | Un shadow webhook valide un autre bot que celui que vous déploierez |

## 3. Impact par phase du plan d'exécution

| Phase | Impact du passage au webhook |
|---|---|
| **1. Capture** | Possible mais fragile : volume firehose en HTTP, trous silencieux, ré-ordonnancement et dédup à votre charge, réconciliation par RPC obligatoire. Vos timestamps locaux deviennent bruités (± secondes) → **l'horloge de référence doit être le slot, pas votre horloge murale** |
| **2. Labels / backfill** | Aucun impact (travail offline) |
| **3. Bases propriétaires** | Aucun impact (travail offline sur la capture) |
| **4. Études** | Largement sauvables **en temps-slot** (voir § 5) ; mais la granularité slot ≈ 400 ms → la courbe de décroissance sub-seconde (0,2 s vs 0,5 s) devient non mesurable. Vous ne saurez simplement pas ce qui se passe sous 400 ms |
| **5. Shadow** | Biaisé si la production visée est gRPC — à faire sur l'infra définitive |
| **6. Micro-réel** | Les sorties événementielles rapides (vente du dev en < 1 s) deviennent impossibles ; entrée systématiquement 1–5 s derrière les bots gRPC |

## 4. Impact par famille d'edge

| Famille | Sort en webhook |
|---|---|
| **A — Empreintes de devs** | ✅ Survit : le signal (identité du dev) est disponible dès la création et décroît lentement. L'entrée décalée de 2–4 s coûte quelques % de prix d'entrée, tolérable |
| **B — Flux mécaniques** | 🟡 Partiel : la poussée de graduation (minutes) reste jouable ; anticiper les sorties de snipers (secondes) ne l'est plus |
| **C — Latence d'information** | ❌ Meurt : c'est précisément la famille que l'infra rapide achète. En webhook, vous *êtes* la foule en retard que d'autres front-runnent |
| **D — Méta / attention** | ✅ Survit : dynamique en minutes |
| **E — Élimination** | ✅ Survit intégralement : c'est du filtrage, pas de la vitesse — et c'est le levier n°1 |
| **F — Rotation de clusters** | 🟡 Partiel : jouable sur les rotations lentes (dizaines de secondes+) |
| **Sorties (dev sell, retournement de flux)** | ❌/🟡 Sévèrement dégradées : votre pire perte par trade grossit → compenser par des tailles réduites et des stops plus larges — ce qui ampute l'espérance |

Lecture honnête : le webhook conserve les edges **lents et informationnels** (A, D, E — dont l'élimination, le plus gros levier) et sacrifie les edges **rapides et réactifs** (C, sorties d'urgence, fin de famille B).

## 5. Le point méthodologique qui sauve un démarrage en webhook : le temps-slot

La recherche (phase 4) ne se fait pas en temps réel : elle se fait sur l'historique, où la latence n'existe pas — à condition de dater les événements **en slots** (l'horloge on-chain, ~400 ms) et non avec votre horloge de réception. Une capture webhook horodatée au slot reste scientifiquement exploitable : études d'événement à « entrée slot+3 » plutôt qu'à « entrée +1,2 s », baselines appariées identiques, labels identiques.

Ce que vous perdez malgré tout : la résolution sub-slot (l'ordre intra-slot des transactions reste visible, mais pas vos deltas en millisecondes), et la mesure de **votre** latence réelle de bout en bout — que seul le flux de prod peut donner.

## 6. Le faux dilemme : les quatre niveaux du spectre

| Niveau | Latence typique | Coût | Pour quoi |
|---|---|---|---|
| **Webhook** | 1–5 s | € | Notifications, stratégies lentes, budget minimal |
| **WebSocket** (RPC `logsSubscribe` / PumpPortal) | 0,5–2 s | € (souvent gratuit) | **Meilleur que le webhook à coût égal** pour la capture : connexion permanente, pas d'endpoint public, sémantique de flux |
| **gRPC partagé** (Triton/Helius LaserStream/Shyft, plan mutualisé) | 100–500 ms | €€ | 80 % du bénéfice gRPC pour une fraction du prix du dédié |
| **gRPC dédié** (Triton dédié) | 50–300 ms, jitter minimal | €€€€ | Familles rapides, guerre de latence, production sérieuse |

**Si la motivation du webhook est le budget, le WebSocket domine le webhook presque partout** pour ce cas d'usage : même ordre de coût, meilleure sémantique (flux ordonné, pas de POST concurrents), pas de serveur public à exposer, et PumpPortal fournit exactement ce flux gratuitement pour prototyper.

## 7. Recommandation

1. **Budget contraint aujourd'hui** : ne choisis pas le webhook — choisis le **WebSocket** (PumpPortal ou `logsSubscribe`) pour les phases 1–4, avec l'horloge slot comme référence et la réconciliation RPC pour les trous. Coût quasi nul, recherche valide.
2. **Décide l'infra de production avec les données, pas avant** : la courbe de décroissance (phase 4, mesurée en slots) te dira si tes edges survivants exigent le gRPC. S'ils décroissent en 30 s+, un WebSocket suffit même en prod — économie majeure. S'ils meurent en 1–5 s, passe au **gRPC partagé** d'abord, dédié seulement si le PnL le justifie.
3. **Si Triton est déjà budgété et acquis** : garde-le. Le coût d'opportunité du démarrage lent n'est pas seulement la latence — c'est que la famille C reste **inexplorée** (tu ne peux pas étudier ce que tu ne peux pas voir à cette résolution) et que ta latence réelle de production reste inconnue jusqu'au dernier moment.
4. **Si webhook quand même** (contrainte externe) : dédup par signature, idempotence stricte, ré-ordonnancement par slot, buffer local pour absorber les rafales, réconciliation périodique par RPC `getBlock`, header d'authentification vérifié sur l'endpoint — et interdiction de toute stratégie dont la sortie d'urgence doit s'exécuter en < 5 s.

**En une phrase** : le webhook échange ~10× de latence, du jitter et des trous silencieux contre un coût presque nul et une mise en route simple — un échange acceptable pour la recherche et les stratégies lentes (élimination, devs, méta, post-graduation), disqualifiant pour les stratégies réactives (latence d'information, sorties d'urgence) ; et à budget égal, le WebSocket fait mieux que le webhook, pendant que le gRPC partagé comble l'essentiel de l'écart avec le dédié.
