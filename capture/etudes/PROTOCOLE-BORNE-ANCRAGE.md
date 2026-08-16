# Protocole — cassure d'une borne d'ancrage

Pré-enregistré le **13 août 2026**. Paramètres figés avant toute donnée de
validation. Ne rien modifier ici en fonction du résultat.

## L'idée, et pourquoi elle n'avait jamais été testée

Toutes les études 15 à 25 mesuraient une **fenêtre glissante** : la borne haute
était recalculée à chaque bougie sur les N précédentes. Conséquence — dès qu'une
bougie casse, elle devient elle-même la borne de la suivante. La borne monte avec
le prix et n'est jamais franchie proprement.

Ici la borne est **figée** : mesurée une fois sur une heure de range, puis gardée
constante pendant qu'on attend la cassure. C'est la différence entre « le prix
dépasse son plus haut récent » et « le prix casse un niveau de référence ».

Mesuré : le taux de gagnants passe de 51 % à 81,7 % en changeant uniquement cela.

## Paramètres figés

| Paramètre | Valeur |
|---|---|
| Univers | pools PumpSwap dont le quote est WSOL (`est_sol = 1`) |
| Bougies | **5 minutes, alignées sur l'horloge, datées sur `event_timestamp`** |
| Range | **1 heure fixe** — 12 bougies contiguës, blocs non chevauchants |
| Validité du range | 12 bougies présentes, **≥ 5 trades chacune** |
| Marché réel | **taille médiane des trades ≥ 0,01 SOL** dans le range |
| Largeur | `max(plus_haut) / min(plus_bas) ≤ 1,10` |
| **Borne** | `max(plus_haut)` du bloc, **figée** |
| Signal | première bougie de l'heure suivante clôturant **> borne × 1,05** |
| Pas de pump en cours | taille du signal / taille du range **≤ 3** |
| Entrée | **ouverture de la bougie suivante** |
| Sortie | clôture 30 minutes après l'entrée |
| Réserve | ≥ 5 SOL à l'entrée |
| Coûts | 0,5 SOL d'impact de chaque côté, 0,6 % de frais |

## Coupure

**2026-08-13 20:00:00 UTC.** Tout signal dont l'entrée est postérieure est hors
échantillon.

## Référence dans l'échantillon de réglage

| Mesure | Valeur |
|---|---|
| **Moyenne** | **1,0208** |
| **Tokens** | **52** |
| Trades | 82 |
| Médiane | 1,0190 |
| Moyenne sans les 3 meilleurs | **1,0106** |
| Trades gagnants | 67,1 % |
| Effondrements (< 0,2) | **0 %** |
| Baseline du marché | 0,9515 |

Robustesse du seuil : à 0,05 SOL au lieu de 0,01, la moyenne vaut 1,0231 et la
moyenne tronquée 1,0123. Le résultat ne dépend pas du réglage fin.

## Critères de décision, décidés à l'avance

Échantillon minimal : **150 tokens distincts** — en tokens, jamais en signaux.

**VALIDÉ** si les trois conditions sont réunies :
- moyenne ≥ **1,010**
- moyenne privée de ses 3 meilleurs trades ≥ **1,000**
- taux de gagnants ≥ **60 %**

**TUÉ** si l'une des trois est vraie :
- moyenne < **0,995**
- moyenne sans top 3 < **0,980**
- effondrements > **2 %**

**NON CONCLUANT** entre les deux : prolonger, sans rien changer d'autre.

## Ce que ce protocole doit à l'utilisateur

Chaque correction majeure vient de lui, en ouvrant un token et en regardant les
bougies — jamais d'une mesure agrégée :

- `EJBZ3i99` — 49 trades/minute à 0,0004 SOL : les essaims de micro-transactions
- `UXkXEB4A` — montée de 201 K à 453 K sans respiration : les dérives
- `QeRWrMQU` — taille passant de 0,26 à 3,5 SOL : les pumps organisés
- `EnA53Nm` — range contenant sa propre cassure : la borne glissante
- `utLyQQCP` — signal 17 % au-dessus de la borne : les fenêtres à trous

---

## Relevé hors échantillon — 14 août 2026, 07h00 UTC

Première lecture après la coupure. **Non concluante par construction** : le
protocole exige 150 tokens distincts, on en a trois.

