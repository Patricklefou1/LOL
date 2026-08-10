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
| 5 | **Entrée au remplissage de courbe, sortie à la graduation** | ✅ **retenu** | `pregraduation.sql` |
| 6 | Persistance du PnL des wallets (smart money) | ✅ retenu | — |
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

### Robustesse

| Test | Résultat |
|---|---|
| Retrait des 3 meilleurs (sur 1 171) | 1,0421 |
| Retrait des 10 meilleurs | 1,0298 |
| Retrait des 25 meilleurs | **1,0030** |
| Tranches de 3 h positives | **7 / 7** |

Survit au retrait de 2 % des meilleurs trades et à toutes les tranches horaires.

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

Les règles 1 et 3 sont désormais gravées dans `../README.md`.
