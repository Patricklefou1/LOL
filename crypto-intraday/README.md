# Backtest intrajournalier BTC : momentum de séance et chiffres ronds

Ce script teste deux effets intrajournaliers sur le BTC/USDT, combinés à l'effet des chiffres ronds :

- **Option A, fenêtre des ETF** : le rendement entre 9 h 30 et 10 h 00, heure de New York, prédit-il celui entre 15 h 00 et 16 h 00 ? Cette dernière fenêtre est celle du taux de référence CME CF qui valorise les ETF Bitcoin au comptant. Jours ouvrés seulement.
- **Option B, jour UTC** : le rendement entre 00 h 00 et 00 h 30 UTC prédit-il celui entre 23 h 30 et 00 h 00 UTC ?

Les heures sont toujours calculées dans le fuseau du marché. Le script gère donc seul les semaines de décalage horaire entre les États-Unis et l'Europe.

## Installation et utilisation

Il faut Python 3.10 ou plus récent, avec `pandas` et `numpy`.

```bash
pip install pandas numpy

# 1. Télécharger les bougies d'une minute de Binance (environ 1 Go de zips depuis 2018)
python3 backtest_btc.py telecharger --debut 2018-01 --fin 2026-09

# 2. Lancer le backtest avec les paramètres pré-enregistrés
python3 backtest_btc.py tester > resultats.md

# Variantes utiles
python3 backtest_btc.py tester --option A --sens momentum
python3 backtest_btc.py tester --frais 0.0002          # ordres limites
python3 backtest_btc.py tester --export trades.csv     # un trade par ligne
```

Les données sont mises en cache dans `donnees/`, qui est ignoré par git.

## Ce que le script mesure

Pour chaque jour, il prend une position dans le sens du signal (momentum) ou dans le sens inverse (retournement). La position est fermée à la fin de la fenêtre, sans stop.

**Chiffres ronds**, en multiples de 1 000 $ par défaut. À l'entrée, chaque trade est classé dans l'une de trois catégories :

- **obstacle** : un chiffre rond se trouve devant le prix, dans le sens du trade, à moins de 0,2 %. Les take-profits y sont concentrés.
- **franchi** : le prix a traversé un chiffre rond dans le sens du trade pendant les 60 minutes précédentes. Les stops et les liquidations placés derrière ont été déclenchés.
- **neutre** : tous les autres cas.

**Variantes testées** :

- **base** : tous les jours.
- **tendance H4** : seulement les trades dans le sens de la tendance, définie comme la clôture H4 au-dessus ou en dessous de sa moyenne mobile 50 périodes.
- **sans obstacle** : les trades classés « obstacle » sont écartés.
- **tendance H4 + sans obstacle** : les deux filtres combinés.
- **objectif avant le rond** : sortie anticipée juste avant le prochain chiffre rond, s'il est atteint.

**Contrôles** :

- **p hasard** : la part des directions tirées au hasard, sur les mêmes jours, qui font au moins aussi bien. En dessous de 0,05, le résultat est difficilement attribuable au hasard.
- **sans top 3 / top 10** : la moyenne recalculée après avoir retiré les meilleurs jours. Si elle s'effondre, le résultat tient à quelques séances.
- **par année** : l'effet doit se retrouver sur plusieurs années, pas seulement sur une.
- **avant / après ETF**, pour l'option A uniquement : si l'effet vient des ETF, il doit apparaître après le 11 janvier 2024, pas avant. Avant cette date, la période sert de placebo.
- **terciles du signal** : l'effet est-il plus fort quand le mouvement de départ est grand ?
- **sensibilité aux frais** : 0, 2, 5 et 10 points de base par côté.
- **référence** : le résultat obtenu en étant toujours acheteur sur la même fenêtre.

## Pré-enregistrement

Paramètres fixés **avant** toute mesure sur données réelles : multiples de 1 000 $, obstacle à 0,2 %, franchissement jugé sur 60 minutes, objectif placé 0,05 % avant le chiffre rond, moyenne H4 sur 50 périodes, frais de 5 pb par côté.

Hypothèses principales :

1. **H1** : option A, momentum, variante de base, après les ETF. Le résultat net est positif et le p hasard inférieur à 0,05. Avant les ETF, le résultat est nul.
2. **H2** : la variante « sans obstacle » bat la variante de base.
3. **H3** : les trades « franchi » battent les trades « neutre ».

Tout le reste (option B, sens retournement, tendance H4, terciles) est **exploratoire**. Avec une trentaine de lignes de résultats, quelques-unes passeront sous 0,05 par pur hasard. Un résultat exploratoire ne vaut que s'il se confirme sur une période qui n'a pas servi à le trouver, par exemple en refaisant le test avec `--depuis` sur les mois à venir.

## Limites connues

- **Jours fériés américains** : ils restent dans l'option A. Cela fait une dizaine de jours par an sans flux d'ETF, ce qui dilue légèrement l'effet.
- **Exécution** : le prix d'entrée est la clôture de la minute précédente, sans glissement. C'est réaliste sur le BTC pour de petites tailles, faux pour de grosses positions.
- **Objectif** : on suppose l'ordre limite exécuté dès que le prix le touche. C'est légèrement optimiste.
- **Liquidations** : le script ne les utilise pas. Binance ne publie pas l'historique des liquidations en données libres, seulement en temps réel.
- **Spot uniquement** : les contrats perpétuels ajoutent le funding, versé à 00 h, 08 h et 16 h UTC. L'option B est donc proche d'un de ces versements.
- **Effectif** : l'option A après les ETF compte environ 650 jours à fin 2026. Une fois filtrées par catégorie de chiffre rond, certaines cases tombent à quelques dizaines de jours, trop peu pour conclure.
