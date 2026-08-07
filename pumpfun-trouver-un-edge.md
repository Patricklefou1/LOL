# Trouver un edge sur Pump.fun — méthode de recherche pour un bot sous Triton

Prérequis de ce document : l'infrastructure est un bot branché sur **Triton One** (flux Yellowstone gRPC / « Dragon's Mouth », latence événement → décision ≈ 100–300 ms, envoi via bundles Jito). À ce niveau d'infra, la latence cesse d'être l'obstacle : **l'edge devient un problème de recherche, pas de tuyauterie**.

**Thèse centrale** : un edge ne se « trouve » pas par illumination — il se **fabrique** par une boucle industrielle : hypothèse mécanique → étude d'événement sur vos propres données → validation hors échantillon temporelle → shadow trading → micro-réel → production monitorée → retrait quand il décède. Le livrable n'est pas *un* edge (durée de vie : semaines), c'est **l'usine à edges**.

---

## 1. Définition opérationnelle (ce que vous cherchez exactement)

Un edge est une condition observable C telle que :

```
E[ rendement(h) | C, exécuté avec VOS coûts et VOTRE latence ] > 0
```

avec :
- **h** : un horizon de détention défini À L'AVANCE (30 s, 5 min, jusqu'à événement de sortie) ;
- **coûts complets** : 1 % de frais protocole ×2 + priority fee + tip Jito + votre impact sur la courbe (calculable exactement) + coût des tx échouées ;
- **persistance** : l'espérance reste positive semaine après semaine en walk-forward, pas seulement sur l'échantillon où vous l'avez aperçue.

Corollaire brutal, spécifique à Pump.fun : l'espérance **inconditionnelle** d'un achat est très négative (~99 % des tokens vont à zéro). Donc :

> **Le levier n°1 n'est pas de prédire les gagnants, c'est d'éliminer les pièges.** L'ordre de grandeur des gains de chaque levier : élimination > sélection > timing > exécution. Cherchez d'abord un edge *négatif* (ne pas acheter), ensuite seulement un edge *positif*.

---

## 2. Étape 0 — la fondation de données (avant toute recherche)

On ne trouve pas d'edge dans des données qu'on n'a pas. Avec Triton :

### 2.1 Capture (à lancer dès maintenant, avant de savoir quoi en faire)

- **Souscription gRPC** : transactions du programme Pump.fun (`6EF8rre...`) + comptes `bonding_curve` + slots. Décodage des événements Anchor `Create` / `Trade` / `Complete` via l'IDL.
- **À horodater au slot près** : chaque trade (wallet, sens, montants, réserves après trade), chaque création (dev, métadonnées, achat initial, composition du bundle), chaque complétion.
- **Le graphe de transferts SOL** : qui finance qui (indispensable aux clusters et aux empreintes de devs). Capturez les transferts systèmes des wallets actifs sur Pump.fun.
- **Le contexte d'exécution** : priority fees payées par les autres, tips Jito observés, taux de tx échouées par token — c'est votre futur modèle de coûts.
- **Stockage** : base colonne (ClickHouse est le standard pour ce débit). Des millions de lignes/jour ; tout garder, y compris et surtout les tokens morts.

### 2.2 Labellisation des issues (le « y » de toute votre recherche)

Pour chaque token capturé, calculez à froid :
- multiple maximal atteint depuis chaque point d'entrée possible ;
- temps jusqu'à la mort (définition : ex. volume 5 min < seuil) ;
- gradué ou non ; ruggé ou non (dev sell > seuil, type de rug) ;
- courbes de rendement à horizon h depuis tout instant t (la matrice token × temps × horizon).

### 2.3 Bootstrap de l'historique

Votre capture live met des semaines à s'accumuler. En parallèle, remplissez l'historique via Bitquery (trades Pump.fun historiques) — suffisant pour les études d'événement grossières, insuffisant pour la microstructure fine (horodatage moins précis). **Aucune API publique ne remplace votre capture** : les tokens morts et le graphe de financement en sont absents.

---

## 3. La boucle de recherche

### 3.1 Générer des hypothèses par le mécanisme, jamais par le data mining

Une bonne hypothèse répond à : **« Qui est contraint ou incité à agir de façon prévisible, et pourquoi cette prévisibilité n'est-elle pas déjà arbitrée ? »** Si vous ne savez pas dire *qui perd de l'argent en face et pourquoi il accepte de le perdre* (il est plus lent, il est contraint, il joue un autre jeu, il se trompe systématiquement), vous n'avez pas une hypothèse, vous avez une coïncidence statistique en devenir.

Miner 300 features contre les labels « pour voir » produit mécaniquement des faux edges (voir § 5).

### 3.2 L'étude d'événement — votre outil de travail quotidien

