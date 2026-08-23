#!/usr/bin/env bash
#
# Rafraichit la couche derivee de la capture Pump.fun.
#
# Deux tables ne sont ecrites par AUCUN code de la capture live : le service
# n'archive que le brut (pumpswap_events). Elles se periment donc en silence,
# sans qu'aucune ligne de sante ne le signale.
#
#   pumpswap_trades  <- decodage des BuyEvent/SellEvent de pumpswap_events
#   pumpswap_pools   <- resolution des comptes Pool par RPC (src/pools.ts)
#
# L'ordre est impose : pools.ts cherche les pools actifs dans pumpswap_trades,
# il faut donc decoder avant de resoudre.
#
# INCREMENTAL, jamais CREATE OR REPLACE. La reconstruction complete de
# pumpswap_trades demanderait ~10 Gio libres pendant le basculement, ce qui ne
# tient pas sur ce disque. On n'ajoute ici que les slots nouveaux.
#
# Relancable sans risque : le filigrane est le plus grand slot deja decode, et
# pools.ts ne demande que les pools absents de sa table.
#
# LIMITE CONNUE : si une insertion est interrompue en plein vol, le filigrane
# repart du plus grand slot ecrit ; les slots inferieurs de ce meme lot qui
# n'auraient pas ete ecrits sont perdus. Le decoupage en lots borne la casse a
# un lot. Aucune cle de deduplication n'existe sur la table, un recouvrement
# creerait des doublons — pires que le trou pour les etudes.

set -euo pipefail

ENV_FILE=/opt/pumpfun/LOL/capture/.env
CAPTURE_DIR=/opt/pumpfun/LOL/capture
VERROU=/tmp/rafraichir-derivees.lock

# Marge de slots laissee de cote en fin de flux : les evenements d'un slot
# arrivent groupes mais pas instantanement. Sans marge on decoderait un slot a
# moitie rempli, et son reste serait perdu au passage suivant.
MARGE_SLOTS=${MARGE_SLOTS:-2000}

# Taille d'un lot, en slots. ~2,5 slots/s, donc 10 000 slots ~ 1 h de flux,
# soit ~0,25 Gio sur le disque. Mesure du premier passage : un lot de 20 000
# slots coutait ~0,5 Gio, ce qui rendait la garde disque trop tardive.
LOT_SLOTS=${LOT_SLOTS:-10000}

# Travail maximal par passage. SANS CE PLAFOND, un gros retard est rattrape
# d'un seul bloc : le premier passage reel a insere 37 millions de lignes et
# fait tomber le disque de 12 a 2,4 Gio libres. Un retard important se rattrape
# maintenant sur plusieurs passages successifs, jamais d'un coup.
MAX_SLOTS_PAR_PASSAGE=${MAX_SLOTS_PAR_PASSAGE:-40000}

# Plancher d'espace disque. En dessous, on ne demarre pas et on interrompt.
# Doit garder plusieurs lots d'avance sur le cout d'un lot.
DISQUE_MIN_GIO=${DISQUE_MIN_GIO:-6}

# Nombre de pools les plus actifs soumis a la resolution RPC par passage.
POOLS_MAX=${POOLS_MAX:-5000}

journal() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }
echec()   { journal "ECHEC: $*"; exit 1; }

# --- Verrou : jamais deux passages simultanes ------------------------------
exec 9>"$VERROU"
if ! flock -n 9; then
  journal "un passage est deja en cours, celui-ci s'arrete"
  exit 0
fi

# --- Garde disque ----------------------------------------------------------
libre_gio=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
if [ "$libre_gio" -lt "$DISQUE_MIN_GIO" ]; then
  echec "disque a ${libre_gio} Gio libres, plancher a ${DISQUE_MIN_GIO}"
fi
journal "demarrage — disque ${libre_gio} Gio libres"

