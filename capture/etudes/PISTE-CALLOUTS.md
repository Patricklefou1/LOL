# Piste des callouts Pump.fun — reconnaissance du 23 août 2026

## Ce qu'est un callout

Fonction native de Pump.fun, lancée le 16 janvier 2026. Un compte annonce un
token à ses abonnés par notification. **Un appel maximum toutes les six
heures et par compte** : la ressource est rare, ce qui distingue ce signal
d'un message de groupe.

## Ce qui est accessible sans authentification

Hôte : `frontend-api-v3.pump.fun`

| Route | État | Contenu |
|---|---|---|
| `GET /callout/list/{portefeuille ou uuid}?limit&sortBy&sortOrder` | ouverte | tous les appels d'un caller ; `sortBy` ∈ {`TIMESTAMP`, `MULTIPLE`} ; pagination par `nextPageToken` |
| `GET /callout/{calloutId}` | ouverte | un appel |
| `GET /callout/{calloutId}/replies` | ouverte | réponses |
| `GET /users/{portefeuille ou pseudo}` | ouverte | `username`, `followers`, `following`, `bio` |
| `GET /following/{portefeuille}` | ouverte | relations, avec adresse et nombre d'abonnés |
| `GET /callout/leaderboard` | **401** | classement des callers — la seule énumération globale |
| `GET /callout/top/{n}` | ouverte mais **toujours vide** | — |

Champs d'un appel : `calloutId`, `userId` (**adresse du portefeuille**),
`coinMint`, `marketCap`, `calloutPrice`, `calloutPriceUsd`, `multiple`,
`maxPriceSol`, `maxPriceUsd`, `maxMultiplier`, `maxMultiplierAt`,
`createdAt` (ms), `thesis`, `likes`, `repostCount`, `viewCount`.

`userId` et `coinMint` permettent la jointure directe avec `pumpswap_trades`.

## Le blocage : l'énumération

Aucune route ouverte ne liste les appels globalement.

- `GET /callout/leaderboard` → 401. **Non contourné, et à ne pas contourner.**
- La page `pump.fun/callouts` redirige désormais vers `/explore`.
- `GET /coins/{mint}` (48 champs) ne porte **aucun** champ de callout.
- Pas de route par mint : `/callout/coin/{mint}`, `/callout/mint/{mint}`,
  `/callout/token/{mint}` → 404.

### Rendement mesuré du balayage aléatoire

| Échantillon | Portefeuilles | Callers |
|---|---|---|
| Les plus actifs parmi les 5 premiers acheteurs | 150 | **0** |
| Profils Pump.fun (4,8 % de 400 portefeuilles tirés au hasard) | 19 | **0** |
| Relations du caller connu `drainednetan` | 92 | **0** |
| **Total** | **261** | **0** |

Le graphe social ne concentre pas les callers : un compte à 741 455 abonnés
présent dans les relations n'a fait aucun appel. Le nombre d'abonnés reste le
seul discriminant observé — les 19 profils tirés au hasard ont de 0 à 72
abonnés, le caller connu en a 7 658.

Borne haute à 95 % de confiance sur 0/261 : moins de **1,2 %** des
portefeuilles actifs font des callouts. Réunir quelques milliers d'appels par
balayage demanderait des dizaines de milliers de requêtes.

## Ce que la piste permettrait de mesurer

1. **Le décalage entre l'appel et la vente du caller** — l'appel est horodaté
   à la milliseconde, les ventes sont dans `pumpswap_trades`.
2. **Le rapport position engagée / capitalisation appelée.** Sur l'exemple
   observé : environ 1,20 $ sur un token à 3 983 $.
3. **La valeur du quota de six heures** — un caller qui le dépense sur un
   token à 4 000 $ engage une ressource rare.

## Décision en attente

La piste est ouverte techniquement mais non énumérable. Elle exige un jeton de
session Pump.fun pour lire `/callout/leaderboard`, qui donnerait la liste des
callers ; leurs historiques complets sont ensuite lisibles par la route
ouverte. Sans ce jeton, la piste s'arrête ici.

## Note annexe

`GET /coins/{mint}` expose directement le champ `twitter`. Le dépliage des
`uri` IPFS de la table `creations`, estimé coûteux, est donc inutile.