Pour chaque hypothèse « condition C » :

1. Repérer toutes les occurrences de C dans l'historique capturé.
2. Aligner les tokens sur l'instant de C (t = 0).
3. Tracer la **courbe de rendement forward moyenne ET médiane** (t+10 s, +30 s, +1 min, +5 min, +15 min) avec intervalles bootstrap.
4. Comparer à la **baseline appariée** : rendement forward de tokens *comparables* (même âge, même mcap, même heure) sans la condition C. Un « +30 % après C » ne veut rien dire si la baseline appariée fait +25 %.
5. Retrancher les coûts complets au point d'entrée réaliste (voir § 6).

La différence (courbe conditionnelle − baseline − coûts) EST l'edge candidat. Médiane et moyenne racontent des histoires différentes en loi de puissance : regardez les deux, plus les quantiles 25/75/95.

### 3.3 Chercher les sorties avec la même machine

La moitié du PnL est dans la sortie, et personne ne la recherche. Mêmes études d'événement, conditionnées sur *être en position* : E[rendement restant | net flow 30 s < 0], E[… | premier vendeur du cluster dominant], E[… | vente du dev]. Vous découvrirez que certains signaux d'entrée médiocres sont d'excellents signaux de sortie.

---

## 4. Où chercher : les familles d'hypothèses classées par coût de falsification

Principe d'expert qui organise tout le reste : **dès qu'un pattern devient tradé par des bots, ceux qui peuvent le fabriquer à bas coût le fabriquent** (wash trading, holder farming, faux momentum). Un edge robuste s'appuie sur des signaux **coûteux à falsifier pour l'adversaire**.

| Signal | Coût de falsification | Verdict |
|---|---|---|
| Volume brut | Quasi nul (wash à 2 $ de frais) | Jamais en signal principal |
| Nombre de holders | Quasi nul (holder farming) | Jamais |
| Nombre de tx, replies | Quasi nul | Jamais |
| Net inflow SOL dans la courbe | Moyen (capital réellement immobilisé et à risque) | Utilisable pondéré |
| Rétention / temps en position des cohortes | Moyen-élevé (immobilisation prolongée) | Bon |
| Historique de graduation d'un dev | Élevé (exige d'avoir vraiment fait graduer des tokens) | Excellent |
| Track record PnL d'un wallet (smart money) | Élevé (exige des profits réels passés) | Excellent |
| Flux mécaniques de structure (graduation, sorties habituelles de snipers) | Non falsifiable (c'est la mécanique elle-même) | Excellent |

### Famille A — Persistance comportementale des acteurs identifiés
Les devs sont des humains avec des habitudes : mêmes sources de financement, même façon de bundler, même timing de rug, même heure de lancement. Construisez des **empreintes de dev** (fingerprints) reliant les identités jetables via le graphe de financement. Hypothèses : E[r | dev du top décile de graduation historique] ; E[survie | empreinte jamais associée à un rug]. Idem pour les snipers : chaque wallet sniper a des niveaux de sortie habituels (×2, ×3…) — mesurables, donc anticipables.

### Famille B — Flux mécaniques
Des achats/ventes qui *doivent* arriver : la poussée de complétion de courbe, les sorties de snipers à leurs multiples habituels, les cascades des bots copieurs (détectables : grappes de wallets qui répliquent un wallet source avec 1–5 s de retard). Vous ne prédisez pas une opinion, vous prédisez une **contrainte**.

### Famille C — Arbitrage de latence d'information
La chaîne : événement on-chain (achat d'un wallet d'élite) → affichage sur GMGN/Photon/Axiom (2–10 s) → réaction du retail (10 s – 3 min, le temps d'ouvrir l'app et de cliquer). Avec Triton vous voyez l'événement en ~200 ms : vous tradez **la réaction prévisible de la foule à une information publique**, pas l'information elle-même. C'est la famille que votre infra achète directement.

### Famille D — Attention et méta
Le premier token d'une nouvelle méta capture une part démesurée de l'attention. Détection : clustering en continu des noms/thèmes des créations ; signal = « cluster nouveau + densité de lancements en explosion + le leader s'échappe ». Même logique pour les calls de KOL : l'arrivée du retail s'étale sur des minutes — flux prévisible après l'événement observable.

### Famille E — Élimination supérieure (l'edge le plus sous-coté)
Votre checklist anti-rug appliquée mieux et plus vite que le marché est un edge en soi : à sélection égale, éliminer 80 % des pièges que les autres achètent transforme l'espérance. C'est aussi le seul edge qui se **renforce** quand les adversaires s'améliorent en fabrication de faux signaux (vous filtrez sur le coûteux-à-falsifier).

### Famille F — Rotation de clusters
Les mêmes grappes de wallets tournent de token en token. Le départ d'un cluster performant du token A (ventes groupées) et son arrivée sur le token B est un indicateur avancé des deux côtés.

---

## 5. Discipline statistique (où meurent les faux edges)

1. **Validation temporelle uniquement** : walk-forward (entraîner sur semaines 1–4, tester sur semaine 5, glisser). Jamais de split aléatoire — il fait fuiter la méta du moment dans le test et gonfle tout.
2. **Tests multiples** : si vous testez 200 conditions, ~10 seront « significatives » par hasard. Tenez un **registre de toutes les hypothèses testées** (y compris les échecs), corrigez vos seuils en conséquence, et méfiez-vous de toute découverte non pré-enregistrée.
3. **Corrélation des observations** : 50 trades sur le même token, ou sur la même heure de la même méta, ne sont pas 50 observations indépendantes. Clusterisez les erreurs par token et par fenêtre temporelle ; comptez votre « N effectif » en tokens-métas, pas en trades.
4. **Queues de distribution** : jugez un edge sur médiane + quantiles + moyenne, testez sa robustesse en retirant les 3 meilleurs trades. S'il ne survit pas à ce retrait, vous avez échantillonné une loterie, pas un edge.
5. **Demi-vie** : tracez l'edge par semaine calendaire. Un vrai edge décline progressivement ; un artefact de mining disparaît instantanément hors échantillon. Prévoyez le retrait (critère de mort défini à l'avance, ex. : moyenne mobile 2 semaines < coûts).
6. **Régimes** : conditionnez tout sur le régime (tendance SOL, débit de lancements, taux de graduation glissant). Beaucoup d'« edges » sont juste « le marché montait ».