# --- Secrets : lus, jamais affiches ---------------------------------------
[ -r "$ENV_FILE" ] || echec "$ENV_FILE illisible (ce script tourne sous l'utilisateur pumpfun)"
lire_env() { grep -m1 "^$1=" "$ENV_FILE" | cut -d= -f2- || true; }

CH_URL=$(lire_env CLICKHOUSE_URL)
CH_USER=$(lire_env CLICKHOUSE_USER)
CH_PASS=$(lire_env CLICKHOUSE_PASSWORD)
CH_DB=$(lire_env CLICKHOUSE_DATABASE)
[ -n "$CH_PASS" ] || echec "CLICKHOUSE_PASSWORD absent de $ENV_FILE"
[ -n "$CH_DB" ]   || CH_DB=pumpfun

ch() { clickhouse-client --user "${CH_USER:-default}" --password "$CH_PASS" --database "$CH_DB" "$@"; }

ch -q "SELECT 1" >/dev/null 2>&1 || echec "ClickHouse injoignable ou identifiants refuses"

# --- Auto-reparation de l'etage de stockage --------------------------------
# pumpswap-decode.sql recree la table sans SETTINGS storage_policy : toute
# reconstruction complete la ramene sur 'default', c'est-a-dire sur le seul
# disque chaud de 38 Gio, sans acces aux 98 Gio du disque froid. Constate le
# 2026-08-15, a 26 h de la saturation. On le remet d'office.
politique=$(ch -q "SELECT storage_policy FROM system.tables WHERE database='$CH_DB' AND name='pumpswap_trades'")
if [ "$politique" != "etage" ]; then
  journal "AVERTISSEMENT: pumpswap_trades est sur la politique '$politique', remise sur 'etage'"
  ch -q "ALTER TABLE pumpswap_trades MODIFY SETTING storage_policy = 'etage'" \
    || journal "AVERTISSEMENT: remise sur 'etage' refusee, le disque chaud se remplira"
fi

# --- Volet 1 : decodage incremental de pumpswap_trades ---------------------
filigrane=$(ch -q "SELECT ifNull(max(slot), 0) FROM pumpswap_trades")
slot_max_brut=$(ch -q "SELECT ifNull(max(slot), 0) FROM pumpswap_events")
plafond=$(( slot_max_brut - MARGE_SLOTS ))

# Plafond de travail : on ne rattrape jamais tout un gros retard d'un seul coup.
retard=$(( plafond - filigrane ))
if [ "$retard" -gt "$MAX_SLOTS_PAR_PASSAGE" ]; then
  plafond=$(( filigrane + MAX_SLOTS_PAR_PASSAGE ))
  journal "retard de $retard slots — plafonne a $MAX_SLOTS_PAR_PASSAGE pour ce passage, le reste suivra"
fi

journal "filigrane pumpswap_trades = slot $filigrane ; brut jusqu'au slot $slot_max_brut ; plafond $plafond"

total_inseres=0
if [ "$plafond" -le "$filigrane" ]; then
  journal "rien a decoder (retard inferieur a la marge de $MARGE_SLOTS slots)"