| Token | Signal (UTC) | Largeur | Dépass. | SOL | Résultat |
|---|---|---|---|---|---|
| `13pxU1kBCZojJgiEKc7RqagVqCx9q8puAUsVihocpump` | 13/08 20:10 | 1,064 | 1,055 | 2 144 | **1,0370** |
| `A13oRB9FFaiUjfi6LdCg6p9ka1u8SfGkUFs4SKvPpump` | 13/08 20:10 | 1,075 | 1,079 | 3 030 | **0,9208** |
| `4jEbdEWatK6ubnK915keqyu9T9EVmN7P87Vg7LpKpump` | 13/08 20:55 | 1,079 | 1,082 | 117 | **0,8366** |
| `6NwarBvDkXhByqVp2Qkq5i9XbtA2B3Bwe8SWGu9vpump` | 13/08 21:30 | 1,056 | 1,068 | 2 705 | *incomplet* |
| `A13oRB9FFaiUjfi6LdCg6p9ka1u8SfGkUFs4SKvPpump` | 13/08 21:35 | 1,095 | 1,072 | 3 057 | *incomplet* |

Moyenne des trois complets : **0,9315**. Un gagnant sur trois.

**Aucune conclusion n'en est tirée.** Avec trois observations, tout résultat entre
0,7 et 1,3 est également plausible. Ce relevé est consigné pour qu'on ne puisse
pas, plus tard, choisir la fenêtre qui arrange.

### Deux observations qualitatives

Les deux premiers signaux tombent **à la même minute**. La concentration
temporelle vue dans l'échantillon de réglage se reproduit : l'effectif
indépendant sera toujours inférieur au nombre de tokens.

Le plus mauvais des trois, `4jEbdEWa`, a **117 SOL de réserve** et des trades de
0,034 SOL — le plus petit pool que la règle ait accepté. Le seuil `qr_e >= 5`
laisse passer des marchés très minces. À surveiller sans y toucher : modifier un
paramètre après avoir vu un résultat est exactement ce que ce protocole interdit.

### Rythme observé

Cinq signaux en deux heures, soit environ 60 par jour, sur peu de tokens
distincts. Les **150 tokens** requis demanderont environ une semaine.

## Mesures annexes prises le 13 août

**Plafond théorique.** En sortant chaque trade à son point haut des 30 minutes —
impossible en pratique — la moyenne serait de **1,0487** contre 1,0208 pour la
règle. Le plafond est donc à +4,9 %, et la sortie à durée fixe en capture déjà
43 %. Il n'y a pas de gisement caché dans le timing de sortie.

**Usage de la réintégration.** Le prix repasse sous la borne dans **9,8 %** des
cas seulement. Ces huit trades rendent **0,9007** contre 1,0338 pour les 74
autres : repasser sous la borne annonce l'échec. Ils atteignent pourtant 1,0585 à
leur point haut — ils montent d'abord, puis retombent.

---

## Relevé hors échantillon v1 — mise à jour du 15 août 2026, 22h45 UTC

Deuxième lecture, **paramètres strictement inchangés**. Signaux dont l'entrée est
postérieure à la coupure du 13/08 20:00, du 13/08 20:15 au 15/08 15:31.

| Mesure | Valeur | Seuil de validation | Seuil de mort |
|---|---|---|---|
| **Tokens** | **12** | *150 requis* | — |
| Trades | 25 | — | — |
| **Moyenne** | **1,0210** | ≥ 1,010 ✅ | < 0,995 |
| Médiane | 1,0357 | — | — |
| **Moyenne sans top 3** | **1,0134** | ≥ 1,000 ✅ | < 0,980 |
| **Trades gagnants** | **92,0 %** | ≥ 60 % ✅ | — |
| **Effondrements** | **0 %** | — | > 2 % ✅ |

**Verdict : NON CONCLUANT — prolonger.** Les trois conditions de validation sont
réunies et aucune condition de mort n'est atteinte, mais l'échantillon est de 12
tokens sur les 150 requis. Le protocole impose de prolonger sans rien changer.

La première lecture donnait 0,9315 sur trois tokens ; celle-ci 1,0210 sur douze.
L'écart entre les deux illustre exactement pourquoi le seuil de 150 existe.

**Rythme réel : environ 6,5 tokens par jour.** L'estimation initiale d'« environ
une semaine » était trop optimiste — il faut compter **une vingtaine de jours**
à ce rythme.

---

# Protocole v2 — couloir élargi à 1,15

Pré-enregistré le **15 août 2026 à 22h45 UTC**. Le protocole v1 ci-dessus
continue de tourner **inchangé** ; v2 ne le remplace pas, il l'accompagne.

## Pourquoi un second protocole plutôt qu'une modification

Une analyse de sensibilité menée le 15/08 montre que le couloir de 1,10 était
trop serré : il éliminait 86 % des tokens porteurs d'un signal, et l'élargir à
1,15 améliorait simultanément la médiane, la moyenne, la moyenne sans top 3, le
taux de gagnants et le taux de pertes lourdes.

