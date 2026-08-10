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

---

## Étude 5 — Pré-graduation

**Mécanisme.** Sur une bonding curve, le prix est une fonction déterministe des
réserves. Le rendement entre un niveau de remplissage et la graduation est donc
connu à l'avance ; le seul aléa est d'y parvenir. C'est un pari de probabilité,
pas une prédiction de prix — d'où sa robustesse.

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

### Ce que l'étude ne dit pas

- **19 heures de données.** Le critère de passage exige un walk-forward sur
  ≥ 4 semaines distinctes. Ce résultat est un candidat, pas un edge validé.
- **Aucune sélection adverse modélisée.** Le stop à −20 % est un niveau évident ;
  si le signal est tradé par d'autres, c'est précisément là qu'on se fait
  chasser. Seul le micro-réel le révélera.
- **Capital de travail** : ~1 480 opportunités/jour, détention ≤ 30 min, soit une
  quinzaine de positions simultanées — 8 à 15 SOL immobilisés à 0,5 SOL l'unité.
- **Fourchette de gain honnête** : 1 à 22 SOL/jour selon la sévérité du
  retraitement des extrêmes ; estimation centrale 10 à 15 SOL/jour.

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