else
  borne_basse=$filigrane
  while [ "$borne_basse" -lt "$plafond" ]; do
    borne_haute=$(( borne_basse + LOT_SLOTS ))
    [ "$borne_haute" -gt "$plafond" ] && borne_haute=$plafond

    libre_gio=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
    if [ "$libre_gio" -lt "$DISQUE_MIN_GIO" ]; then
      journal "arret du decodage : disque tombe a ${libre_gio} Gio"
      break
    fi

    ch -q "
      INSERT INTO pumpswap_trades
        (slot, signature, received_at, is_buy, pool, user, coin_creator,
         event_timestamp, base_reserves, quote_reserves, base_amount,
         quote_amount, user_quote_amount, price_sol)
      WITH d AS (
        SELECT slot, signature, received_at, base64Decode(payload) AS b,
               toUInt8(CAST(event_name AS String) = 'BuyEvent') AS is_buy
        FROM pumpswap_events
        WHERE slot > $borne_basse AND slot <= $borne_haute
          AND CAST(event_name AS String) IN ('BuyEvent','SellEvent')
          AND length(base64Decode(payload)) >= 336)
      SELECT slot, signature, received_at, is_buy,
        base58Encode(substring(b, 113, 32)) AS pool,
        base58Encode(substring(b, 145, 32)) AS user,
        base58Encode(substring(b, 305, 32)) AS coin_creator,
        reinterpretAsInt64(substring(b, 1, 8))    AS event_timestamp,
        reinterpretAsUInt64(substring(b, 41, 8))  AS base_reserves,
        reinterpretAsUInt64(substring(b, 49, 8))  AS quote_reserves,
        reinterpretAsUInt64(substring(b, 9, 8))   AS base_amount,
        reinterpretAsUInt64(substring(b, 57, 8))  AS quote_amount,
        reinterpretAsUInt64(substring(b, 105, 8)) AS user_quote_amount,
        if(base_reserves > 0, (quote_reserves / 1e9) / (base_reserves / 1e6), 0) AS price_sol
      FROM d" || echec "insertion refusee sur les slots ]$borne_basse, $borne_haute]"

    borne_basse=$borne_haute
  done

  nouveau_filigrane=$(ch -q "SELECT ifNull(max(slot), 0) FROM pumpswap_trades")
  total_inseres=$(ch -q "SELECT count() FROM pumpswap_trades WHERE slot > $filigrane")
  journal "decodage termine — $total_inseres lignes ajoutees, filigrane $filigrane -> $nouveau_filigrane"
fi

