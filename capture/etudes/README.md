# Études d'événement

Registre des hypothèses testées sur la capture, succès **et** échecs. Le
cimetière compte autant que les survivants : il évite de re-tester les mêmes
mirages et documente la correction pour tests multiples.

Chaque étude est un fichier SQL exécutable :

```bash
clickhouse-client --password "$CLICKHOUSE_PASSWORD" -n < etudes/pregraduation.sql
```

---

## Registre

| # | Hypothèse | Verdict | Où |
|---|---|---|---|
| 1 | Achat inconditionnel à T+1 min | ❌ 0,940 net | — |
| 2 | Filtre sur l'activité de la 1re minute (trades, acheteurs, inflow) | ❌ meurt au retrait des 3 meilleurs | — |
| 3 | Sortie sur vente du dev | ❌ inversé (1,000 vs 0,963) | — |
| 4 | Sortie sur net flow négatif / excès de vendeurs | ❌ inversé, instable selon l'âge | — |
| 5 | Entrée au remplissage de courbe, sortie à la graduation | ❌ **tué** — le stop portait tout l'edge | `pregraduation.sql` |
| 6 | **Persistance du PnL des wallets (smart money)** | ✅ **seul survivant** | — |
| 7 | Élimination par historique de rug du dev | ⚠️ médiane oui, moyenne non | — |
| 8 | Copier les wallets d'élite (entrée après eux) | ❌ **inversé** — on achète leur sortie | — |
| 9 | Sortie conditionnée au flux acheteur | ❌ attendre coûte plus que le meilleur fill | — |
| 10 | Acheter toute graduation sur PumpSwap | ⚠️ médiane +1,2 % stable, moyenne à zéro | `pumpswap-decode.sql` |
| 11 | Élimination des effondrements post-migration | ⚠️ effondrements ÷ 7, espérance encore nulle | — |
| 12 | Suivre les tips Jito | ❌ **inversé** — 0,88 avec 10+ tips |  — |
| 13 | Éliminer les tokens touchés par des perdants persistants | ❌ effet réel mais 10× trop faible | — |
| 14 | Le rôle de créateur *(mesure, pas stratégie)* | ℹ️ seul rôle rentable : 67 % de gagnants | — |

> **Les études 15 à 18 et 21 portent toutes sur le MÊME signal** — le réveil
> après consolidation de la 15. La 16 dit sur quelle liquidité il marche, la 17
> comment en sortir, la 18 quels pools écarter avant d'entrer, la 21 qu'il ne
> survit pas au-delà de 30 minutes. Les chiffres du tableau sont ceux de la
> refonte sur population certifiée SOL, seuls valides.

| 22 | **Explosion du bruit** | ❌ **pire que l'achat au hasard** — 0,90 contre 0,96, et 3× plus de pertes lourdes | `explosion-du-bruit.sql` |
| 21 | Le range en multi-heures | ❌ **l'effet ne survit pas au-delà de 30 min** — moyenne 0,9149 contre 0,9432 pour la baseline | `multi-heures.sql` |
| 20 | Trois stratégies à contre-courant | ❌ **les trois mortes** — le preneur paie le gap dans les deux sens | `wtf-postgraduation.sql` |
| 19 | **Acheter toutes les graduations** | ❌ **perdant à tous les horizons** — médiane 0,088 et moyenne 0,739 à 30 min | `acheter-les-graduations.sql` |
| 18 | **Range — quels pools écarter** | ✅ **surplomb 2,99 contre 0,14** ; pertes lourdes de 10 % à **0,6 %** | `filtre-surplomb.sql` |
| 17 | **Range — comment sortir** | ✅ **la réintégration est la meilleure sortie** — moyenne 0,9922 contre 0,9822 sans stop | `sortie-fill-reel.sql` |
| 16 | **Range — sur quelle liquidité** | ✅ gradient monotone, gagnants **47 % → 85 %** ; quintile 4 seule moyenne > 1 | `liquidite-discriminante.sql` |
| 15 | **Réveil après consolidation — LE signal de range** | ⏳ **bat la baseline sur toutes les mesures** (0,9834 contre 0,9501) mais reste sous 1 | `reveil-postgraduation.sql` |

---

## Étude 5 — Pré-graduation

**Mécanisme.** Sur une bonding curve, le prix est une fonction déterministe des
réserves. Le rendement entre un niveau de remplissage et la graduation est donc
connu à l'avance ; le seul aléa est d'y parvenir. C'est un pari de probabilité,
pas une prédiction de prix. Le mécanisme est solide ; c'est l'exécution qui le tue.

**Exécution testée.** Entrée au franchissement d'un niveau de remplissage, stop
à −20 %, sortie dans la poussée de graduation, sinon prix à +15 min.

### Résultat (19 h de capture, 10 août 2026)

Espérance nette, impact et frais inclus :

| Seuil | 0,25 SOL | 0,40 SOL | 0,50 SOL | 0,90 SOL | n |
|---|---|---|---|---|---|
| **40 %** | **1,0474** | **1,0370** | **1,0300** | 1,0022 | 1 171 |
| 50 % | 1,0127 | — | 0,9942 | — | 894 |
| 60 % | 1,0071 | — | 0,9878 | — | 684 |
| 75 % | 0,9723 | — | 0,9502 | — | 506 |

L'optimum est plat entre 0,4 et 0,5 SOL — au-delà, l'impact reprend exactement
ce que la taille apporte. Gain maximal ≈ 0,015 SOL par trade.

**Structure du résultat** : 79 % des positions sont stoppées à −20 %, 38 %
graduent, et la médiane des graduations est à **×2,33**. La stratégie perd
quatre fois sur cinq et se rattrape sur la queue — mais une queue *mécanique*,
pas une loterie.

### Robustesse — passée, puis annulée par le fill du stop

L'hypothèse passait les deux tests classiques : 1,0030 après retrait des 25
meilleurs trades sur 1 171, et 7 tranches de 3 h positives sur 7. C'est ce qui
l'avait fait retenir.

**Ces tests ne testaient pas la bonne chose.** Ils vérifient qu'un résultat ne
repose pas sur quelques coups de chance ni sur une fenêtre temporelle
particulière — mais pas qu'il est exécutable. Or 79 % des positions se terminent
au stop : la stratégie était entièrement déterminée par une hypothèse
d'exécution, pas par un signal.

### Le fill réel tue l'hypothèse

Mesuré sur le flux : viser −20 % donne un fill médian à **−26,4 %** avec une
seconde de réaction. Le franchissement se fait *par* une vente qui a déjà creusé
(−22,3 % au déclenchement), et ça continue de tomber (−27,8 % à 3 s).

| Stop visé | Déclenche | Fill réel | Espérance nette |
|---|---|---|---|
| 0,99 | 87,3 % | 0,9475 | **1,0016** |
| 0,95 | 84,9 % | 0,9176 | 0,9860 |
| 0,90 | 82,6 % | 0,8530 | 0,9741 |
| 0,80 | 78,4 % | 0,7347 | 0,9500 |
| 0,70 | 74,9 % | 0,6201 | 0,9357 |
| sans stop | — | — | 0,9774 |

