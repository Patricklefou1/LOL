# Outillage de rétro-conception d'événements

## `identifier-offsets.py`

Identifie les offsets des champs d'un événement Anchor **contre une vérité
terrain externe** : les variations de solde réelles de la transaction, lues
depuis `meta` via RPC.

C'est un test qui **peut échouer**, contrairement à une comparaison entre deux
champs du même événement. Cette distinction a coûté une journée : la première
validation du décodeur PumpSwap comparait le prix issu des réserves au prix issu
des montants — deux quantités lues aux mêmes offsets. Elle passait sur les six
formes d'événements, y compris celles dont les ordres de grandeur étaient
absurdes.

```bash
# selection.tsv : type <TAB> taille <TAB> signature <TAB> payload_base64
RPC_URL=... python3 identifier-offsets.py
```

Sortie : pour chaque forme d'événement, les offsets dont la valeur reproduit un
mouvement réel de la chaîne, avec le taux de confirmation.

## État de la rétro-conception PumpSwap

Le flux contient au moins **six formes** : `BuyEvent` 457 et 472 octets,
`SellEvent` 409, et trois non identifiées de 64, 72 et 200 octets. **Leurs
dispositions diffèrent** — c'est établi, un jeu d'offsets unique est donc exclu.

### Montants — état après réparation

Identification stricte : on ne compare qu'aux mouvements des comptes **de
l'utilisateur** (pubkey lue à `@144`), et uniquement sur les transactions où
PumpSwap est invoqué en premier niveau. Les deux restrictions comptent : sans
elles, une dizaine de comptes bougent par transaction et les correspondances
fortuites sont massives.

| Forme | Offsets | Confirmation | Verdict |
|---|---|---|---|
| `BuyEvent` 472 | `@8` quote, `@16` et `@56` base | **76 %**, alternatives ≤ 21 % | exploitable |
| `SellEvent` 409 | `@104` base | **80 %** | partiel — quote non localisé (`@8`/`@24` à 59 %) |
| `BuyEvent` 457 | — | `@8` et `@104` à 48 % **pour quote comme pour base** | **non résolu** |

Le cas 457 mérite d'être lu : quand un offset matche quote *et* base à parts
égales, c'est la signature d'une correspondance fortuite, pas d'un champ. Aucun
signal n'en sort.

**Aucun décodeur n'est livré.** `BuyEvent` 472 représente environ un tiers des
événements ; décoder un tiers du flux biaiserait toute étude qui s'appuierait
dessus. Il faut les trois formes, ou rien.

### Corrections apportées en chemin

1. **Réintégrer les frais au compte 0.** Sans ça, aucun mouvement de SOL natif
   ne correspond exactement, le payeur supportant les frais de transaction.
2. **Restreindre aux comptes de l'utilisateur.** Comparer à tous les mouvements
   de la transaction produit des correspondances fortuites en pagaille — c'est
   ce qui faisait ressortir `@8` et `@24` à 75 % alors qu'ils portent la même
   valeur.
3. **Écarter les transactions routées.** Quand un agrégateur intercale ses
   propres comptes, l'utilisateur de l'événement n'est pas celui dont le solde
   bouge. Gain : +12 points sur `BuyEvent` 472.

### Pubkeys (identifiées par leur taux de répétition)

Une pubkey de pool sert de nombreux trades ; celle de l'utilisateur est presque
toujours distincte. Le taux de valeurs distinctes les sépare sans ambiguïté, et
il est cohérent sur les trois formes :

| Offset | Distinctes | Rôle |
|---|---|---|
| `@112` | 66–75 % | **le pool** |
| `@144`, `@176`, `@208` | 100 % | utilisateur et ses comptes de token |
| `@240` | 15–25 % | **compte global** (destinataire des frais) |
| `@272` | 48–73 % | non déterminé |

### Reste à faire

- **`BuyEvent` 457** : aucun offset de montant ne dépasse le seuil. Sa
  disposition diffère réellement et demande son propre passage.
- **Les réserves** : aucun offset ne reproduit un solde de coffre post-trade.
  L'hypothèse `@40`/`@48` du premier décodeur est **infirmée**. Ce n'est pas
  bloquant : le prix exécuté se calcule depuis les montants, mieux vérifiés.
- **Le quote de `SellEvent`** : non localisé. Probablement parce que le quote de
  ces pools est du **SOL natif**, qui bouge dans `preBalances`/`postBalances` et
  se mélange aux frais de transaction, rendant l'égalité exacte rare.

### Piège écarté en chemin

Une version de l'outil identifiait le quote comme « le mint le plus fréquent de
l'échantillon ». C'est faux : le quote étant du SOL natif, il n'apparaît jamais
dans `postTokenBalances`, et l'heuristique classait des tokens de base comme
quotes. La bonne règle est de traiter le SOL natif et le WSOL comme quote, tout
le reste comme base.