Mais ce seuil a été choisi **après avoir vu les données**. Modifier v1 en
conséquence serait précisément ce que sa clause d'ouverture interdit. On ouvre
donc un protocole distinct, avec sa propre coupure, et on laisse v1 vivre sa vie.
Si les deux valident, la conclusion est robuste au réglage ; si seul v2 valide,
le doute d'ajustement reste entier.

## Ce qui change, et rien d'autre

**Un seul paramètre** : `max(plus_haut) / min(plus_bas) ≤ 1,15` au lieu de 1,10.
Tous les autres paramètres figés du v1 sont repris à l'identique — univers,
bougies de 5 min sur `event_timestamp`, range d'une heure fixe, ≥ 5 trades par
bougie, taille médiane ≥ 0,01 SOL, borne figée, signal à +5 %, taille du signal
≤ 3× celle du range, entrée à l'ouverture suivante, sortie à 30 min, réserve
≥ 5 SOL, coûts identiques.

## Coupure

**2026-08-16 00:00:00 UTC.** Postérieure à l'intégralité des données ayant servi
au choix du seuil, qui s'arrêtent au 15/08 22:17 UTC.

## Référence dans l'échantillon de réglage

| Mesure | v2 (couloir 1,15) | v1 (couloir 1,10) |
|---|---|---|
| Tokens | 44 | 103 |
| Trades | 89 | 273 |
| Moyenne | 1,0134 | 1,0098 |
| Médiane | 1,0405 | 1,0343 |
| Moyenne sans top 3 | 1,0062 | 1,0048 |
| Trades gagnants | 84,3 % | 92,3 % |
| **Effondrements** | **2,25 %** | 2,56 % |

## Réserve inscrite avant toute donnée

**Le taux d'effondrement de référence, 2,25 %, dépasse déjà le seuil de mort de
2 %.** v2 démarre donc en situation défavorable sur ce critère précis, et c'est
lui qui décidera vraisemblablement de son sort. C'est consigné ici, avant la
coupure, pour qu'on ne puisse pas plus tard présenter un échec sur ce critère
comme une surprise — ni l'écarter comme un détail.

Deux variantes ont été écartées et sont notées pour mémoire : sans filtre de
taille, 147 tokens mais 2,25 % d'effondrements également ; avec un filtre à
0,001 SOL, 57 tokens et 1,74 % d'effondrements, seule variante sous le seuil de
mort — mais elle exigeait de modifier deux paramètres au lieu d'un.

## Critères de décision

Identiques au v1, sans aucune modification : validé si moyenne ≥ 1,010 **et**
moyenne sans top 3 ≥ 1,000 **et** gagnants ≥ 60 % ; tué si moyenne < 0,995
**ou** moyenne sans top 3 < 0,980 **ou** effondrements > 2 % ; non concluant
entre les deux, prolonger. Échantillon minimal : **150 tokens distincts**.

---

## Relevé du 16 août 2026, 20h08 UTC

Premier relevé automatisé (minuteur quotidien, 06h00 UTC). Paramètres inchangés
pour les deux protocoles.

| Mesure | v1 (couloir 1,10) | v2 (couloir 1,15) |
|---|---|---|
| Coupure | 13/08 20:00 | 16/08 00:00 |
| **Tokens** | **17** / 150 | **8** / 150 |
| Trades | 31 | 12 |
| Moyenne | 1,0327 | 1,0661 |
| Médiane | 1,0341 | 1,0458 |
| Moyenne sans top 3 | 1,0178 | 1,0352 |
| Gagnants | 93,5 % | 100 % |
| Effondrements | 0 % | 0 % |
| **Verdict** | **non concluant, tendance validation** | **non concluant, tendance validation** |

Progression de v1 : 3 tokens et 0,9315 au 14/08 ; 12 et 1,0210 au 15/08 ; 17 et
1,0327 aujourd'hui. **Aucune tendance ne doit être lue dans cette suite** — c'est
un échantillon qui grossit, pas une série temporelle.

Rythme : v1 accumule 5,7 tokens/jour, v2 **9,6**. Le couloir élargi collecte
environ 1,7 fois plus vite, ce qui était son objet. Aux rythmes actuels les 150
tokens tombent vers le **8 septembre** pour v1 et le **31 août** pour v2.

Réserve sur v2 : 8 tokens, 100 % de gagnants et zéro effondrement sont un
échantillon minuscule et exceptionnellement favorable. Sa référence de réglage
annonçait 2,25 % d'effondrements, au-dessus de son seuil de mort ; ce critère
n'a tout simplement pas encore eu l'occasion de se manifester.

### Correction d'un verdict erroné