# --- Controle non circulaire : le decodeur dit-il encore vrai ? ------------
# Entre deux trades consecutifs d'un meme pool, la variation des reserves doit
# egaler le montant du trade. Mediane attendue ~1,00 ; l'ancien decodeur fautif
# donnait 85 a 1185. Mesure sur les lignes fraiches uniquement.
if [ "${total_inseres:-0}" -gt 1000 ]; then
  # Echantillon d'un pool sur vingt, et memoire plafonnee : la fonction de
  # fenetre sur l'integralite des lignes fraiches a fait sauter la limite de
  # 1,5 Gio au premier passage, alors que 89 000 paires suffisent a trancher.
  contr=$(ch --max_memory_usage 1000000000 -q "
    SELECT round(median(r), 4) FROM (
      SELECT abs(toFloat64(quote_reserves) - toFloat64(prec)) / greatest(toFloat64(quote_amount), 1) AS r
      FROM (
        SELECT quote_reserves, quote_amount,
               any(quote_reserves) OVER (PARTITION BY pool ORDER BY received_at
                                         ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING) AS prec
        FROM pumpswap_trades
        WHERE slot > $filigrane AND cityHash64(pool) % 20 = 0)
      WHERE prec > 0 AND quote_amount > 0)")
  journal "controle non circulaire — mediane $contr (attendu ~1,00)"
  # Comparaison en entier au centieme : bash ne fait pas de flottant.
  c100=$(printf '%.0f' "$(echo "$contr" | awk '{print $1*100}')")
  if [ "$c100" -lt 90 ] || [ "$c100" -gt 110 ]; then
    echec "le decodeur derive : mediane $contr hors de [0,90 ; 1,10] — format PumpSwap probablement change"
  fi
fi

# --- Volet 1 bis : extraction incrementale des evenements rares -------------
# L_archive brute ne garde que 4 jours. Ces trois familles d_evenements ne sont
# decodees nulle part ailleurs ; toute journee non extraite est perdue pour
# toujours. Filigrane par slot, comme le decodage principal.
for t in creations:CreatePoolEvent liquidity:WithdrawEvent,DepositEvent boost:BoostBuyAndBurn; do
  nom=${t%%:*}
  case "$nom" in
    creations) filtre="event_name = 'CreatePoolEvent'"; taille=326
      champs="reinterpretAsInt64(substring(b,1,8)) AS event_timestamp,
        base58Encode(substring(b,166,32)) AS pool, base58Encode(substring(b,11,32)) AS creator,
        base58Encode(substring(b,294,32)) AS coin_creator, base58Encode(substring(b,43,32)) AS base_mint,
        base58Encode(substring(b,75,32)) AS quote_mint, base58Encode(substring(b,198,32)) AS lp_mint,
        reinterpretAsUInt64(substring(b,125,8)) AS pool_base_amount,
        reinterpretAsUInt64(substring(b,133,8)) AS pool_quote_amount,
        reinterpretAsUInt64(substring(b,157,8)) AS lp_out,
        reinterpretAsUInt8(substring(b,326,1)) AS is_mayhem_mode"
      cible=pumpswap_creations ;;
    liquidity) filtre="event_name IN ('WithdrawEvent','DepositEvent')"; taille=248
      champs="CAST(ev AS String) AS event_name, reinterpretAsInt64(substring(b,1,8)) AS event_timestamp,
        base58Encode(substring(b,89,32)) AS pool, base58Encode(substring(b,121,32)) AS user,
        reinterpretAsUInt64(substring(b,9,8)) AS lp_amount, reinterpretAsUInt64(substring(b,81,8)) AS lp_supply,
        reinterpretAsUInt64(substring(b,49,8)) AS base_reserves, reinterpretAsUInt64(substring(b,57,8)) AS quote_reserves,
        reinterpretAsUInt64(substring(b,65,8)) AS base_amount, reinterpretAsUInt64(substring(b,73,8)) AS quote_amount"
      cible=pumpswap_liquidity ;;
    boost) filtre="discriminator = '3f451c16305cc2b9'"; taille=200
      champs="reinterpretAsInt64(substring(b,1,8)) AS event_timestamp, base58Encode(substring(b,9,32)) AS mint,
        base58Encode(substring(b,73,32)) AS pool, base58Encode(substring(b,105,32)) AS authority,
        reinterpretAsUInt64(substring(b,137,8)) AS quote_in_requested, reinterpretAsUInt64(substring(b,145,8)) AS quote_in_used,
        reinterpretAsUInt64(substring(b,153,8)) AS base_burned, reinterpretAsUInt64(substring(b,177,8)) AS quote_reserves_after,
        reinterpretAsUInt64(substring(b,185,8)) AS base_reserves_after, reinterpretAsUInt64(substring(b,193,8)) AS boost_vault_remaining"
      cible=pumpswap_boost ;;
  esac
  fil=$(ch -q "SELECT ifNull(max(slot),0) FROM $cible")
  ajout=$(ch -q "
    INSERT INTO $cible SELECT slot, signature, received_at, $champs
    FROM (SELECT slot, signature, received_at, ev, base64Decode(payload) AS b
          FROM (SELECT slot, signature, received_at, payload, event_name AS ev
                FROM pumpswap_events WHERE $filtre AND slot > $fil AND slot <= $plafond))
    WHERE length(b) = $taille" 2>&1 && ch -q "SELECT count() FROM $cible WHERE slot > $fil")
  journal "$cible — ${ajout:-0} lignes ajoutees (filigrane slot $fil)"
done

# --- Volet 2 : resolution RPC des nouveaux pools ---------------------------
avant=$(ch -q "SELECT count() FROM pumpswap_pools")
if cd "$CAPTURE_DIR" && npm run --silent pools -- "$POOLS_MAX" >/dev/null 2>&1; then
  apres=$(ch -q "SELECT count() FROM pumpswap_pools")
  journal "pools resolus — $avant -> $apres (+$(( apres - avant )))"
else
  # Un echec RPC ne doit pas faire echouer tout le passage : le decodage, lui,
  # est deja acquis, et pools.ts rattrapera au passage suivant.
  journal "AVERTISSEMENT: la resolution RPC des pools a echoue, reprise au prochain passage"
fi

journal "termine — disque $(df -BG --output=avail / | tail -1 | tr -dc '0-9') Gio libres"
