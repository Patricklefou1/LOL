# Figures chartistes haussières des tokens gradués

Outil autonome (Python 3.9+, **aucune dépendance**) qui répond à la question :
« quelles figures chartistes haussières sont les plus représentées parmi les
tokens gradués sur Pump.fun — hier, il y a 7 jours, il y a 30 jours ? »

Le contexte, les définitions des 12 figures détectées, la méthode et les
limites sont documentés dans [../../pumpfun-figures-chartistes.md](../../pumpfun-figures-chartistes.md).

## Lancer

```bash
# Sur le VPS de capture (recommandé : zéro biais du survivant, zéro clé).
# Bougies = phase bonding curve, le chart qui a mené à la graduation.
python3 figures_chartistes.py --source clickhouse \
    --markdown resultats.md --json resultats.json

# Sans la base de capture, avec une clé Moralis (graduatedAt exact,
# bougies post-graduation via la paire PumpSwap) :
MORALIS_API_KEY=... python3 figures_chartistes.py --source moralis

# Dernier recours sans clé (approximation par jour de création) :
python3 figures_chartistes.py --source pumpfun
```

Options utiles :

| Option | Effet |
|---|---|
| `--mode jours` (défaut) | cohortes d'un jour : hier (J-1), J-7, J-30 |
| `--mode cumule` | fenêtres glissantes : derniers 1 / 7 / 30 jours |
| `--fenetres 1,7,30` | reculs analysés, en jours |
| `--date-ref 2026-08-14` | rejouer une date passée (défaut : aujourd'hui UTC) |
| `--echantillon 150` | tokens max par fenêtre (échantillon déterministe SHA-1) |
| `--bougies geckoterminal` | chandelles post-graduation sans clé (30 req/min) |
| `--minutes-post 720` | profondeur du chart post-graduation (sources API) |
| `--rentabilite` | étude d'événement : rendement **net** par figure (achat à la confirmation, sortie au stop d'invalidation ou à l'horizon), classement par médiane nette et verdict « figure la plus rentable » par fenêtre |
| `--couts 0.03` | coûts d'un aller-retour (frais + slippage) pour le mode rentabilité |
| `--horizons 15,60,240` | horizons de sortie en minutes ; `--horizon-cle` fixe celui du classement (défaut : le médian) |
| `--verbeux` | figures détectées token par token, sur stderr |

Variables d'environnement : `CLICKHOUSE_URL`, `CLICKHOUSE_USER`,
`CLICKHOUSE_PASSWORD`, `CLICKHOUSE_DATABASE` (mêmes noms et défauts que
[capture/](../../capture/)), `MORALIS_API_KEY`.

## Vérifier sans réseau

```bash
python3 figures_chartistes.py --autotest
# Autotest : 15/15 cas OK
```

L'autotest fabrique une série synthétique par figure (plus un témoin baissier)
et vérifie que chaque détecteur reconnaît la sienne, puis valide le simulateur
de rentabilité sur un drapeau gagnant et un double creux stoppé à
l'invalidation.

Les niveaux d'entrée / invalidation / objectif de chaque figure sont
documentés dans [../../pumpfun-figures-chartistes.md](../../pumpfun-figures-chartistes.md)
(§ 4 bis).

## Sorties

- console : classement par fenêtre (tokens et % des séries analysées) ;
- `--markdown fichier.md` : rapport prêt à coller dans la doc ;
- `--json fichier.json` : comptes bruts pour retraitement.

Une même série peut présenter plusieurs figures : les pourcentages sont
rapportés aux tokens analysés et ne somment pas à 100 %. Les figures
emboîtées sont dédupliquées (triple creux absorbe double creux, tasse avec
anse absorbe fond arrondi).
