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

### Montants (validés contre les variations de solde, 45 tx par forme)

| Forme | Offset | Contenu | Confirmation |
|---|---|---|---|
| BuyEvent 472 | `@8` | quote entrant | 29/45 |
| BuyEvent 472 | `@96` | base reçu par l'utilisateur | 29/45 |
| SellEvent 409 | `@104` | mouvement réel côté base | 34/45 |

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
