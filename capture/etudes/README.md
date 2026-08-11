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
| 10 | Acheter toute graduation sur PumpSwap | ⏸ à refaire — décodeur désormais correct | `pumpswap-decode.sql` |

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