Resserrer le stop améliore l'espérance de façon monotone — un stop très serré
devient un filtre de momentum : on ne reste que dans les tokens qui ne reculent
jamais, et ceux-là graduent. Mais le plafond est à **+0,16 %**, soit zéro, et il
ne survit à aucun des frottements restants : 6,4 % des ventes échouent, la
réaction à 1 s est optimiste, et un stop sur un niveau évident est exactement ce
qu'un adversaire chasse.

**Verdict : tué.** Ce n'était pas un edge, c'était un artefact de modélisation du
stop.

### Les chiffres invalidés, conservés pour mémoire

Le tableau de résultats ci-dessus (jusqu'à 1,0474) suppose une sortie au niveau
théorique du stop. Il est **faux**, et n'est gardé que pour montrer l'ampleur de
l'écart : même population, même signal, même machinerie — +4,7 % avec un stop
imaginaire, −1,8 % avec le stop réel.

Sur cette base on aurait annoncé 10 à 15 SOL/jour. La réalité est une perte
d'environ 6,5 SOL/jour.

### Erreurs commises pendant cette étude, et corrigées

Elles sont consignées parce qu'elles se reproduiraient sans ça.

1. **Seuil de graduation appliqué comme constante universelle.** Faux pour les
   27 % de tokens qui « graduent » par migration instantanée sans accumuler de
   SOL. Corrigé : population définie explicitement.
2. **Impact confondu avec le mouvement de prix.** Une position S dans une réserve
   V déplace le prix de `2S/V`, mais ne coûte que `S/V` par sens. Avoir confondu
   les deux a d'abord divisé l'estimation par trois, à tort.
3. **`k = v_sol × v_tok` traité comme un invariant.** La courbe Pump.fun est
   dynamique. Cette hypothèse a fait conclure à tort à 23 % de données corrompues
   — vérification faite par RPC, la capture est fidèle et le décodeur correct.
4. **Stop modélisé à son niveau théorique**, et non à son fill réel. La plus
   coûteuse : elle a fait annoncer un edge de +4,7 % là où l'exécution réelle
   donne −1,8 %. Une stratégie qui se termine au stop 79 % du temps est
   *entièrement* déterminée par la qualité de ce stop.

Les trois règles qui en découlent sont gravées dans `../README.md`.

### Ce qui reste de cette étude

La machinerie : population explicite, impact intégré, fill de stop mesuré, deux
tests de robustesse. Elle se réutilise telle quelle pour la prochaine hypothèse.
C'est le vrai livrable — l'usine, pas l'edge.


---

## Étude 10 — Acheter toute graduation (PumpSwap)

**RÉSULTATS RETIRÉS — ils avaient été calculés avec un décodeur faux.**

Le décodeur a depuis été refait à partir de l'IDL Anchor publié on-chain, et validé
par deux contrôles dont un non circulaire. L'étude est à refaire.

Les chiffres de cette section ont été calculés avec un décodeur invalide. Ils
sont conservés uniquement comme trace de l'erreur.

Le flux contient **six formes d'événements** (BuyEvent 457 et 472 octets,
SellEvent 409, plus trois non identifiées de 64, 72 et 200 octets), décodées
avec un seul jeu d'offsets. Conséquence : des pools amorcés à 83 SOL affichent
une médiane de 40 175 SOL, et 91 pools sur 97 voient leurs réserves s'effondrer
d'un facteur 1 000.

**La validation d'origine était circulaire** : elle comparait le prix issu des
réserves au prix issu des montants, deux quantités lues aux mêmes offsets dans
le même événement. Un tel contrôle ne peut pas échouer — il passait sur les six
formes, y compris les absurdes.

Le test qui aurait dû être fait relie **deux événements distincts** : entre deux
trades consécutifs d'un même pool, la variation des réserves doit égaler le
montant du trade. Résultat : écart relatif de 85 à 1 185 fois. Échec sur les six
formes.

### Ce qui est mesuré

