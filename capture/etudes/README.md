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
| 17 | **Stops au fill réel** | ❌ **aucune règle de sortie n'aide** — la perte est un rug, pas une baisse | `sortie-fill-reel.sql` |
| 16 | **Liquidité discriminante** | ⏳ gradient monotone, taux de gagnants **44 % → 86 %** | `liquidite-discriminante.sql` |
| 15 | Réveil après consolidation (post-graduation) | ⚠️ **médiane positive, moyenne non concluante** — échoue au retrait des extrêmes | `reveil-postgraduation.sql` |

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
