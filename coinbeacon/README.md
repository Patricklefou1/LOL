# Rentabilité des détections CoinBeacon

`analyse_setups.py` mesure la rentabilité des setups de CoinBeacon à 4 h et à 24 h, à partir des bougies 1 min de Binance au comptant.

## Lancer

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