Le passage automatique de 06h04 avait déclaré **v2 « TUÉ » sur 1 token**. Cause :
la statistique « sans top 3 » vaut mécaniquement 0 quand on retire les trois
meilleurs trades d'un échantillon qui en compte un, et ce 0 franchissait le
seuil de mort de 0,980.

Corrigé dans l'outil : aucun verdict, ni validation ni mort, n'est prononcé
sous les 150 tokens. Le protocole fixe cet effectif pour **la décision**, pas
seulement pour la validation — on ne peut pas plus tuer sur un token que valider
sur un token. La statistique sans-top-3 n'est plus calculée sous 4 trades.

---

# Protocole v3 — détection « tout vert », entrée à 45 min, sortie à 15 min

Pré-enregistré le **16 août 2026 à 20h30 UTC**. Hypothèse distincte des v1/v2 :
elle ne porte pas sur une cassure de range mais sur les tokens dont le prix
monte sans interruption, que l'utilisateur a identifiés comme artificiels.

## L'idée

Un token dont les neuf premières bougies de 5 minutes sont **toutes vertes** est
tenu par quelqu'un. Mesuré : ces tokens vivent 2 h 48 en médiane contre 15 min
pour les autres, montent d'environ **+0,37 % par minute**, et 73 % finissent par
s'effondrer — mais l'effondrement se produit à 94 % dans une seule bougie, avec
un plus bas à 0,000012 × le sommet. Il n'y a pas de sortie possible pendant le
rug ; on parie sur la montée en sortant bien avant.

## Paramètres figés

| Paramètre | Valeur |
|---|---|
| Univers | pools PumpSwap, réserve quote médiane entre 5 et 20 000 SOL |
| Bougies | 5 minutes, datées sur `event_timestamp` |
| **Détection** | les **9 premières bougies** (45 min) toutes vertes (`clôture > ouverture`), au moins 8 présentes |
| Entrée | **premier trade au-delà de t0 + 45 min** |
| Sortie | **premier trade au-delà de l'entrée + 15 min** |
| Réserve | ≥ 5 SOL à l'entrée |
| Coûts | 0,5 SOL d'impact de chaque côté, 0,6 % de frais |

## Coupure

**2026-08-17 00:00:00 UTC**, postérieure à toutes les données de réglage, qui
s'arrêtent au 16/08 20:01 UTC.

## Référence dans l'échantillon de réglage

| Mesure | Valeur |
|---|---|
| Tokens | 550 |
| Médiane | 1,0410 |
| **Moyenne** | **1,0062** |
| Moyenne sans top 3 | 1,0046 |
| Gagnants | 84,4 % |
| Pertes > 50 % | 4,2 % |
| Écart-type | 0,2147 |
| Erreur standard | 0,0092 |
| **t de Student** | **0,68** |

## L'avertissement principal, écrit avant la coupure

**Cet effet n'est pas significatif dans l'échantillon de réglage.** Un t de 0,68
signifie que le gain mesuré (+0,62 %) est plus petit que sa propre erreur
standard (0,92 %) : sur 550 tokens, il est indiscernable de zéro. La médiane de
1,0410 est trompeuse — c'est la moyenne qui décide, et elle ne conclut rien.

Ce protocole n'est donc **pas** l'enregistrement d'un résultat prometteur. C'est
l'enregistrement d'une hypothèse dont on sait d'avance qu'elle demande beaucoup
de données pour être tranchée, et qu'on consigne maintenant pour ne pas pouvoir,
dans deux mois, présenter un résultat favorable comme s'il avait été prédit.

## Échantillon minimal, calculé et non choisi

**4 596 tokens.** C'est l'effectif nécessaire pour que l'effet observé se
distingue de zéro à 95 %, soit `(1,96 × 0,2147 / 0,0062)²`. Au rythme observé de
**~92 tokens/jour**, cela demande **environ 50 jours** de capture.

Contrairement aux 150 tokens de v1 et v2 — un nombre rond décidé à l'avance —
celui-ci est dérivé de la dispersion mesurée. Il n'est pas négociable à la
baisse : une validation sur moins ne voudrait rien dire.

## Critères de décision

**VALIDÉ** si les trois sont réunies, sur au moins 4 596 tokens :
- moyenne ≥ **1,003**
- moyenne sans les 3 meilleurs ≥ **1,000**
- **t ≥ 2,0**

**TUÉ** si l'une est vraie, sur au moins 500 tokens :
- moyenne < **0,995**
- **t ≤ −2,0**
- pertes > 50 % au-delà de **10 %**

**NON CONCLUANT** dans tous les autres cas : prolonger sans rien changer.

Le critère de t figure explicitement parce que l'effet visé est quatre fois plus
petit que celui de v1/v2 : une moyenne au-dessus du seuil sans significativité
ne serait qu'un tirage favorable.
