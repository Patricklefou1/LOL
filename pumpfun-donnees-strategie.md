# Référentiel de données pour une stratégie d'achat/revente sur Pump.fun

Ce document recense **l'ensemble des données exploitables** pour construire une stratégie de trading (sniping, scalping de bonding curve, momentum, copy-trading) sur Pump.fun, classées en trois niveaux : **base**, **intermédiaire** et **expert**. Chaque métrique est accompagnée de sa définition, de son mode de calcul quand il n'est pas trivial, et du signal qu'elle apporte.

> ⚠️ **Avertissement** : ~99 % des tokens Pump.fun ne migrent jamais et finissent à zéro. Aucune combinaison de données ne supprime ce risque ; elle ne fait que déplacer l'espérance de gain. Rien ici n'est un conseil financier. Les paramètres du protocole (frais, seuil de migration) évoluent : vérifiez toujours les valeurs actuelles on-chain.

---

## 0. Comprendre le terrain : cycle de vie d'un token Pump.fun

Toute donnée n'a de sens que rapportée à la **phase** du token :

| Phase | Durée typique | Mécanique | Stratégies concernées |
|---|---|---|---|
| **1. Création** | bloc 0 | Le créateur (dev) déploie le token : supply fixe de 1 milliard (6 décimales), mint et freeze authority révoquées d'office (pas de honeypot par gel possible) | Sniping au bloc de création |
| **2. Bonding curve** | minutes → heures | Courbe à produit constant avec réserves virtuelles (~30 SOL / ~1,073 Md tokens au départ, ~793,1 M de tokens vendables). Le prix monte mécaniquement à chaque achat | Scalping, momentum, détection précoce |
| **3. Pré-migration** | derniers % de la courbe | Quand ~85 SOL réels sont collectés (market cap ≈ 60–70 k$ selon le prix du SOL), la courbe est complète | Front-run de graduation |
| **4. Migration ("graduation")** | instantanée | La liquidité migre vers PumpSwap (historiquement Raydium), LP verrouillée/brûlée. ~1 % des tokens y arrivent | Achat post-migration, swing |
| **5. Post-migration** | heures → semaines | AMM classique, arrivée d'agrégateurs (Jupiter), de bots et de traders plus « lents » | Swing, position |

Programme principal : `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P` (événements Anchor `Create`, `Trade`, `Complete` décodables dans les logs). AMM post-migration : PumpSwap (`pAMM...`).

---

## 1. Données de base (ce que tout le monde regarde)

Ces données sont nécessaires mais **non suffisantes** : elles sont visibles par tous, donc déjà intégrées dans le prix quelques secondes après leur apparition.

### 1.1 Prix et valorisation

| Donnée | Définition | Usage |
|---|---|---|
| **Prix spot** | `réserves_SOL_virtuelles / réserves_tokens_virtuelles` sur la courbe ; prix AMM après migration | Base de tout calcul |
| **Market cap (FDV)** | prix × 1 Md (supply totale, jamais diluée) | Repère universel sur Pump.fun (tout le monde raisonne en mcap, pas en prix) |
| **ATH / distance à l'ATH** | plus haut historique et drawdown courant | Un token à −70 % de son ATH avec du volume qui revient = setup de « second pump » |
| **Multiple depuis le lancement** | mcap actuel / mcap initial (~4–5 k$) | Mesure du « déjà pumpé » : acheter à ×20 n'a pas le même risque qu'à ×2 |

### 1.2 Volume et transactions

| Donnée | Définition | Usage |
|---|---|---|
| **Volume par fenêtre** | SOL échangés sur 1 min / 5 min / 1 h / 24 h | Filtre d'activité minimal |
| **Volume achat vs vente** | ventilation du volume par sens | Le volume brut ment ; le déséquilibre, moins |
| **Nombre de transactions** | count buys / count sells par fenêtre | Beaucoup de petites tx ≠ un gros ordre : à croiser avec le volume |
| **Bougies OHLCV** | chandelles 1 s / 5 s / 1 min (au-delà, inutile en phase courbe) | Support des indicateurs techniques |

### 1.3 Liquidité et courbe

| Donnée | Définition | Usage |
|---|---|---|
| **Réserves réelles / virtuelles** | SOL réellement déposés vs réserves virtuelles de la courbe | Liquidité réelle disponible à la sortie |
| **Progression de la courbe (%)** | ≈ `SOL_réels_collectés / 85` ou `1 − tokens_restants / 793,1 M` | Position dans le cycle de vie ; lisible directement dans le compte `bonding_curve` |
| **Statut** | en courbe / complète / migrée | Change totalement le régime de trading |

