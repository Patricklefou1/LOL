# Protocole de validation — étude 15

Ce fichier est **pré-enregistré**. Les paramètres, la coupure et les critères de
passage sont figés *avant* de voir les données de validation. C'est ce qui
distingue une validation d'une justification a posteriori.

Ne rien modifier ici en fonction du résultat. Si le résultat déplaît, c'est le
résultat qui compte, pas le protocole.

---

## Paramètres figés

Aucun de ces réglages ne doit être touché, ni « juste un peu ajusté » :

| Paramètre | Valeur |
|---|---|
| Univers | pools PumpSwap, ≥ 120 min de vie et ≥ 200 trades |
| Durée du couloir | **30 minutes strictement précédentes** |
| Largeur du couloir | `haut / bas ≤ 1,10` |
| Activité minimale | ≥ 60 trades sur la fenêtre |
| Déclenchement | `prix > haut × 1,01` |
| Entrée | minute suivant le signal |
| Taille | 0,5 SOL, et ≤ 10 % des réserves du pool (`qr_e ≥ 5`) |
| Horizon principal | **30 minutes** |
| Frais | 0,6 % l'aller-retour (PumpSwap) |

## Coupure

**2026-08-12 18:26:00 UTC.** À cet instant la base contenait 37 M d'événements
PumpSwap sur 55 h, et c'est sur ces données que les paramètres ci-dessus ont été
choisis. Tout signal dont l'horodatage d'entrée est postérieur est hors
échantillon.

## Référence dans l'échantillon de réglage

| Mesure | Valeur |
|---|---|
| Signaux (30 min) | 464 |
| Médiane | **1,0261** |
| Baseline appariée | 0,9995 |
| Écart | **+2,66 points** |
| Trades gagnants | 63,1 % |
| Pertes > 20 % | 7,6 % |
| Moyenne brute | 2,804 *(inutilisable — portée par des queues à ×314)* |
| **Moyenne sans les 10 meilleurs** | **0,9698** |

## Critères de décision, décidés à l'avance

Échantillon minimal : **300 signaux** à l'horizon 30 minutes. En dessous, le
test n'est pas concluant et on attend — on ne conclut pas sur moins.

**VALIDÉ** si les trois conditions sont réunies :
- médiane hors échantillon ≥ **1,015**
- écart à la baseline appariée ≥ **+1,5 point**
- taux de trades gagnants ≥ **58 %**

**TUÉ** si l'une des trois est vraie :
- médiane < **1,005**
- écart à la baseline < **+0,5 point**
- **moyenne privée de ses 10 meilleurs signaux < 1,000**

> Le troisième critère a été **ajouté** après avoir constaté, sur l'échantillon
> de réglage, que la moyenne passe de 2,804 à 0,9698 en retirant 10 signaux sur
> 523. C'est un durcissement, jamais un assouplissement : ajouter une condition
> de mort est légitime, relâcher un seuil de passage ne l'est pas.

**NON CONCLUANT** entre les deux : prolonger la fenêtre et refaire, sans rien
changer d'autre.

## Exécution

L'ordre compte. `pumpswap_trades` est une table **dérivée** qui ne se met pas à
jour toute seule : la mesurer sans la rafraîchir donne les chiffres du dernier
décodage, à l'identique. Ce piège a été rencontré une fois — les chiffres
étaient rigoureusement inchangés, ce qui a mis la puce à l'oreille.

```bash
cd /opt/pumpfun/LOL/capture
set -a; . ./.env; set +a

# 1. rafraîchir les trades décodés depuis les événements bruts
clickhouse-client --password "$CLICKHOUSE_PASSWORD" -n < etudes/pumpswap-decode.sql

# 2. reconstruire les signaux et mesurer
clickhouse-client --password "$CLICKHOUSE_PASSWORD" -n < etudes/reveil-postgraduation.sql

# 3. test hors échantillon
clickhouse-client --password "$CLICKHOUSE_PASSWORD" --query "
CREATE OR REPLACE TABLE pumpfun.tmp_oos ENGINE = MergeTree ORDER BY (pool, m) AS
SELECT s.pool AS pool, s.m AS m, s.p_e AS p_e, s.h30 AS h30, s.qr_e AS qr_e,
       v.t0 + toIntervalMinute(s.m) AS t_signal
FROM pumpfun.tmp_ps_ok s
INNER JOIN (SELECT pool, min(received_at) AS t0 FROM pumpfun.pumpswap_trades GROUP BY pool) v
  ON v.pool = s.pool
WHERE s.m >= 31 AND s.bas > 0 AND s.haut/s.bas <= 1.10 AND s.tr30 >= 60
  AND s.prix > s.haut*1.01 AND s.p_e > 0 AND s.qr_e >= 5"

clickhouse-client --password "$CLICKHOUSE_PASSWORD" --query "
SELECT if(t_signal < toDateTime('2026-08-12 18:26:00'), 'reglage', 'HORS ECHANTILLON') AS periode,
  count() AS n, round(median(h30/p_e), 4) AS mediane,
  round(100*countIf(h30/p_e > 1.01)/count(), 1) AS pct_gagnant,
  round(100*countIf(h30/p_e < 0.8)/count(), 1)  AS pct_perte_20
FROM pumpfun.tmp_oos WHERE h30 > 0 GROUP BY periode ORDER BY periode"

# baseline appariée sur la même période hors échantillon
clickhouse-client --password "$CLICKHOUSE_PASSWORD" --query "
SELECT count() AS n, round(median(h30/p_e), 4) AS baseline
FROM pumpfun.tmp_ps_ok s
INNER JOIN (SELECT pool, min(received_at) AS t0 FROM pumpfun.pumpswap_trades GROUP BY pool) v
  ON v.pool = s.pool
WHERE s.m >= 31 AND s.p_e > 0 AND s.h30 > 0 AND s.tr30 >= 60 AND s.qr_e >= 5
  AND v.t0 + toIntervalMinute(s.m) >= toDateTime('2026-08-12 18:26:00')"
```

## Quand

Le débit observé est d'environ **9 signaux par heure de capture**. Il faut donc
~50 heures de données neuves pour atteindre les 300 signaux du seuil minimal.

**Premier test possible : à partir du 15 août 2026.** Avant, ce n'est pas la
peine — au 12 août 21h40, la fenêtre hors échantillon ne contenait que
**7 signaux**, sur lesquels rien ne se conclut (7 succès sur 7 arrivent par
hasard une fois sur vingt).

## Après le verdict

**Si VALIDÉ** : passer au shadow — moteur incrémental sur le flux live, fills
simulés, journal complet. Deux semaines minimum avant tout capital réel. Ne pas
sauter cette étape : elle mesure si le pipeline temps réel reproduit la
recherche.

**Si TUÉ** : consigner dans le registre avec les chiffres, et ne pas retester
des variantes du même motif. Le cimetière sert à ça.

**Si NON CONCLUANT** : attendre. Ne pas élargir les critères pour faire passer
le résultat — c'est exactement ainsi qu'on fabrique un edge qui n'existe pas.