---

## 6. Le modèle de coûts et la courbe de décroissance du signal

Deux mesures à faire AVANT de croire à tout edge candidat :

### 6.1 Coût complet par aller-retour
`1 % ×2 (protocole) + priority fee + tip Jito (percentile du moment) + impact aller + impact retour (exacts par produit constant) + P(échec) × coût de retry`. Sur une courbe mince, l'impact domine tout : simulez VOTRE taille.

### 6.2 Courbe de décroissance : E[r | signal, délai d]
Recalculez chaque étude d'événement en décalant l'entrée de d = 0,2 s / 0,5 s / 1 s / 5 s / 30 s. Trois cas :

- le signal tient à 30 s → c'est un edge de **modèle** : votre latence Triton est un confort, la compétition se joue sur la qualité de la recherche ;
- le signal meurt entre 1 et 5 s → c'est exactement **votre terrain** : trop rapide pour le retail et les bots à WebSocket, atteignable en gRPC ;
- le signal meurt sous 500 ms → guerre d'infra pure contre les meilleurs : n'y allez que si votre boucle complète (détection → décision → tx landée) est mesurée sous ce seuil.

Cette courbe est le **filtre qui apparie vos hypothèses à votre infrastructure**. Mesurez aussi en continu votre latence de bout en bout réelle (distribution, pas moyenne) : elle fait partie du modèle.

---

## 7. Pipeline de validation en 3 étages (avec critères de mort écrits à l'avance)

| Étage | Quoi | Ce que ça mesure | Critère de passage |
|---|---|---|---|
| **1. Backtest événementiel** | Études d'événement sur votre capture + historique | L'edge existe-t-il statistiquement ? | Edge net de coûts > 0 en walk-forward sur ≥ 4 semaines distinctes |
| **2. Shadow (paper) en production** | Le bot tourne en réel, loggue des fills simulés (délai de slot réel, tip du moment, impact simulé) | Votre pipeline temps réel reproduit-il la recherche ? | PnL simulé ≈ PnL backtesté (écart expliqué) sur ≥ 2 semaines |
| **3. Micro-réel** | Tailles minuscules réelles | La seule chose que le papier ne mesure pas : **votre** slippage réel et la **sélection adverse** | Slippage réel ≈ modélisé ; edge net > 0 sur ≥ 300–500 trades |

La sélection adverse de l'étage 3 est le tueur silencieux : dès que des bots tradent un pattern, les manipulateurs le fabriquent — et le pattern fabriqué s'exécute *mieux* (on vous laisse entrer volontiers). Si le PnL micro-réel est nettement pire que le shadow à slippage égal, votre signal est en train d'être farmé : retour au § 4 (montez en coût de falsification).

**Sizing en production** : Kelly fractionné (¼ Kelly max — les queues de loi de puissance rendent le Kelly plein suicidaire), plafond par trade (1–2 % du capital), kill switch de drawdown journalier, et jugement sur ≥ 500 trades — jamais sur 20.

---

## 8. L'usine à edges (le vrai livrable)