### 1.4 Holders et social de surface

| Donnée | Définition | Usage |
|---|---|---|
| **Nombre de holders** | comptes de token non vides | Trop bas = personne ; trop haut trop vite = sybil probable (voir § expert) |
| **Âge du token** | secondes depuis le `Create` | La majorité des tokens meurent en < 30 min |
| **Réponses sur la page Pump.fun** | nombre et rythme des commentaires | Proxy grossier d'attention |
| **Métadonnées** | présence Twitter/Telegram/site, image, description | Un token sans aucun lien social a un taux de rug supérieur |
| **King of the Hill** | mise en avant sur le site à un palier de mcap | Afflux mécanique d'yeux (et de bots) au moment du passage |

---

## 2. Données intermédiaires (dérivées simples, déjà discriminantes)

Ici on ne collecte plus, on **calcule**. Fenêtres courtes (10 s, 30 s, 1 min, 5 min) — sur Pump.fun, une bougie d'une heure est une éternité.

| Métrique | Formule | Signal |
|---|---|---|
| **Net flow** | `Σ volume_achats − Σ volume_ventes` sur la fenêtre | Le carburant réel du prix sur une courbe : net flow > 0 soutenu = pompe alimentée |
| **Buy ratio** | `vol_achats / vol_total` | > 0,65 en continu = demande dominante ; retour < 0,45 = début de distribution |
| **Acheteurs / vendeurs uniques** | wallets distincts par sens et par fenêtre | 40 acheteurs uniques valent plus que 400 tx d'un seul wallet |
| **Taille médiane des achats** | médiane en SOL | Médiane qui monte = des convaincus arrivent ; médiane minuscule + gros volume = bots |
| **Vitesse d'inflow** | SOL nets entrant dans la courbe / minute | Dérivée première du « progrès vers graduation » |
| **Accélération d'inflow** | variation de la vitesse d'inflow | C'est l'accélération, pas la vitesse, qui précède les jambes de hausse |
| **Z-score de volume** | `(vol_1min − μ) / σ` vs historique du token | Détection d'anomalie sans seuil absolu |
| **Ratio volume/holders** | volume 5 min / holders | Très élevé = churn/wash ; sain ≈ rotation modérée |
| **Temps entre trades** | intervalle moyen inter-transactions et sa tendance | L'allongement des intervalles précède la mort du token bien avant la baisse du prix |
| **RSI / EMA courtes** | RSI 14 et croisements EMA 9/21 sur bougies 1–5 s | Utile en phase courbe uniquement comme timing d'entrée, jamais comme thèse |
| **Volatilité réalisée** | `√(Σ r²)` sur rendements 1 s | Dimensionnement de position et des stops |
| **SOL restants avant migration** | `85 − SOL_collectés` | Front-run de graduation : la fin de courbe attire des acheteurs mécaniques |
| **ETA de graduation** | SOL restants / vitesse d'inflow | Un ETA qui passe de « jamais » à « 10 min » est un événement tradable |

---

## 3. Données d'expert (ce que les amateurs ne regardent pas)

C'est ici que se situe l'avantage compétitif. Ces features demandent l'historique on-chain complet, du décodage de transactions et des graphes de wallets — pas juste une API de prix.

### 3.1 Profil du déployeur (le « dev ») — la donnée n°1

Le meilleur prédicteur du destin d'un token Pump.fun n'est pas son chart, c'est **qui l'a créé**.

| Feature | Calcul | Lecture |
|---|---|---|
| **Historique de création** | nombre de tokens déjà déployés par ce wallet (et par son cluster, voir 3.3) | Un « serial deployer » à 40 tokens/semaine ne construit rien : il farme les snipers |
| **Taux de rug historique** | % de ses tokens précédents où le dev a vendu > 80 % de sa position en < 1 h | Feature quasi binaire : > 0 rug avéré = éliminatoire |
| **Taux de graduation historique** | % de ses tokens ayant migré | Les rares devs à 10–20 % de graduation sont des signaux d'achat à eux seuls |
| **Achat initial du dev** | montant du « dev buy » dans la transaction de création | 0 = aucun skin in the game ; > 5 % de la supply = risque de dump massif |
| **Position courante du dev** | % de supply encore détenu + **transferts sortants** vers d'autres wallets | Un dev qui « disperse » vers 10 wallets frais prépare une vente déguisée |
| **Source de financement du wallet** | remonter le premier SOL reçu : CEX (Binance, Coinbase), bridge, ou **wallet lié à un rug précédent** | Le graphe de financement démasque les identités jetables |
| **Âge et activité du wallet** | date de première tx, comportement hors Pump.fun | Wallet créé il y a 4 minutes = jetable |
| **Vente du dev en temps réel** | événement `Trade` de type sell signé par le créateur | **Signal de sortie immédiat et non négociable**, à exécuter en < 1 s |

