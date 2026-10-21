# Rentabilité des détections CoinBeacon

CoinBeacon ne fournit **aucun historique** : `GET https://api.coinbeacon.io/public/setups` renvoie le tableau du moment, avec 150 lignes au plus, et un setup qui échoue disparaît. On procède donc en deux temps :

1. `collecteur.py` interroge l'API à chaque clôture de bougie et enregistre chaque setup **la première fois qu'il apparaît**.
2. `analyse_setups.py --observations` mesure ensuite la rentabilité de ces setups sur les bougies 1 min de Binance au comptant.

## Collecter

```bash
read -rs COINBEACON_TOKEN && export COINBEACON_TOKEN     # la clé reste en mémoire
python coinbeacon/collecteur.py --timeframes 1h           # un appel d'essai
setsid nohup python coinbeacon/collecteur.py --boucle >> ~/coinbeacon-donnees/collecte.log 2>&1 < /dev/null &
```

- La clé passe dans l'en-tête `X-API-Key`. Par défaut, le collecteur interroge Binance au comptant en 1 h et en 4 h, 90 s après chaque clôture, en ne gardant que les setups déclenchés (`pattern_breakout`, `trendline_break`, `breakout_retest`), triés par fraîcheur.
- Cela coûte 150 crédits par jour. La collecte s'arrête d'elle-même sous 100 crédits restants.
- Les données sont rangées dans `~/coinbeacon-donnees`, hors du dépôt :
  - `observations.jsonl` : une ligne par setup, à sa première apparition, avec la clôture de sa bougie de déclenchement, `computedAt − barsSinceTrigger × tf` ;
  - `vues.jsonl` : chaque passage d'un setup sur le tableau ;
  - `appels.jsonl` : statut HTTP, crédits restants et troncature de chaque appel ;
  - `brut/` : les réponses complètes.
- Un setup vu pour la première fois plusieurs bougies après son déclenchement avait déjà survécu. L'analyse l'écarte par défaut (`--bars-max 1`). C'est le cas de tout le tableau présent au premier appel.

## Analyser les setups collectés

```bash
python coinbeacon/analyse_setups.py --observations ~/coinbeacon-donnees/observations.jsonl
python coinbeacon/analyse_setups.py --observations ~/coinbeacon-donnees/observations.jsonl --heure-detection declenchement --out-dir coinbeacon/resultats-declenchement
```

- `premiere_vue`, le mode par défaut, est réaliste : l'entrée se fait à la première bougie après le moment où le collecteur a vu le setup.
- `declenchement` est théorique : l'entrée se fait à la clôture de la bougie de déclenchement, environ 90 s avant qu'on puisse la voir.

La clé n'est pas nécessaire pour l'analyse. Le rapport signale aussi les trous de collecte et les réponses tronquées.

## Mode API directe

Ce mode est conservé pour une future API d'historique : `analyse_setups.py` peut aussi lire un endpoint paginé.

### Lancer

```bash
pip install -r coinbeacon/requirements.txt
export COINBEACON_TOKEN=...              # dans l'environnement uniquement, jamais dans un fichier
export COINBEACON_API_URL=https://...    # endpoint des setups
python coinbeacon/analyse_setups.py --check-only   # les trois contrôles, rien d'autre
python coinbeacon/analyse_setups.py
```

Le script s'arrête avec un code et un message précis si l'un des trois contrôles échoue :

| Code | Contrôle en échec |
|---:|---|
| 2 | jeton absent |
| 3 | API CoinBeacon : URL manquante, injoignable, ou code HTTP différent de 200 |
| 4 | Binance injoignable ou code HTTP différent de 200 (451 = restriction géographique) |
| 5 | Binance a banni l'adresse IP (418) |
| 6 | champ de paire ou d'heure introuvable dans les données |

## Sorties

- `resultats/detections.csv` : une ligne par détection, exclues comprises, avec le motif d'exclusion dans `statut`.
- `resultats/rapport.md` : tableaux, comparaison au hasard, sensibilité aux frais, biais et conclusion.
- `resultats/resume.json` : les mêmes statistiques, lisibles par une machine.
- `resultats/instantanes/` : les identifiants vus à chaque exécution. En comparant deux exécutions, le script repère les setups retirés de l'API.

## Cache

Le cache se trouve dans `coinbeacon/.cache/` et n'est pas versionné.
- Bougies Binance : un bloc de 1000 minutes déjà clos ne change plus, il est gardé définitivement.
- Pages de l'API : gardées 6 h. `--refresh-api` force un nouveau téléchargement.
- `--offline` rejoue toute l'analyse depuis le cache, sans réseau ni jeton.

Le jeton n'est écrit nulle part. Les clés du cache sont calculées sans lui, et toute sortie passe par un masquage.

## Adapter à l'API

Le script reconnaît seul les formats courants : liste brute, `data`, `results` ou `items`, puis pagination par `next`, en-tête `Link`, curseur ou numéros de page. Si la reconnaissance échoue, on peut tout préciser :

```bash
--page-param page --limit-param limit --limit 100        # pagination par page
--offset-param offset --limit-param limit --limit 100    # pagination par décalage
--field-map '{"pair":"market.symbol","time":"detected_at","side":"direction","type":"setup_type"}'
--auth-header X-API-Key --auth-scheme ""                 # jeton seul dans un en-tête dédié
--auth-query-param token                                 # jeton en paramètre d'URL, masqué partout
--api-param timeframe=all                                # paramètre fixe
```

La correspondance retenue et la liste des champs fournis figurent dans le rapport.

## Méthode

- Entrée : ouverture de la première bougie 1 min qui commence strictement après la détection. S'il y a un trou à cet endroit, la détection est exclue et comptée.
- Sortie : clôture de la bougie qui commence à l'entrée + H − 1 min. La position dure donc exactement H.
- Frais : 0,30 % aller-retour, soustraits du rendement brut (`--cost`).
- Vendeurs : traités comme des ventes à découvert, avec le rendement et les excursions inversés.
- Doublons : pour chaque paire, on garde la première détection et on écarte les suivantes tant que la position est ouverte.
- Hasard : 20 entrées par détection, même paire, ±7 jours, même sens, mêmes frais. Le tirage dépend de la graine et de l'identifiant, il est donc rejouable.
- Intervalles de confiance : 10 000 rééchantillonnages. Pour les groupes globaux, on donne aussi un intervalle qui rééchantillonne des journées entières.

## Tests

```bash
python -m pytest coinbeacon/tests -q
```

Les tests utilisent des données artificielles servies en local. Ce ne sont pas des résultats.
