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