### 3.2 Snipers et bundles au lancement

La composition des **premiers blocs** détermine la structure de détention pour toute la vie du token.

| Feature | Calcul | Lecture |
|---|---|---|
| **Part snipée** | % de supply achetée dans le même slot que le `Create` (ou les 2–3 slots suivants) | > 20–30 % = le token appartient à des bots qui vendront sur vous |
| **Nombre de snipers connus** | matching contre une liste de wallets snipers identifiés (récurrence sur des milliers de lancements) | Quelques snipers « intelligents » sont un bon signe ; une meute de snipers « spray » non |
| **Détection de bundle** | achats multi-wallets dans le même bundle Jito / même slot, **financés par un ancêtre commun** dans le graphe de transferts | Le dev qui s'auto-achète avec 15 wallets fabrique un faux carnet : % bundlé > 15 % = éliminatoire |
| **Comportement post-snipe** | les snipers du bloc 0 ont-ils déjà revendu ? à quel multiple ? | Des snipers qui *tiennent* au-delà de ×3 en disent long sur l'info dont ils disposent |

### 3.3 Structure de détention (au-delà du « nombre de holders »)

| Feature | Calcul | Lecture |
|---|---|---|
| **Top 10 holders %** | part de supply des 10 premiers (hors courbe et hors LP) | > 25–30 % = un seul acteur peut tuer le chart |
| **Indice HHI** | `Σ (part_i)²` sur tous les holders | Mesure de concentration continue, plus fine que le top 10 |
| **Coefficient de Gini** | Gini sur la distribution des soldes | Distingue « 500 vrais holders » de « 500 miettes + 5 baleines » |
| **Ratio de wallets frais** | % de holders dont le wallet a < 24 h d'existence | > 50 % = armée de sybils, holders fictifs |
| **Clusters de wallets** | composantes connexes du graphe « qui a financé qui » parmi les holders | 80 wallets = parfois 3 personnes ; le vrai nombre de mains est le nombre de clusters |
| **Rétention par cohorte** | % des acheteurs de la fenêtre t encore en position à t+5 min / t+30 min | La rétention distingue une communauté d'un flipper game |
| **Supply en profit** | % de supply dont le prix de revient (reconstruit par wallet) est sous le prix courant | > 90 % en profit après un gros run = tout le monde a une raison de vendre |
| **Prix de revient moyen par palier** | distribution des coûts d'acquisition | Localise les vrais supports (là où les holders repassent en perte) |

### 3.4 Microstructure et détection de manipulation

| Feature | Calcul | Lecture |
|---|---|---|
| **Score de wash trading** | volume généré par des wallets qui achètent ET vendent en boucle courte, cycles A→B→A dans le graphe | Sur Pump.fun le volume se fabrique à 2 $ de frais près ; ce score « nettoie » le volume affiché |
| **Lambda de Kyle (impact prix)** | régression `Δprix = λ × volume_signé` sur les dernières N tx | λ élevé = courbe mince : vos propres ordres seront votre pire ennemi à la sortie |
| **Asymétrie d'impact** | λ mesuré séparément sur les achats et les ventes | Ventes qui impactent plus que les achats = liquidité fantôme côté bid |
| **Whale prints** | transactions > X SOL, horodatées, avec identité du wallet | Un achat de 5 SOL par un wallet à 80 % de win-rate ≠ un achat de 5 SOL aléatoire |
| **Séquences d'accumulation discrète** | même cluster achetant par petits ordres réguliers sur plusieurs minutes | L'accumulation pro cherche à ne pas bouger le prix — invisible sur le chart, visible on-chain |
| **Taux d'échec de transactions** | % de tx failed visant ce token | Congestion = pump violent en cours ; vos ordres arriveront en retard, élargir le slippage ou passer |

### 3.5 Smart money et copy-trading inversé

| Feature | Calcul | Lecture |
|---|---|---|
| **PnL historique par wallet** | reconstruction du PnL réalisé de chaque wallet actif sur ses 100 derniers trades Pump.fun | Fabrique la liste « smart money » (top 1 % de PnL persistant) et la liste « dumb money » |
| **Présence smart money** | nombre et taille des positions smart money sur le token | 2–3 wallets d'élite qui entrent dans les 5 premières minutes = le signal d'achat le plus fiable de cet écosystème |
| **Contre-indicateur dumb money** | afflux massif de wallets systématiquement perdants | Statistiquement exploitable en sens inverse (signal de sommet) |
| **Win-rate des KOL wallets** | wallets publics d'influenceurs et performance *après* leurs calls | Permet de trader le call du KOL… ou son fade, selon son historique réel |

