# Choisir son point d'entrée sur Pump.fun : comparatif des stratégies

Ce document compare les points d'entrée possibles sur le cycle de vie d'un token Pump.fun — sniping à la création, milieu de courbe, pré-graduation, post-graduation, suivi de la smart money, nombre de holders — et répond à la question des timeframes (bougies en secondes vs 5 min / 15 min / 1 h, et durée de détention).

**Idée directrice** : le bon choix ne dépend pas du « meilleur moment » dans l'absolu, mais de trois choses que *vous* possédez : votre **latence** (infrastructure), vos **données** (pipeline de features), et votre **temps** (bot ou trading manuel). Chaque phase du token favorise un profil différent.

---

## 1. Tableau comparatif

| Stratégie | Données dispo à l'entrée | Concurrence | Infra requise | Profil de gains | Durée de détention | Adapté à |
|---|---|---|---|---|---|---|
| **Sniping à la création (bloc 0)** | Quasi nulles (dev + métadonnées seulement) | Extrême (guerre de latence) | Geyser/gRPC + bundles Jito, < 300 ms | ~90 % de pertes, gains en loi de puissance | 30 s – 5 min | Équipes outillées uniquement |
| **Milieu de courbe (5–40 %)** | Riches (flux, holders, comportement du dev, snipers) | Moyenne | Bot + pipeline de données, latence ~1 s OK | Win rate moyen, R/R sain | 2 – 20 min | **Le trader data-driven** |
| **Pré-graduation (75–95 %)** | Très riches (tout l'historique du token) | Élevée (jeu connu) | Bot simple, latence ~1 s | Petits deltas réguliers + queue de risque | Minutes autour de l'événement | Stratégie d'appoint systématique |
| **Post-graduation (survivants)** | Maximales + LP verrouillée | Faible à moyenne, plus lente | Aucune obligatoire (manuel possible) | Moins de zéros instantanés, −80 % possibles | Heures – jours | **Le débutant / trader manuel** |
| **Suivi smart money** | La position d'autrui (avec retard) | Moyenne, décroissante | Tracking wallets + exécution rapide | Dépend du retard de copie | Celle du wallet copié | Filtre plus que stratégie |
| **Seuil de holders** | Un compteur falsifiable | — | — | Négatif (seuil farmé par les devs) | — | Personne, seul |

---

## 2. Analyse par stratégie

### 2.1 Sniper à la création (bloc 0) — la guerre de latence

**Ce que c'est** : acheter dans le même slot (ou les 2–3 slots suivants) que la transaction `Create`, à ~4–5 k$ de market cap, avant toute donnée de marché.

**Pourquoi c'est séduisant** : le prix d'entrée le plus bas possible ; chaque token qui fait ×20 est passé par là.

**Pourquoi c'est un piège pour un amateur** :
- Au bloc 0, **il n'existe aucune donnée de marché** : ni flux, ni holders, ni rétention. Les seules features disponibles sont le wallet du dev, les métadonnées et la composition de la transaction de création. Vous achetez à l'aveugle un billet de loterie.
- La concurrence se joue en **dizaines de millisecondes** : Geyser/Yellowstone gRPC, bundles Jito, tips calibrés, infra colocalisée. En WebSocket/API REST (0,5–2 s), vous arrivez systématiquement derrière la meute — vous êtes la liquidité de sortie des snipers plus rapides.
- L'économie réelle : ~90 % des snipes finissent en perte, les frais de priorité et les transactions échouées rongent le reste ; le PnL vient de quelques queues extrêmes qu'il faut avoir la discipline (automatisée) de vendre dans la première vague.

**La seule variante défendable sans infra d'élite** : le **snipe filtré par dev** — ne sniper que les créations des rares déployeurs à historique prouvé (taux de graduation élevé, zéro rug). L'univers passe de 1 000+ lancements/jour à quelques-uns, la vitesse compte moins que la liste.

**Verdict** : à éviter, sauf investissement sérieux en infrastructure ou via la variante « liste de devs ».

### 2.2 Milieu de courbe (≈ 5–40 % de progression) — le point d'équilibre

**Ce que c'est** : entrer quand le token a 2–15 minutes de vie et que la courbe se remplit, sur confirmation de features — pas au chart, aux **données**.

**Pourquoi c'est le sweet spot** :
- C'est la première phase où **toutes les features d'expert existent** : net flow et son accélération, croissance des acheteurs uniques, rétention des premières cohortes, comportement des snipers du bloc 0 (tiennent-ils ?), position et transferts du dev, clusters de wallets, présence smart money.
- La concurrence s'y joue sur la **qualité du modèle**, pas sur la milliseconde : une latence d'une seconde est acceptable. C'est le seul terrain où un individu outillé peut battre les bots industriels — par la sélection, pas par la vitesse.
- Le risque est **mesurable avant l'entrée** : la checklist anti-rug (voir le référentiel de données, § 3.8) s'applique intégralement.

**Le coût** : vous payez ×2 à ×5 le prix du bloc 0. C'est le prix de l'information — et il est presque toujours bon marché par rapport à ce qu'elle élimine.

**Exécution type** : filtres éliminatoires → score composite → entrée si percentile cible → sortie sur événement (vente du dev = immédiate ; net flow 30 s négatif + pic de vendeurs uniques = sortie ; sinon take-profits échelonnés + durée max 15–20 min).

**Verdict** : **la stratégie cœur recommandée** pour quiconque construit un pipeline de données (ce que le référentiel de ce dépôt permet).

### 2.3 Juste avant graduation (≈ 75–95 %) — capter le delta de migration

**Ce que c'est** : acheter en fin de courbe pour revendre dans la poussée mécanique liée à la complétion (visibilité « graduated », listings DexScreener/agrégateurs, acheteurs de graduation).

**Ce qui marche** : le déclencheur n'est pas « 90 % » mais la **dynamique** : ETA de graduation qui s'effondre (vitesse d'inflow en accélération) + net flow positif. Entrer sur un token *stagnant* à 90 % est le piège classique — les derniers SOL sont les plus durs à collecter et un token peut camper à 95 % pendant des heures pendant que le flux meurt.

**Ce qui a changé** : depuis la migration instantanée vers PumpSwap (mars 2025, plus de frais ni de délai vs l'époque Raydium), la « fenêtre morte » entre complétion et tradabilité a disparu — le gap exploitable s'est **compressé**, et le jeu est connu donc encombré : une partie du delta est déjà front-run par des acheteurs à 70–80 %.

**Risques spécifiques** : le post-migration dump — les snipers et premières cohortes utilisent la liquidité et la visibilité de la migration comme sortie ; sans vérification de la structure de détention, vous achetez leur exit.

**Verdict** : stratégie d'appoint valable, mécanique, à espérance modeste ; à mesurer en continu car l'edge se comprime. Jamais en stratégie unique.

### 2.4 Après la graduation (si le token survit) — le terrain du trader manuel

**Ce que c'est** : ne trader que les ~1 % de tokens qui migrent. Univers réduit (dizaines/jour au lieu de milliers), données maximales, LP verrouillée, historique complet de la courbe disponible pour l'analyse.

**Pourquoi c'est la meilleure porte d'entrée** :
- Le rythme est **humain** : les mouvements se jouent en minutes/heures, pas en secondes. Pas de bot obligatoire.
- Le risque de rug instantané est fortement réduit (pas éliminé : un dump de dev ou de cluster reste possible et fait −80 %).
- Les setups sont lisibles : le pattern dominant est **flush post-migration → stabilisation → seconde jambe si la rétention tient**. Acheter la première purge post-migration quand (a) les cohortes de la courbe tiennent, (b) la smart money n'est pas sortie, (c) le volume ne s'évapore pas, est le setup le plus enseignable de l'écosystème.
- On peut y appliquer une vraie discipline de clôture de bougie (voir § 3).

**Le coût** : vous renoncez aux ×20 de courbe ; les multiples typiques sont ×1,5–×5, avec des queues rares au-delà.

**Verdict** : **la stratégie recommandée sans infrastructure** — et le meilleur terrain d'apprentissage avant de descendre vers la courbe.

### 2.5 « Quand la smart money arrive » — un signal, pas une stratégie

Suivre les wallets d'élite fonctionne **comme couche de confirmation**, mal comme stratégie autonome :

- **En copie brute**, vous entrez toujours après eux (retard de détection + exécution). Sur un scalpeur rapide, ce retard vous fait acheter son sommet — certains wallets d'élite sont *structurellement toxiques à copier* parce que leur edge est précisément la vitesse. D'autres, sachant qu'ils sont suivis, montent des sorties sur leurs copieurs.
- **En filtre**, c'est excellent : présence de 2–3 wallets d'élite dans les premières minutes = un des signaux les plus fiables pour valider une entrée milieu de courbe ; smart money qui *tient à travers la migration* = signal de conviction post-graduation ; smart money qui sort = veto.
- À copier, préférez les profils **position/rétention** (détention > 30 min, win rate stable) aux profils scalp, et réévaluez la liste chaque semaine (le PnL des wallets d'élite est peu persistant).

**Verdict** : intégrer comme feature pondérée (cf. score composite du référentiel), pas comme déclencheur unique.

### 2.6 Le nombre de holders — le pire déclencheur possible

- C'est un compteur **retardé** (il monte après le mouvement) et **falsifiable pour quelques dollars** : il existe des services de « holder farming » que les devs utilisent précisément pour déclencher les bots d'amateurs réglés sur « acheter à N holders ». Un seuil fixe de holders n'est pas un edge, c'est **le piège tendu à ceux qui croient en avoir un**.
- Les versions utiles de cette donnée sont ses dérivées corrigées : **croissance des acheteurs uniques** par fenêtre, **holders ajustés des clusters** (nombre de mains réelles), **ratio de wallets frais**, **rétention par cohorte**.

**Verdict** : jamais en déclencheur ; uniquement en feature transformée dans le score.

---

## 3. La question des timeframes : bougies et durée de détention

Deux lectures de la question, deux réponses.

### 3.1 Quelle granularité de bougies ?

La granularité n'est **pas un choix libre : elle est dictée par la phase**. La durée de vie médiane d'un token en courbe se compte en minutes — une bougie de 15 min y contient tout un cycle de vie.

| Phase | Granularité utile | Logique de décision |
|---|---|---|
| Bloc 0 – 2 min | Tick par tick (pas de bougies) | Événementielle pure |
| Courbe (5–40 %) | 1 s – 5 s | **Événementielle** (seuils de flux), les bougies ne servent qu'au visuel |
| Pré-graduation | 5 s – 15 s | Événementielle (ETA, accélération d'inflow) |
| Jour de migration | 1 min – 5 min | Mixte : événements + clôtures de bougies |
| Survivants installés (J+1 et au-delà) | 15 min – 1 h | Clôtures de bougies classiques (les 20 min n'existent pas en standard — 15 min fait le même travail) |

**Le point clé** : en phase courbe, **attendre la clôture d'une bougie de 5 min est disqualifiant** — le mouvement est fini avant la clôture. On n'y trade pas des bougies, on y trade des **événements** : franchissement d'un seuil de net flow, vente du dev, arrivée smart money. À l'inverse, en post-graduation, la discipline de clôture (ex. : n'acheter que sur clôture 5 min au-dessus du VWAP, ne vendre que sur clôture sous un niveau) protège des mèches et des fakeouts — c'est là qu'elle a du sens.

### 3.2 Quelle durée de détention (clôture de position) ?

| Stratégie | Détention typique | Règle de sortie recommandée |
|---|---|---|
| Snipe bloc 0 | 30 s – 5 min | Vendre dans la première vague, automatiquement |
| Milieu de courbe | 2 – 20 min | Événementielle (dev sell, retournement de flux) + **durée max ~15–20 min** en garde-fou |
| Pré-graduation | Minutes autour de l'événement | Vendre dans la poussée de graduation, pas après |
| Post-graduation J0 | 15 min – quelques heures | Take-profits échelonnés + stop sous le creux post-migration |
| Survivant en swing | Heures – jours | Clôtures 15 min/1 h + suivi de rétention et de la smart money |

Une sortie à durée fixe (« je coupe tout à 5 min ») est un garde-fou légitime — c'est une baseline honnête qui évite le sur-hold — mais les sorties pilotées par les données la battent systématiquement : le token vous dit quand c'est fini (flux, vendeurs uniques, dev) avant que le chronomètre le fasse.

---

## 4. Arbre de décision

```
Avez-vous une infra basse latence (gRPC + bundles) et un budget de tx échouées ?
├─ OUI → Sniping filtré par liste de devs + milieu de courbe en parallèle
└─ NON
   ├─ Avez-vous (ou construisez-vous) un bot avec pipeline de données ?
   │  ├─ OUI → CŒUR : milieu de courbe (5–40 %), score composite,
   │  │         sorties événementielles.
   │  │         APPOINT : delta de pré-graduation (déclenché sur ETA
   │  │         en accélération, jamais sur le % seul).
   │  └─ NON → Post-graduation uniquement : acheter la purge
   │            post-migration des survivants dont la rétention tient
   │            et dont la smart money n'est pas sortie.
   └─ Dans tous les cas :
      - Smart money = filtre/confirmation, jamais déclencheur unique
      - Nombre de holders brut = jamais un déclencheur (seuil farmé)
      - Granularité : événements/secondes en courbe,
        1–5 min en post-migration, 15 min–1 h pour les survivants
```

## 5. Progression recommandée

1. **Semaine 1–2 : enregistrer, ne pas trader.** Capter le flux complet (créations, trades, transferts) pour constituer une base sans biais du survivant.
2. **Phase manuelle : post-graduation.** Peu de tokens, rythme humain, apprentissage des patterns (flush → rétention → seconde jambe) en risquant peu.
3. **Premier bot : milieu de courbe.** Checklist éliminatoire + score composite du référentiel, positions minuscules, journal de chaque trade avec les features à l'entrée (c'est votre futur dataset d'entraînement).
4. **Module d'appoint : pré-graduation** une fois le delta mesuré sur *vos* données récentes (il se comprime — vérifiez qu'il existe encore).
5. **Éventuellement, dernier : sniping filtré par devs** — uniquement si les étapes précédentes sont rentables et que la liste de devs d'élite est constituée.

Ne menez pas les cinq de front : chaque stratégie exige son outillage, son monitoring et son budget d'erreurs. Un edge médiocre bien exécuté sur une phase bat cinq edges théoriques mal exécutés sur toutes.
