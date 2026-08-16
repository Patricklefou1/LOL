# Exploitation — tâches planifiées de la capture

Deux tâches systemd complètent le service `pumpfun-capture`. Elles ne le
touchent jamais : `Nice`, `IOSchedulingClass=idle` et `CPUWeight` bas garantissent
que la capture garde la priorité sur le disque et le CPU.

## `rafraichir-derivees.sh` — toutes les 15 minutes

Deux tables ne sont écrites par **aucun code de la capture** : le service
n'archive que le brut (`pumpswap_events`). Elles se périmaient donc en silence,
sans qu'aucune ligne de santé ne le signale.

| Table | Alimentée par |
|---|---|
| `pumpswap_trades` | décodage des `BuyEvent`/`SellEvent` de `pumpswap_events` |
| `pumpswap_pools` | résolution RPC des comptes Pool (`src/pools.ts`) |

Constaté le 15/08 : les deux avaient gelé le 13/08 vers 22 h, soit **18 h de
retard**, avec 15,8 M d'événements non décodés. Toute étude PumpSwap menée dans
cet intervalle mesurait un passé arbitraire.

Le décodage est **incrémental** — filigrane sur le plus grand slot déjà traité,
jamais de `CREATE OR REPLACE`, qui exigerait ~10 Gio libres pendant le
basculement. Un plafond de 40 000 slots par passage empêche qu'un gros retard
soit rattrapé d'un seul bloc : le premier essai a inséré 37 M de lignes et fait
tomber le disque de 12 à 2,4 Gio libres.

Garde-fous : verrou `flock`, plancher disque vérifié avant chaque lot, marge de
2 000 slots pour ne pas décoder un slot à moitié rempli, contrôle non circulaire
du décodeur qui **fait échouer le passage** si la médiane sort de [0,90 ; 1,10],
et remise d'office de `pumpswap_trades` sur la politique de stockage `etage`
(sans quoi elle reste sur le seul disque chaud de 38 Gio).

## `releve-borne-ancrage.sh` — tous les jours à 06h00 UTC

Reconstruit le pipeline d'étude — bougies de 5 min sur `event_timestamp`, blocs
d'une heure figés, signaux — puis applique les trois protocoles pré-enregistrés
de `../etudes/PROTOCOLE-BORNE-ANCRAGE.md` et confronte le résultat à leurs
critères. Le rapport daté est écrit dans `/opt/pumpfun/releves/`.

Le script **ne modifie jamais les paramètres** : ils sont figés dans le
protocole, il ne fait que mesurer.

Aucun verdict, ni validation ni mort, n'est prononcé sous l'effectif minimal du
protocole. Sans ce garde-fou, le passage du 16/08 avait déclaré v2 « TUÉ » sur
un seul token — la statistique « sans top 3 » valant mécaniquement 0 quand on
retire les trois meilleurs d'un échantillon qui en compte un.

## Installation

Les scripts sont exposés sous `/opt/pumpfun/bin/` par des **liens symboliques**
vers ce dossier, pour qu'il n'existe qu'une seule source de vérité.

```bash
sudo ln -sf /opt/pumpfun/LOL/capture/ops/rafraichir-derivees.sh   /opt/pumpfun/bin/
sudo ln -sf /opt/pumpfun/LOL/capture/ops/releve-borne-ancrage.sh  /opt/pumpfun/bin/
sudo cp /opt/pumpfun/LOL/capture/ops/pumpfun-*.service /etc/systemd/system/
sudo cp /opt/pumpfun/LOL/capture/ops/pumpfun-*.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pumpfun-derivees.timer pumpfun-releve.timer
```

**Conséquence à connaître** : changer de branche dans ce dépôt change les
scripts que systemd exécute. C'est le prix du lien symbolique, et c'est
préférable à deux copies qui divergent sans qu'on le sache — le mode de panne
qu'on vient précisément de corriger sur `pumpswap_trades`.

## Secrets

Les deux scripts lisent `../.env` au moment de s'exécuter et n'affichent jamais
sa valeur. **Aucun secret ne figure dans ce dossier** ; le dépôt est public.