### 3.6 Social quantifié (au-delà du « il y a un Twitter »)

| Feature | Calcul | Lecture |
|---|---|---|
| **Vélocité de mentions** | mentions X/Telegram par minute + **dérivée** | C'est l'accélération des mentions qui précède le prix, pas leur niveau |
| **Qualité des mentionneurs** | followers réels, ancienneté, taux de bots des comptes qui postent | 50 comptes créés hier = campagne payée |
| **Empreinte de l'image** | hash perceptuel du logo comparé aux tokens passés | Image recyclée d'un rug précédent = même équipe, éliminatoire |
| **Similarité de nom/ticker** | distance d'édition avec les tokens en tendance | Copycat d'un token qui pompe = durée de vie en minutes, tradable uniquement en scalp assumé |
| **Détection de méta** | clustering des noms/thèmes des lancements de la dernière heure | Être dans la méta du moment (animal, IA, actu politique…) multiplie la probabilité d'attention ; les 2–3 premiers d'une nouvelle méta capturent presque tout |
| **Vélocité des replies Pump.fun** | commentaires/min et nombre d'auteurs uniques | Version pauvre mais gratuite de la vélocité sociale |

### 3.7 Contexte de marché (le régime au-dessus du token)

| Feature | Calcul | Lecture |
|---|---|---|
| **Tendance SOL** | prix et momentum de SOL | SOL en chute = appétit memecoin qui s'évapore, tous signaux atténués |
| **Débit de lancements** | tokens créés/heure sur tout Pump.fun | Débit très élevé = attention diluée, taux de survie par token en baisse |
| **Taux de graduation glissant** | % de tokens migrés sur 24 h glissantes | Baromètre de l'appétit au risque de tout l'écosystème |
| **Volume agrégé Pump.fun** | volume total plateforme + part des 10 plus gros tokens | Marché concentré sur 2 tokens = le vôtre n'aura pas d'yeux |
| **Heure et jour** | fuseaux US/Asie/Europe, week-end | La liquidité memecoin a une saisonnalité intraday marquée et mesurable |
| **Frais de priorité / tips Jito ambiants** | percentiles des priority fees réseau | Coût d'exécution réel du moment ; en pic de congestion, une stratégie rentable devient perdante |

### 3.8 Checklist anti-rug consolidée (filtres éliminatoires)

À évaluer **avant** toute entrée, en < 1 seconde de calcul :

1. Dev déjà associé à un rug (directement ou via son cluster de financement) → **NON**
2. Supply bundlée au lancement > 15 % → **NON**
3. Top 10 holders (hors courbe) > 30 % → **NON**
4. Dev détient encore > 5 % ET a commencé à transférer vers des wallets frais → **NON**
5. Part snipée au bloc 0 > 30 % → **NON**
6. Image/nom recyclés d'un scam précédent → **NON**
7. > 50 % de holders sur wallets de < 24 h → **NON**

*(Mint/freeze authority et LP : déjà neutralisés par le protocole Pump.fun lui-même — inutile de les re-vérifier en courbe, contrairement aux tokens Raydium classiques.)*

---

## 4. Données d'exécution (l'edge invisible des backtests)

Sur Pump.fun, la qualité d'exécution **est** une partie de la stratégie :

- **Latence de détection** : délai entre l'événement on-chain et votre signal (WebSocket ≈ 0,5–2 s ; Geyser/gRPC ≈ 50–200 ms). Les stratégies de bloc 0 se jouent en gRPC + bundles Jito, pas en API REST.
- **Priority fee et tip Jito optimaux** : payés trop bas = tx en retard ou échouée ; trop haut = edge mangé. À calibrer dynamiquement sur les percentiles du moment.
- **Slippage réel sur la courbe** : votre propre impact est calculable *exactement* à l'avance (produit constant) — simulez-le avant d'envoyer.
- **Frais complets par aller-retour** : ~1 % de frais protocole par swap ×2 + priority fees + tip + votre impact. Un scalp à +8 % brut peut être négatif net.
- **Taux de réussite de vos propres tx** : à monitorer comme une métrique de production.

---

## 5. Sources de données