Entrée à la première minute du pool, sortie 30 minutes plus tard, sur les pools
amorcés entre 70 et 100 SOL (signature d'une graduation Pump.fun, médiane
83,3 SOL). Impact et frais PumpSwap (0,6 % l'aller-retour) inclus.

| Taille | Moyenne nette | Médiane | Gagnants |
|---|---|---|---|
| 0,25 SOL | 1,713 | 0,988 | 47,8 % |
| 1 SOL | 1,687 | 0,972 | 47,8 % |
| 2 SOL | 1,654 | 0,950 | 47,8 % |

Trois éléments favorables et indépendants du résultat statistique : les frais
sont trois fois plus faibles qu'en courbe, l'impact est négligeable (pools de
83 SOL de profondeur), et le taux de gagnants est de 47,8 % contre 24 % en
courbe.

### Pourquoi ce n'est pas concluant

- **n = 46.** Sur un profil de queue, un seul token à ×30 produit ce résultat.
- **Sept heures de capture PumpSwap.** Il faut une semaine pour ~2 000
  observations, un mois pour un walk-forward.
- **Les prix sont des cotations, pas des exécutions.** La performance est
  calculée sur le prix issu des réserves au dernier trade de chaque minute, avec
  l'impact appliqué par-dessus. Aucun fill n'est simulé, aucun délai de détection
  de la migration n'est modélisé — et l'espérance chute de 1,80 à 1,19 entre une
  entrée à la minute 0 et une entrée à la minute 5.
- **Des artefacts subsistent** dans la série de prix : sur certains pools, les
  moyennes explosent à des valeurs de l'ordre de 10⁶, signe que `base_reserves`
  tombe à des valeurs dégénérées. Les médianes sont robustes, les moyennes ne le
  sont pas tant que ces pools ne sont pas identifiés et écartés.

### Règle de sortie testée : « N secondes sans achat = vente »

| Silence | Sortie médiane | Médiane nette | Gagnants |
|---|---|---|---|
| 3 s | 7 s | 0,9933 | 13,4 % |
| 5 s | 10 s | 0,9932 | 13,4 % |
| 10 s | 27 s | 0,9332 | 12,4 % |
| 30 s | 301 s | 0,6820 | 19,6 % |

La règle sort très vite (10 s médiane à 5 s de silence) et rend une médiane de
0,9932 — on paie les frais et on sort. Elle protège du scénario long (0,682 à
30 s de silence) mais ne crée pas d'espérance. Les moyennes ne sont pas
reportées : elles sont polluées par les mêmes artefacts.

### Erreur de méthode n°5, commise pendant cette étude

**Définir une population par une propriété technique plutôt qu'économique.**
La première version prenait « tout nouveau pool PumpSwap » — 1 245 pools et
3 626 migrations/jour, alors qu'on en mesure moins de mille sur la courbe. La
population contenait des paires sans rapport avec Pump.fun. Le filtre correct
porte sur la profondeur d'amorçage du pool, signature économique de la
graduation.


---

## Étude 15 — Réveil après consolidation *(post-graduation)*

**Mécanisme.** Un token qui reste 30 minutes dans un couloir de ±10 % a laissé
sortir ses vendeurs impatients : l'offre disponible est épuisée. La cassure du
haut du couloir part alors contre peu de résistance. Hypothèse sur une
*contrainte*, pas sur une opinion.

**Règle.** Fenêtre **strictement passée** de 30 minutes, `haut/bas ≤ 1,10`,
≥ 60 trades, cassure à `haut × 1,01`. Entrée à la minute suivante. Taille
plafonnée à 10 % des réserves du pool.

### Pourquoi pas sur la bonding curve

91,7 % des tokens sont morts à 60 minutes, moins de 1 % encore actifs. Résultat :
142 signaux sur **13 tokens**, aucune hausse. Ce qu'on y appelle « couloir » est
un token endormi faute d'acheteurs. Sur PumpSwap, 2 035 pools vivent au-delà
d'une heure.

### Résultats (55 h de capture PumpSwap)

L'arbitrage de la sortie est le résultat principal : **il n'y a pas de signal de
sortie**, seulement un choix entre rendement médian et queue gauche.

| Horizon | n | Médiane | Gagnants | Perd > 20 % |
|---|---|---|---|---|
| 30 min | 352 | 1,0245 | 64,5 % | **6,6 %** |
| 60 min | 332 | **1,0360** | 62,3 % | 12,7 % |
| 120 min | 309 | 1,0619 | 59,2 % | **22,7 %** |

**Baseline appariée** — mêmes pools, mêmes instants, sans condition de réveil :
**1,0000**. L'écart est donc l'intégralité du rendement.

Une sortie conditionnelle sur invalidation de la cassure n'apporte rien
(médiane 1,0315, pertes lourdes 10,5 %) : elle se déclenche à la minute 14 à
0,9422, c'est-à-dire après une baisse — le même problème que le stop de
l'étude 5.

### Les tests passés

| Test | Résultat |
|---|---|
| Baseline appariée (médiane) | **+2,4 points** — 1,0184 contre 0,994 |
| Sensibilité aux paramètres | **9 combinaisons sur 9 positives** |
| **Retrait des extrêmes (moyenne)** | ❌ **0,9698 sans les 10 meilleurs sur 523** |
| **Fill réel à l'entrée** | **0,9979 — favorable de 0,2 %** |
| Fill réel à la sortie | 0,9988 — 0,1 % contre |
| Frais réels *(mesurés dans les événements)* | 0,55 % l'aller-retour ; on en modélise 0,6 % |
| Illusion de report | ❌ écartée — **100 %** des signaux ont ≥ 10 trades dans la fenêtre de sortie |

Le fill est le test qui a tué l'étude 5, et celle-ci le passe. L'asymétrie est
mécanique : on **achète dans une hausse qui débute** et on **vend à un instant
planifié**, jamais dans une cascade.

### Ce qui manque

- **Aucune fenêtre de validation** : les 352 signaux couvrent toute la capture.
- **73 % des signaux dans une seule tranche de 6 h** — ce peut être un régime.
- Les **moyennes sont inutilisables**, polluées par quelques pools dont le prix
  explose. Seules les médianes sont reportées.
- La **sélection adverse** n'est mesurable qu'en micro-réel.

**Verdict : à revalider sur données neuves, sans toucher un paramètre.**

### Erreurs de méthode n° 10 et 11, corrigées ici

10. **`leadInFrame(prix, 61)` renvoie 61 lignes, pas 61 minutes.** Ces pools ne
    tradent que 27 % des minutes : le « +60 min » valait 62 minutes à la médiane
    mais 159 au 9<sup>e</sup> décile, et le +180 sortait de la partition avec un
    décalage négatif. Corrigé par une série dense à prix reporté.
11. **Le facteur d'impact devenait négatif** sous 0,5 SOL de réserves, donnant
    des moyennes à −2 400. Corrigé par la contrainte de taille — qui est de
    toute façon une règle de bon sens : on ne prend pas 0,5 SOL dans un pool qui
    en contient 0,2.

Les deux ont été repérées parce qu'un chiffre était **absurde**, pas parce que
le raisonnement avait été vérifié. Le réflexe fonctionne ; il ne remplace pas
d'écrire à quel instant chaque variable est connue.


---

## Erreur de méthode n° 12 — ne pas refaire les tests après correction

Le verdict « le plus prometteur » de l'étude 15 reposait sur un test de
robustesse (« 1,0339 → 1,0258 sans le top 5 ») calculé sur la table **à horizons
faussés**, avant la correction de l'erreur n° 10. Une fois la série densifiée, la
mesure principale a été refaite — **mais pas le test de robustesse**. Il échoue :
0,9698 sans les 10 meilleurs.

Ce n'est pas un calcul faux, c'est une conclusion non recalculée. C'est plus
insidieux : rien dans les chiffres ne signale l'incohérence, puisque chaque
nombre pris isolément est correct.

**Règle : après toute correction de données, refaire TOUS les tests, pas
seulement la mesure principale.** Et pour toute stratégie, reporter systématiquement
médiane *et* moyenne tronquée — une médiane seule cache exactement ce cas.


---

## Hypothèse 16 — la liquidité discrimine (et corrige la lecture de la 15)

### L'objection qui a relancé l'étude

Le verdict de la 15 reposait sur le retrait des extrêmes. **L'objection est juste :
dans une loi de puissance, retirer la queue retire le mécanisme, pas le bruit.**
Le capital-risque a exactement ce profil. La bonne question n'était pas « la
moyenne survit-elle au trim » mais **« qu'ont ces tokens en commun »**.

Réponse : la liquidité. Après exclusion des 23 pools hors SOL, sur 492 signaux :

| Quintile de réserve | SOL | Médiane | Gagnants | Moyenne hors queue |
|---|---|---|---|---|
| 1 | 6 – 322 | 0,987 | 44,4 % | 0,9527 |
| 2 | 327 – 618 | 1,0051 | 60,6 % | 0,9584 |
| 3 | 619 – 1 343 | 1,0164 | 68,4 % | 1,0063 |
| 4 | 1 351 – 2 895 | 1,0308 | 78,6 % | 0,9867 |
| **5** | **2 909 – 14 443** | **1,0426** | **85,7 %** | 0,997 |

**Monotone sur les deux colonnes, de 44 % à 86 % de gagnants** — et ce gradient ne
doit rien à la queue : médiane et taux de gagnants sont insensibles aux extrêmes.
C'est le résultat solide de l'étude, sur ~98 observations par tranche.

### Ce que le filtre change, et ce qu'il ne change pas

Il **ne transforme pas** la stratégie en rente : la moyenne hors queue reste sous 1
partout (0,997 au meilleur quintile). Il fait passer le *grind* de **perdant à
nul** — on gagne 86 % du temps, petit, on perd gros 14 % du temps, et le résultat
net hors loterie est plat. **L'espérance reste portée par la queue.**

C'est un modèle d'affaires légitime, à trois conditions : que le taux de queue
soit stable, qu'on encaisse assez de tirages, et que le dimensionnement survive
aux pertes lourdes.

### Ce qui manque pour conclure : du temps, pas des idées

Le taux de queue repose sur **5 événements**. L'intervalle de Poisson à 95 % pour
5 observations va de 1,6 à 11,7 — soit un taux réel entre 0,3 % et 2,2 %, **un
facteur 7 d'incertitude**. Les mesures par tranches de 12 h le confirment : 0 %,
0,31 %, 2,94 %, 3,23 %, 5,13 %.

Serrer ce taux à ±30 % demande une quarantaine d'événements. Au rythme observé
avec le filtre — environ un par jour — cela fait **six semaines de capture**.

> **523 signaux, c'est beaucoup pour une médiane et rien pour une queue.** Les
> deux quantités ne se mesurent pas à la même vitesse. C'est la leçon
> transposable : dire « n = 523 » sans préciser *de quoi* est une illusion de
> précision.

### Réserve de méthode

Le discriminant a été cherché sur 4 variables × 5 quintiles, soit 20 comparaisons.
« 4 extrêmes sur 5 dans le quintile haut » vaut p ≈ 0,7 % isolément, **mais ne
survit pas à la correction pour comparaisons multiples** (p ≈ 0,13). Cette moitié
du résultat n'est pas établie. Le gradient de médiane et de taux de gagnants,
lui, tient sans la queue et ne dépend pas de ce test.

---

## Erreur de méthode n° 13 — confondre « la queue est fragile » et « la stratégie est nulle »

Le test du retrait des extrêmes détecte une queue **accidentelle**. Appliqué à une
distribution dont la queue *est* le mécanisme, il condamne mécaniquement toute
stratégie de loi de puissance — y compris les bonnes.

**Règle : quand le trim tue une stratégie, ne pas conclure. Vérifier d'abord si la
queue se reproduit à un taux stable et ce qui distingue ses membres.** Un trim qui
échoue est une question, pas un verdict.

Corollaire consigné : **`pumpswap_trades` n'a pas de colonne `quote_mint`.** Les
pools hors SOL ne peuvent être écartés que par un seuil sur les réserves, ce qui
est fragile. À capturer.


---

## Hypothèse 17 — les stops au fill réel : le problème n'est pas la sortie

484 signaux, déclenchement lu sur les **trades bruts** (486 par fenêtre de 30 min
à la médiane), fill au premier trade **≥ 1 seconde après** le déclencheur.

### Le stop en pourcentage est inexécutable

| Stop −20 % | |
|---|---|
| Prix du trade déclencheur | 0,9241 × le niveau visé |
| **Fill 1 s plus tard** | **0,5697 × le niveau visé** |
| Fill au 1er décile | 0,0007 |
| Traversées de plus de 10 % | 40,9 % |
| Traversées de plus de 50 % | 22,7 % |

Un stop à −20 % sort en réalité à **−54 %**. Il confirme la règle gravée.

### La réintégration se remplit bien — et ne sert quand même à rien

Sortir quand le prix repasse sous le haut du couloir se remplit à **0,9832** du
niveau visé, contre 0,5697 pour le stop en pourcentage : le déclenchement arrive
à −2,6 %, avant tout effondrement. **C'est exécutable.** Mais le résultat ne
s'améliore pas, parce que la perte qui compte n'est pas une baisse.

### Ce qui tue vraiment : le retrait de liquidité

61 événements où les réserves passent de **1 182 SOL à 1,24 SOL — 99,5 % retirés**.
En une transaction, ou en cascade à l'intérieur d'une seconde. **Il n'existe aucun
prix intermédiaire auquel vendre.** Aucun stop, aussi serré soit-il, ne protège :
ce n'est pas un problème de latence, c'est l'absence de contrepartie.

### Le résultat qui change tout : hors rugs, l'edge tient sans la queue

458 signaux, les 26 rugs écartés :

| Règle | Médiane | Gagnants | **Sans top 3** |
|---|---|---|---|
| **Sans stop** | 1,0236 | 71 % | **1,0368** |
| Stop −20 % | 1,0236 | 71 % | 1,033 |
| Réintégration | 1,0228 | 68,3 % | 1,030 |

**+3,7 % par trade après retrait des 3 meilleurs sur 458** — indépendant de la
queue, ce qui manquait depuis le début. Et la meilleure règle de sortie est
**l'absence de stop** : toutes les autres coûtent.

### Conclusion : c'est un problème de filtre, pas de sortie

26 signaux sur 484 (5,4 %) vont à zéro et coûtent ~5,4 points de moyenne. Les 458
autres rapportent +3,7 % de façon robuste. **Toute la viabilité tient à ne pas
acheter les rugs.**

Deux pistes testées, aucune concluante :

- **Le créateur vend avant le signal** : 33,3 % des pools ruggés contre 17,8 % des
  autres. Le double — mais sur 24 rugs, p ≈ 0,09. Suggestif, non établi.
- **L'historique du créateur est inutilisable** : 188 créateurs distincts pour 195
  pools, 3 récidivistes. `dev_profiles` ne peut rien sur cette population.

---

## Erreur de méthode n° 14 — chercher le remède du côté du symptôme

On a cherché à réparer la sortie parce que les pertes apparaissaient à la sortie.
Elles y apparaissaient seulement : elles se **décident** au retrait de liquidité,
que la sortie ne peut pas voir venir.

**Règle : avant d'optimiser une réaction, mesurer si l'événement laisse le temps
de réagir.** Ici la réponse est non — 99,5 % de la liquidité part en une
transaction. Trois familles de stops ont été simulées pour découvrir qu'aucune ne
pouvait fonctionner ; la mesure du gap l'aurait dit d'emblée.


---

## Hypothèse 18 — le surplomb d'un porteur prédit le rug

Cinq prédicteurs **fixés avant mesure**, tous calculés sur des trades strictement
antérieurs au signal. 193 pools, dont 24 ruggés.

| | Pools ruggés | Pools sains |
|---|---|---|
| **Plus gros porteur / réserves de base** | **2,866** | **0,142** |
| Part de portefeuilles nouveaux (30 min) | 0,0338 | 0,0591 |
| Argent neuf net (SOL, 30 min) | 26,65 | 15,08 |
| Part du volume à l'achat | 0,7509 | 0,6619 |
| Le créateur a vendu | 4,2 % | 4,7 % |

### Ce que les intuitions donnaient

- **« Un portefeuille détenait une grande partie des tokens »** — **confirmé, et
  c'est le prédicteur dominant.** Facteur 20 sur la médiane. Le surplomb est
  la condition matérielle du rug : il faut détenir pour pouvoir vider.
- **« Manque de nouveaux holders »** — confirmé, mais faible : 3,4 % contre 5,9 %.
- **« Manque d'achat, d'argent neuf »** — **infirmé, et c'est l'inverse.** Les pools
  ruggés encaissent **26,65 SOL** nets contre 15,08, et 75 % de volume acheteur
  contre 66 %. Évident après coup : **on ne peut extraire que ce qui est entré.**
  L'afflux d'argent n'est pas une protection, c'est l'appât.
- **Le créateur** ne signale rien du tout (4,2 % contre 4,7 %). Cohérent avec
  l'étude 17 : 9 % seulement des ventes massives viennent de lui.

### Le filtre, et ce qu'il coûte

Règle mécanique, non ajustée : écarter si le plus gros porteur dépasse les
réserves du pool.

| | Pools | Taux de rug | Pertes lourdes |
|---|---|---|---|
| Écarté (surplomb) | 82 | 18,3 % | 9,7 % |
| **Gardé** | 111 | **8,1 %** | **2,9 %** |

Il divise les pertes lourdes par 3,3. **Mais il coûte cher en performance** : le
groupe écarté a une *meilleure* médiane (1,0528) et un *meilleur* taux de gagnants
(80 %) que celui gardé (1,0074 et 59,9 %). Un gros porteur pousse le prix aussi
bien qu'il l'effondre. Ce n'est pas un filtre gratuit, c'est un arbitrage.

### Les deux filtres ensemble

Liquidité ≥ 1 000 SOL **et** absence de surplomb — 127 signaux sur 484 :

| | Médiane | Gagnants | **Sans top 3** | Sans top 10 |
|---|---|---|---|---|
| **Gardé** | 1,0188 | **77,2 %** | **1,0096** | 0,9623 |
| Écarté | 1,0231 | 63,6 % | 0,9683 | 0,9607 |

**Premier `sans top 3` au-dessus de 1 obtenu par un filtre applicable à l'entrée**
(1,0368 hors rugs n'était accessible qu'a posteriori). Mais il reste mince, il est
dans l'échantillon, et `sans top 10` reste à 0,9623 — retirer 10 signaux sur 127
est un test sévère. **À valider hors échantillon avant toute conclusion.**

Noter aussi que le filtre combiné **ne réduit pas** les pertes lourdes (5,5 %
contre 5,3 %) : les gros pools sont des cibles plus attirantes, ce qui annule le
gain du filtre de surplomb sur ce plan.

### Réserves

- **Les positions de bonding curve sont invisibles** pour cette cohorte : ces
  tokens ont gradué avant la capture. Le surplomb réel est donc sous-estimé, et le
  filtre sous-performe ce qu'il pourrait faire. Cela s'améliorera seul.
- Un `user` très actif peut être un routeur d'agrégateur plutôt qu'un détenteur.
  Non vérifié.
- 39,6 % des pools sains dépassent aussi le seuil : le surplomb est fréquent, il
  n'est pas une condition suffisante.


---

## Hypothèse 19 — acheter toutes les graduations : tuée

### La population, enfin propre

La signature d'une graduation est une réserve initiale de **67,406 SOL exactement**
— constante à la troisième décimale sur les quatre jours. Pas 85 : la migration
prélève sa part. Cela donne **365 / 468 / 817 graduations par jour**, enfin
cohérent avec le marché.

Et surtout : **aucun biais du survivant**. Ces 1 821 pools sont suivis depuis leur
première seconde, pas retenus parce qu'ils vivaient encore.

### Horizons courts (entrée à +1 s)

| Horizon | Médiane | Moyenne | Sans top 3 | Gagnants | Pertes > 50 % |
|---|---|---|---|---|---|
| 15 s | 0,9958 | 0,9802 | 0,9761 | 38,6 % | 4,2 % |
| 30 s | 0,9997 | 0,9929 | 0,9870 | 49,0 % | 7,6 % |
| 60 s | 1,0053 | 0,9957 | 0,9873 | 56,8 % | 12,6 % |
| **120 s** | **1,0122** | **1,0017** | 0,9904 | 57,7 % | 18,4 % |
| 180 s | 1,0161 | 0,9862 | 0,9716 | 55,3 % | 23,4 % |
| 300 s | 0,9908 | 0,9685 | 0,9418 | 49,6 % | 30,1 % |

Le meilleur point est à 2 minutes : médiane 1,0122, **moyenne 1,0017** — l'équilibre
exact — et **0,9904 sans les 3 meilleurs**. Il n'y a pas d'edge, il y a un sommet
plat au niveau zéro.

### Horizons longs : carnage

| Horizon | Médiane | Moyenne | Sans top 3 | Gagnants | Pertes > 50 % |
|---|---|---|---|---|---|
| 5 min | 0,9908 | 0,9685 | 0,9418 | 49,6 % | 30,1 % |
| 15 min | 0,4075 | 0,7584 | 0,7275 | 36,9 % | 52,5 % |
| **30 min** | **0,0880** | **0,7393** | 0,6716 | 31,7 % | 61,9 % |
| 60 min | 0,0380 | 0,6935 | 0,6520 | 26,7 % | 69,6 % |

**À 30 minutes, la médiane est 0,088** : un token sur deux a perdu plus de 91 %.

### Mécanisme, vérifié

- Les réserves à 30 min valent **23,93 %** des initiales, et **33,3 % des pools
  sont vidés** (moins de 5 SOL). Sur un produit constant, des réserves divisées
  par 4 impliquent un prix divisé par ~16 : **0,0625, cohérent avec la médiane
  mesurée de 0,088.** Les deux chiffres se confirment l'un l'autre.
- Le prix **monte** d'abord : +11,9 % à 1 s, +30,7 % à 30 s, +42,0 % à 60 s. Puis
  il s'effondre. La distribution en cloche des horizons courts en est la trace.
- Prix issu des réserves contre prix réellement exécuté sur 13,5 millions de
  trades : rapport d'ordre 1,06, l'écart attendu du slippage. Décodeur confirmé.

### Ce que cette étude change pour les autres

Les hypothèses 15, 16 et 18 sont mesurées sur des pools **qui avaient déjà survécu**
assez longtemps pour former un couloir de 30 minutes. Cette cohorte-ci montre la
population inconditionnelle : sur 100 graduations, 62 ont perdu plus de la moitié
en 30 minutes.

**Leur edge n'est pas un edge sur le marché, c'est un edge conditionnel à la
survie.** Ce n'est pas invalidant — filtrer est légitime — mais cela impose que
le filtre soit applicable à l'entrée, ce que l'étude 18 a commencé à construire.


---

## Hypothèse 20 — trois paris à contre-courant, trois morts

### 1. Acheter les cadavres (chute de 80 %)

**84,6 % des graduations touchent −80 %, en 86 secondes médianes.** Le couteau ne
s'arrête pas de tomber :

| Horizon | Médiane | Moyenne | Sans top 3 | Gagnants |
|---|---|---|---|---|
| 5 min | 0,856 | 0,8535 | 0,822 | 33,4 % |
| 15 min | 0,4628 | 0,7268 | 0,6952 | 31,4 % |
| 30 min | 0,3252 | 0,6615 | 0,625 | 28,6 % |

### 2. Le pump initial comme signal de danger

Vrai comme description, inutile comme stratégie. Rendement à 30 min selon le
comportement de la première minute :

| Première minute | n | Médiane | Moyenne | Pertes > 50 % |
|---|---|---|---|---|
| −20 % ou pire | 459 | 0,0625 | 0,4801 | 77,3 % |
| Baisse légère | 252 | 0,0939 | 0,7002 | 69,4 % |
| **Hausse < 30 %** | 831 | **0,8749** | 0,7234 | 45,6 % |
| Hausse 30-100 % | 218 | 0,1049 | 0,7177 | 70,2 % |
| Pump > ×2 | 58 | 0,12 | 0,7076 | 63,8 % |

**Les deux extrêmes tuent** — un effondrement comme un pump ×2 mènent au même
désastre, et la zone tiède fait 14 fois mieux en médiane. Mais aucune moyenne
n'atteint 1. Croisée avec les horizons courts, la meilleure combinaison
(hausse douce, 2 min) donne 0,9765 de médiane pour **0,9259 de moyenne**.

### 3. Attraper la mèche

| Maintien | Médiane | Moyenne | Sans top 3 | Gagnants |
|---|---|---|---|---|
| 5 s | 0,9566 | 0,9081 | 0,9046 | 17,2 % |
| 20 s | 0,9578 | 0,8925 | 0,8848 | 20,9 % |
| 90 s | 0,9649 | 0,9100 | 0,8926 | 29,9 % |

### Pourquoi les trois meurent : le preneur paie le gap dans les deux sens

C'est le résultat qui vaut d'être gardé.

| | Fill obtenu |
|---|---|
| Vendre un stop à −20 % | **0,5697 × le niveau visé** — on sort 43 % plus bas |
| Acheter une chute de −80 % | **1,0888 × le niveau visé** — on entre 8,9 % plus haut |

Une seconde de latence coûte dans les deux sens : à la vente le prix a déjà
fui vers le bas, à l'achat il a déjà rebondi vers le haut. Le déclencheur qu'on
observe n'est jamais le prix qu'on obtient.

**La volatilité intra-minute de ces tokens est réelle et énorme — elle n'est
simplement pas accessible à un preneur de liquidité à une seconde.** Elle
appartient à qui est dans le même bloc. Toute stratégie qui a besoin de réagir à
un prix affiché est déjà perdue ; seules survivent celles qui décident sur un
état *antérieur* et acceptent le prix courant, comme les études 15 à 18.


---

## Hypothèse 21 — l'edge multi-heures n'existe pas (et la cassure s'inverse)

323 pools liquides, 641 SOL de réserve médiane, 134 trades par heure : la seule
population où la capacité existe. Position calée à 1 % des réserves.

| | Horizon | n | Médiane | Moyenne | Sans top 3 | Gagnants | Pertes > 50 % |
|---|---|---|---|---|---|---|---|
| **Cassure 6 h** | +3 h | 1 029 | 0,9969 | **0,9153** | 0,9086 | 45,7 % | 12,5 % |
| | +6 h | 1 029 | 0,9938 | **0,8665** | 0,8535 | 47,0 % | 20,4 % |
| | +12 h | 938 | 0,9819 | **0,8137** | 0,7915 | 46,1 % | 33,3 % |
| **Baseline** | +3 h | 9 733 | 0,9742 | **1,047** | 0,9443 | 23,9 % | 6,1 % |
| | +6 h | 9 292 | 0,9742 | **1,0182** | 0,9108 | 29,1 % | 10,9 % |
| | +12 h | 8 274 | 0,9739 | **0,969** | 0,8489 | 32,3 % | 20,0 % |

### La cassure s'inverse

Elle bat la baseline en médiane (+2,3 points) et écrase son taux de gagnants
(45,7 % contre 23,9 %) — **mais sa moyenne est très inférieure** (0,9153 contre
1,047) et elle double les pertes lourdes (12,5 % contre 6,1 %).

C'est exactement le piège de la règle 4. Une médiane et un taux de gagnants
flatteurs sur une stratégie qui perd davantage. **L'effet de consolidation-cassure
est de courte durée** : réel à 30 minutes (études 15 et 16, médiane 1,0184 à
1,0426), nul puis négatif à partir de 3 heures.

### Le chiffre qui dit tout : la médiane est le coût

La médiane de la baseline vaut **0,9742 à tous les horizons** — soit exactement
0,99 × 0,99 × 0,994. Le pool liquide médian **ne bouge pas** entre 3 et 12 heures.
On ne paie que l'aller-retour. Même chose sur les rescapés de graduation, dont la
médiane valait 0,9546 = 0,98 × 0,98 × 0,994 partout, avec 7 trades par heure.

Sur ces horizons il n'y a pas de tendance à capter : il y a un coût à payer et
une queue à espérer.

### Blocage structurel, troisième occurrence

`pumpswap_trades` ne stocke **ni `base_mint` ni `quote_mint`**. Les pools hors SOL
ont maintenant faussé les hypothèses 16, 19 et 21, et ne s'écartent qu'à coups de
seuils fragiles — ici une bande de prix calibrée sur la cohorte de graduation.
**Les mints sont dans les comptes de l'instruction et `resolveAccountKeys` sait
déjà les résoudre.** C'est la correction la plus rentable qui reste à faire.


---

## Correction 22 — les mints, et ce qu'ils détruisent

### Ce qui a été fait

`pumpswap_pools` (table `__DB__`, `ReplacingMergeTree`), alimentée par
`npm run pools` — lecture RPC du compte Pool, `base_mint` à l'offset 43,
`quote_mint` à 75, `coin_creator` à 211. Timer systemd `pumpfun-pools` toutes les
heures. La capture n'a **pas** été redémarrée : l'outil couvre déjà le passé et
l'avenir, un redémarrage aurait créé un trou pour un gain nul.

**31 857 pools identifiés, 0 illisible, 0 hors PumpSwap.** Dont **24 782 en SOL**
et **7 275 hors SOL**, répartis sur **6 057 quotes distincts**.

Validation : la cohorte de graduation ressort **100 % WSOL**, comme elle le doit.

### Ce que valaient mes seuils bricolés

| Mon verdict par bande de prix | Vraiment en SOL | Vraiment hors SOL | Erreur |
|---|---|---|---|
| Écarté | 1 | 452 | 0,2 % |
| **Gardé** | 876 | **225** | **20,4 %** |

Excellent pour écarter, mauvais pour garder. Un pool hors SOL sur cinq passait.

### Ce qui survit : le gradient de liquidité (étude 16)

| Quintile | SOL | Médiane | Moyenne | Sans top 3 | Gagnants |
|---|---|---|---|---|---|
| 1 | 13 – 340 | 0,9967 | 0,961 | 0,943 | 47,4 % |
| 2 | 341 – 619 | 1,004 | 0,966 | 0,9565 | 58,9 % |
| 3 | 620 – 1 343 | 1,0153 | 0,999 | 0,9836 | 68,4 % |
| 4 | 1 351 – 2 870 | 1,0338 | **1,004** | 0,9816 | 80,0 % |
| 5 | 2 890 – 6 837 | 1,0426 | 0,988 | 0,9759 | 85,3 % |

**Monotone sur la médiane et sur le taux de gagnants**, de 47 % à 85 %. Le
résultat tient sur données certifiées.

### Ce qui meurt : le `sans top 3` de l'étude 18

| Filtre combiné, groupe gardé | Avant | **Après** |
|---|---|---|
| n | 127 | 119 |
| Médiane | 1,0188 | 1,0186 |
| Moyenne | 8,258 | **0,993** |
| **Sans top 3** | **1,0096** | **0,9752** |

**Le ×314 qui portait toute la moyenne était dans un pool hors SOL** — et
l'autopsie complète est pire que ça. Le pool est
`8dKmnMw3n2Bj3LiSxwqfjpEhGq3FvQ5Fh4UHLyFUwSGw` : **le SOL y est la base**, le
memecoin `BtAPyCkmCDzaFdCC8MwzkW6wvD7nXKJhMAMsrJ9sGmbV` la quote. Le « prix »
lu était donc celui du SOL libellé dans ce memecoin, et le ×303,8 signifie que
ce token **s'est effondré de 99,67 %**. Vérification on-chain : il n'a aucune
courbe à l'adresse dérivée `["bonding-curve", mint]`, son mint appartient à
**Token-2022** — il n'a jamais été lancé sur Pump.fun, encore moins gradué.

Trois erreurs empilées dans un seul chiffre : mauvais programme d'origine, prix
inversé, et gain qui était une perte. Dix-sept
signaux contaminés sur 484 suffisaient à faire passer le résultat phare
au-dessus de 1. C'était exactement ce que le test de retrait des extrêmes
signalait sans qu'on sache le lire.

Le filtre garde sa valeur sur le taux de gagnants (77,3 % contre 64,4 %) mais
**les deux moyennes sont désormais sous 1 et quasi identiques** (0,993 contre
0,978). L'étude 18 n'est plus un résultat, c'est une piste.

### Ce qui se confirme en pire : le multi-heures (étude 21)

La baseline était gonflée par les pools hors SOL — 1,047 devient **0,9432** à
+3 h, puis 0,9074 et 0,8405. **Tout perd sur plusieurs heures**, la cassure
(0,9149) comme l'achat au hasard. La conclusion ne change pas, elle durcit.

---

## Erreur de méthode n° 15 — un seuil n'est pas une identité

Trois études ont été faussées par des pools qu'aucun seuil ne pouvait écarter
proprement, parce que le seuil approxime ce que la donnée manquante affirmait.
Les mints étaient à portée de RPC depuis le début.

**Règle : quand un filtre demande de deviner une propriété, aller chercher la
propriété.** Le coût ici : un fichier SQL, 150 lignes de TypeScript, et huit
minutes de lecture RPC — contre trois études à refaire.


---

# Refonte complète sur population certifiée SOL

Toutes les études PumpSwap refaites en joignant `pumpswap_pools` sur `est_sol = 1`.
**Second biais corrigé au passage** : les tables de base filtraient sur « pool
vivant ≥ 120 min et ≥ 200 trades », ce qui sélectionne sur l'AVENIR du pool. Il
est remplacé par les seules conditions de décision, qui portent sur le passé.
Base : 24 782 pools, 11,9 millions de barres-minute.

## Étude 15 — le signal bat la baseline sur toutes les mesures

| | n | Médiane | Moyenne | Sans top 3 | Sans top 10 | Gagnants | Pertes > 50 % |
|---|---|---|---|---|---|---|---|
| **Signal, 30 min** | 475 | **1,0211** | **0,9834** | **0,9784** | 0,9709 | **68,0 %** | 5,1 % |
| Baseline, 30 min | 228 372 | 0,9957 | 0,9501 | 0,9492 | 0,9484 | 43,1 % | 9,2 % |
| Signal, 60 min | 450 | 1,0289 | 0,9411 | 0,9348 | 0,9240 | 65,6 % | 12,7 % |
| Signal, 120 min | 419 | 1,0482 | 0,9078 | 0,8981 | 0,8805 | 61,6 % | 21,5 % |

**+3,3 points de moyenne et +2,9 de moyenne tronquée sur la baseline**, avec un
taux de gagnants de 68 % contre 43,1 %. C'est la première fois que l'avantage
tient sur la moyenne tronquée. Mais les deux restent **sous 1**.

## Étude 16 — gradient de liquidité, monotone

| Quintile | SOL | Médiane | Moyenne | Sans top 3 | Gagnants |
|---|---|---|---|---|---|
| 1 | 13 – 340 | 0,9967 | 0,9607 | 0,9430 | 47,4 % |
| 2 | 341 – 619 | 1,0040 | 0,9658 | 0,9565 | 58,9 % |
| 3 | 620 – 1 343 | 1,0153 | 0,9992 | 0,9836 | 68,4 % |
| **4** | 1 351 – 2 870 | 1,0338 | **1,0037** | 0,9816 | 80,0 % |
| 5 | 2 890 – 6 837 | 1,0426 | 0,9876 | 0,9759 | 85,3 % |

**Le quintile 4 est la seule cellule à moyenne supérieure à 1 de toute l'enquête.**
Sur 95 observations, et sa moyenne tronquée reste à 0,9816.

## Étude 17 — la réintégration devient la meilleure sortie

| Règle | Déclenche | Médiane | Moyenne | Sans top 3 | Pertes > 50 % |
|---|---|---|---|---|---|
| Sans stop | — | 1,0203 | 0,9822 | 0,9770 | 5,1 % |
| Stop −10 % | 12,0 % | 1,0203 | 0,9887 | 0,9836 | 4,7 % |
| Stop −20 % | 8,4 % | 1,0203 | 0,9857 | 0,9806 | 4,7 % |
| **Réintégration** | 24,6 % | 1,0192 | **0,9922** | **0,9871** | 4,7 % |

**Inversion complète du verdict de l'étude 17.** Sur données contaminées, la
réintégration semblait coûter (2,271 contre 2,885) ; le ×314 d'un pool hors SOL
écrasait tout. Sur données propres elle est **la meilleure règle**, +1 point de
moyenne. La règle 5 reste vraie — le fill du stop en pourcentage est mauvais —
mais la réintégration déclenche assez tôt pour y échapper.

## Étude 18 — le surplomb élimine les catastrophes

| | Ruggés (22) | Sains (162) |
|---|---|---|
| **Surplomb** | **2,994** | **0,137** |
| Portefeuilles nouveaux | 3,63 % | 5,92 % |
| Argent neuf (SOL) | 35,68 | 15,39 |
| Volume à l'achat | 75,75 % | 66,63 % |

| Filtre | n | Médiane | Moyenne | Sans top 3 | Gagnants | **Pertes > 50 %** |
|---|---|---|---|---|---|---|
| Écarté | 170 | 1,0530 | 0,9651 | 0,9561 | 81,8 % | **10,0 %** |
| **Sans surplomb seul** | 178 | 0,9994 | 0,9912 | **0,9808** | 47,8 % | **0,6 %** |
| Liquide et sans surplomb | 119 | 1,0186 | 0,9930 | 0,9752 | 77,3 % | 5,0 % |

**Les pertes lourdes passent de 10 % à 0,6 %** — un facteur 17. Le filtre de
surplomb ne fait pas gagner, il empêche de tout perdre.

## Études 19 et 20 — intactes

La cohorte de graduation est **100 % SOL (1 821 sur 1 821)**, et la signature de
67,406 SOL est **exclusive aux pools SOL** — seconde confirmation qu'elle
identifie bien les graduations Pump.fun. Aucun chiffre à corriger.

## Étude 21 — confirmée, sans edge

| | +3 h | +12 h |
|---|---|---|
| Cassure (moyenne) | 0,9149 | 0,8126 |
| Baseline (moyenne) | 0,9432 | 0,8405 |

---

## Le résultat structurel de toute l'enquête

**La baseline elle-même saigne.** Détenir un pool SOL liquide pris au hasard
pendant 30 minutes rapporte **0,9501 en moyenne** — moins 5 %. Sur 228 372
observations, ce n'est pas du bruit.

Le meilleur signal trouvé ramène cette perte à 0,9834. Il capte **+3,3 points**,
de façon reproductible, mesurée contre une baseline appariée. **Mais il ne
retourne pas le signe.**

Aucune stratégie acheteuse testée ne franchit 1 en moyenne tronquée. Ce n'est pas
faute de signal : c'est que la population a une dérive négative que le signal
réduit sans l'annuler. Deux voies restent ouvertes, et une seule est à notre
portée aujourd'hui :

1. **Isoler une sous-population à dérive positive.** Le quintile 4 de liquidité
   (moyenne 1,0037) est le seul indice qu'elle existe. À confirmer hors
   échantillon avant d'y croire.
2. Être de l'autre côté du trade — hors de portée sur un AMM sans emprunt.


---

## Correction 23 — la déduplication, et une erreur d'anecdote

### Le constat de départ

La liste des 24 effondrements montrait `EJBZ3i99nNEoZmD3jyhJ4xfCngBrXzp6ir81hhJfpump`
**trois fois** — 03:17, 03:18, 03:20 — le même pool racheté trois fois pendant
qu'il mourait. J'en ai conclu à un défaut de conception.

Le redéclenchement est bien massif : **475 signaux pour seulement 187 pools**, et
87 pools seulement produisent un signal unique. Un pool en a produit onze.

### La mesure dit l'inverse

Règle testée : un seul signal par pool par tranche de 30 minutes — c'est-à-dire
la durée de détention, pendant laquelle on est déjà en position.

| | n | Médiane | Moyenne | Sans top 3 | Gagnants | Pertes > 50 % |
|---|---|---|---|---|---|---|
| Tel quel | 475 | 1,0211 | **0,9834** | 0,9784 | 68,0 % | 5,1 % |
| **Dédoublonné** | 377 | 1,0217 | **0,9765** | 0,9706 | 69,8 % | 5,6 % |

Retirer 98 signaux **abaisse** la moyenne. Les redéclenchements étaient meilleurs
que la moyenne, pas pires : leur taux de pertes lourdes était inférieur.

### Mais le chiffre dégradé est le bon

La déduplication n'est pas un filtre destiné à améliorer le résultat, c'est une
**contrainte de la réalité** : si on détient 30 minutes et que le signal se
represente, on est déjà en position. Le 0,9834 comptait des trades qu'on n'aurait
pas pu prendre.

**La performance réaliste de l'étude 15 est donc 0,9765, pas 0,9834.**

À noter aussi : 187 pools pour 70 heures de capture. La stratégie est très
concentrée — un incident sur quelques pools déplace tout le résultat.

---

## Erreur de méthode n° 16 — généraliser depuis un cas saillant

Trois lignes identiques dans une liste de 24 sautaient aux yeux, et j'en ai
déduit un défaut général avant de le mesurer. Mesuré, l'effet est inverse.

**Règle : une régularité vue dans une liste est une hypothèse, jamais un
constat.** Ce qui saute aux yeux dans un échantillon affiché est précisément ce
que l'œil sélectionne — la répétition se remarque, la dispersion non.


---

## Hypothèse 22 — l'explosion du bruit : tuée, et par son propre exemple

### L'observation de départ

FROGGY (*The Fomo Frog*) le 10 août : quatre heures plates entre 11h30 et 15h30
UTC, puis l'activité passe de 33 à 138 trades par quart d'heure et de 26 à 79
portefeuilles. Le prix fait **×8,8 en 45 minutes**.

### Le signal perd à toutes les spécifications

Bruit des 15 dernières minutes ≥ 4× son rythme des 2 heures précédentes, prix en
hausse d'au moins 2 %, après une consolidation de largeur maximale variable.
Horizon 30 minutes.

| Largeur exigée | n | Médiane | Moyenne | Sans top 3 | Gagnants | Pertes > 50 % |
|---|---|---|---|---|---|---|
| ≤ 1,6 | 498 | 0,9917 | **0,9176** | 0,9132 | 47,6 % | 11,8 % |
| ≤ 2,0 | 690 | 0,9736 | **0,9037** | 0,8984 | 44,5 % | 10,7 % |
| ≤ 3,0 | 1 002 | 0,9484 | **0,8963** | 0,8924 | 39,8 % | 9,1 % |
| aucune | 1 470 | 0,8981 | **0,9222** | 0,9008 | 35,6 % | 13,2 % |
| **Baseline** | 208 179 | 0,9933 | **0,9634** | 0,9626 | 35,4 % | **3,7 %** |

Pire que l'achat au hasard, partout, avec **trois à quatre fois plus de pertes
lourdes**.

### Pourquoi : le bruit n'est pas un précurseur, c'est l'événement

Sur FROGGY, en faisant varier l'instant d'entrée :

| Heure UTC | Facteur de bruit | Résultat à 30 min si on entre là |
|---|---|---|
| 15:38 | 0,6 | **×2,84** |
| 15:43 | 0,8 | **×4,02** |
| 15:58 | 2,8 | ×4,64 |
| 16:08 | **4,0** | ×2,72 |
| 16:18 | 3,2 | 0,94 |
| **16:28** | **12,0** | **0,42** |

**Les meilleures entrées sont celles où le bruit n'avait pas encore explosé.**
Quand le facteur atteint le seuil de déclenchement, le gain a déjà fondu ; quand
il atteint 12, on perd 58 %.

L'afflux de participants ne précède pas la hausse, **il est la hausse** — et il
marque la distribution, pas l'accumulation. Un signal qui attend de le voir
arrive par construction du mauvais côté du trade.

### Ce que ça confirme

C'est la même leçon que la règle 5, sous une autre forme : ici la latence n'est
pas technique mais logique. Le signal ne peut pas être observé avant d'être
consommé. FROGGY n'était pas un contre-exemple à trouver, c'était une
démonstration de l'impossibilité.
