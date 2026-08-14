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