Un edge Pump.fun vit quelques semaines (copie, farming, rotation de méta). L'organisation qui gagne :

- **Attribution continue** : chaque trade en production loggue les features à l'entrée et le signal déclencheur → PnL décomposable par signal, par semaine. Vous voyez *quel* edge décline, pas juste « le bot gagne moins ».
- **Cimetière d'hypothèses** : registre de tout ce qui a été testé, avec verdict. Évite de re-tester les mêmes mirages et documente les corrections de tests multiples.
- **Cadence** : un rituel hebdomadaire — réestimer les edges vivants, avancer 2–3 hypothèses nouvelles, enterrer les morts. L'usine tourne même quand le bot gagne (surtout quand il gagne : c'est là qu'on se fait copier).
- **Le fossé défensif** : au fil des mois, vos actifs non copiables sont vos **bases de données propriétaires** — empreintes de devs, historique PnL des wallets, niveaux de sortie des snipers, cimetière d'hypothèses. C'est ça, l'edge durable ; les signaux individuels ne sont que sa production courante.

---

## 9. Architecture de référence du bot (Triton)

```
[Triton Yellowstone gRPC]
   │  (tx pump.fun, comptes bonding_curve, slots, transferts SOL)
   ▼
[Décodeur Anchor]  ──────────────►  [ClickHouse : capture brute complète]
   │                                      ▲ (recherche, études d'événement,
   ▼                                         labels, walk-forward)
[Moteur de features INCRÉMENTAL]
   │  état par token mis à jour en O(1) par événement :
   │  net flow, acheteurs uniques (HyperLogLog), vitesse/accél. d'inflow,
   │  position dev, flags snipers/bundles, clusters, présence smart money
   ▼
[Décision]  ◄─── [Bases propriétaires : empreintes devs, smart wallets,
   │              niveaux snipers — rafraîchies offline]
   ▼
[Exécuteur : bundle Jito, tip dynamique au percentile, simulation
 d'impact avant envoi, retry borné, kill switches]
   │
   ▼
[Journal de production : features à l'entrée, latences mesurées,
 fills réels vs simulés]  ──► retour dans ClickHouse (attribution)
```

Contraintes non négociables : features calculables en **incrémental** (pas de recalcul par fenêtre), horodatage au slot partout, chemin critique instrumenté (histogramme de latence de bout en bout), et le même code de features en recherche et en production (sinon vos backtests testent un autre bot que le vôtre).

---

## 10. Par où commencer concrètement : les trois premières études

Dans l'ordre, parce qu'elles maximisent l'apprentissage par heure investie :

1. **Élimination (famille E)** : sur votre historique, mesurez l'espérance inconditionnelle d'achat à 10 % de courbe, puis réappliquez la checklist anti-rug (référentiel § 3.8) et mesurez l'espérance du sous-ensemble survivant. L'écart entre les deux est votre premier edge — probablement le plus gros que vous trouverez jamais.
2. **Devs (famille A)** : classez tous les devs capturés par historique (graduation, rugs, via empreintes de financement). Étude d'événement : achat à 10 % de courbe conditionné au décile de dev. Signal cher à falsifier, décroissance lente (tient à 30 s+) — parfait premier signal *positif*.
3. **Latence smart money (famille C)** : constituez le top 1 % des wallets par PnL persistant ; étude d'événement sur leurs achats avec la courbe de décroissance complète (0,2 s → 30 s). C'est l'étude qui vous dira précisément **ce que votre infra Triton vous achète en dollars**.

Ces trois études partagent la même machinerie (capture, labels, event study, baseline appariée) : en les faisant, vous construisez l'usine. Le reste — familles B, D, F, signaux de sortie — s'enchaîne sur les mêmes rails.

---

## 11. Les erreurs qui coûtent six mois

1. Chercher « le » signal magique au lieu de construire la machine à tester des signaux.
2. Backtester sur des données d'API publiques (sans les morts, sans les slots précis) puis s'étonner du réel.
3. Miner des corrélations sans mécanisme ni adversaire identifié.
4. Ignorer la courbe de décroissance et trader en gRPC un signal qui tient 30 s (payer une Formule 1 pour aller à la boulangerie — pendant que d'autres tradent en face un signal mort en 800 ms que vous n'avez pas cherché).
5. Valider sur split aléatoire, déployer, mourir à la rotation de méta suivante.
6. Sauter l'étage micro-réel et découvrir la sélection adverse avec de la taille.
7. Ne pas instrumenter la latence de bout en bout (la « latence Triton » n'est pas votre latence : la vôtre inclut votre décodeur, vos features, votre décision, votre envoi).
8. Ne jamais rien retirer : garder en production des edges morts qui saignent en silence — l'attribution par signal existe précisément pour ça.
