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

Établi (45 transactions par forme) :

| Forme | Offset | Contenu | Confirmation |
|---|---|---|---|
| BuyEvent 472 | `@8` | quote entrant | 29/45 |
| BuyEvent 472 | `@96` | base reçu par l'utilisateur | 29/45 |
| SellEvent 409 | `@104` | mouvement réel | 34/45 |
| toutes | `@112`–`@272` | bloc de 6 pubkeys de la transaction | 12/12 |

Non établi, et à faire avant tout usage :

- la disposition de `BuyEvent` 457 — aucun offset ne dépasse le seuil ;
- **quelle pubkey est le pool** parmi les six du bloc ;
- **où sont les réserves** : aucun offset ne reproduit un solde de coffre
  post-trade. L'hypothèse `@40`/`@48` du premier décodeur est infirmée.

Limite connue de l'outil : il classe le *quote* en supposant qu'il s'agit de
SOL ou de WSOL. Les paires PumpSwap quotées en un autre token sont donc mal
classées, ce qui explique une partie des 36 % non confirmés. À corriger en
lisant le mint du pool plutôt qu'en le supposant.