| Source | Ce qu'elle fournit | Latence / coût |
|---|---|---|
| **RPC Solana + Geyser/Yellowstone gRPC** (Helius, Triton…) | Flux brut de transactions du programme Pump.fun : la vérité, tout en dérive | La plus basse latence ; demande du décodage (IDL Anchor) |
| **PumpPortal** | WebSocket gratuit : créations de tokens + trades en temps réel, API de trading | Simple, latence moyenne — idéal pour prototyper |
| **Bitquery** | GraphQL/streams : trades Pump.fun historiques et temps réel, transferts, balances | Historique profond, pratique pour le backtest |
| **Moralis / SolanaTracker** | Endpoints prêts à l'emploi : nouveaux tokens, courbe, gradués, prix, holders | Confort maximal, latence supérieure |
| **DexScreener / Birdeye / GeckoTerminal** | Prix, volume, paires (surtout post-migration) | Gratuit/bon marché, non adapté au bloc 0 |
| **GMGN / Photon / BullX / Axiom** | Features pré-calculées : % snipers, % insiders, % bundlé, historique du dev | Utile pour valider vos propres calculs |
| **RugCheck** | Score de risque, autorités, LP (post-migration) | Vérification complémentaire |
| **API X/Twitter, Telegram (Telethon)** | Données sociales brutes pour les features du § 3.6 | Le social propre coûte cher ; les replies Pump.fun sont le substitut gratuit |
| **Jito** | Envoi de bundles, données de tips | Indispensable pour le sniping compétitif |

Principe d'architecture : **enregistrez tout le flux en continu** (créations, trades, transferts) dans votre propre base. Les tokens morts disparaissent des API publiques — sans capture live, votre historique est biaisé (voir § 7).

---

## 6. Assembler : exemple de score composite

Une structure éprouvée : **filtres éliminatoires** (checklist § 3.8) puis **score pondéré** sur ce qui reste.

```
Score = 0,25 × S_dev          (historique du déployeur, § 3.1)
      + 0,20 × S_flow         (net flow, accélération, acheteurs uniques, § 2)
      + 0,15 × S_distribution (Gini, clusters, wallets frais, § 3.3)
      + 0,15 × S_smartmoney   (présence smart money, § 3.5)
      + 0,15 × S_social       (vélocité de mentions, méta, § 3.6)
      + 0,10 × S_contexte     (régime marché, § 3.7)
```

- Chaque sous-score est normalisé en percentile **par rapport aux lancements comparables de la même heure** (jamais en absolu : les seuils dérivent avec les métas).
- Entrée uniquement au-dessus d'un percentile cible (ex. top 5 % des lancements de l'heure).
- **Sorties pilotées par les données, pas par le prix seul** : vente du dev (immédiate), net flow 30 s négatif + pic de vendeurs uniques (sortie), rétention de cohorte qui s'effondre (sortie), sinon take-profits échelonnés + durée de détention max.
- Poids à réestimer chaque semaine : sur ce marché, un edge a une demi-vie de quelques semaines.

---

## 7. Pièges du backtest (où meurent les stratégies)

1. **Biais du survivant** — tester sur les tokens encore listés = tester sur les gagnants. Il faut la population complète des lancements, captée en live.
2. **Latence fictive** — vous ne pouvez pas acheter le prix affiché au moment du signal. Simulez : délai de détection + délai de slot + probabilité d'échec de tx.
3. **Impact ignoré** — sur une courbe mince, votre ordre de 2 SOL bouge le prix. L'impact est calculable exactement : intégrez-le à l'aller **et au retour**.
4. **Frais complets oubliés** — 1 % ×2 + priority + tip transforment beaucoup de stratégies « rentables » en machines à perdre.
5. **Distribution en loi de puissance** — la quasi-totalité du PnL vient de < 5 % des trades. Médiane négative ≠ stratégie perdante ; tester la robustesse en retirant les 3 meilleurs trades.
6. **Dérive de méta** — un modèle entraîné sur la méta « animaux » de janvier ne vaut rien en mars. Validation glissante obligatoire, jamais un simple train/test fixe.
7. **Sur-apprentissage des seuils** — « top10 < 27,3 % » est du bruit déguisé en science. Préférer des percentiles relatifs et des règles simples.

---

## Résumé : la hiérarchie de valeur des données

```
Valeur prédictive (croissante) :
prix seul  <  volume brut  <  flux signés (net flow, acheteurs uniques)
           <  structure de détention (clusters, Gini, snipe/bundle)
           <  identité et historique des acteurs (dev, smart money)
```

Les amateurs tradent le **chart**. Le chart est la dernière donnée de la chaîne : tout ce qui le fait bouger est visible on-chain **avant** — dans les flux, dans la structure de détention, et surtout dans l'identité de ceux qui achètent et vendent.
