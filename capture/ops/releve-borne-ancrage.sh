#!/usr/bin/env bash
#
# Releve hors echantillon de la borne d'ancrage — protocoles v1 et v2.
#
# Reconstruit le pipeline (bougies 5 min sur event_timestamp, blocs d'une heure
# figes, signaux) depuis pumpswap_trades, puis applique les deux protocoles
# pre-enregistres de PROTOCOLE-BORNE-ANCRAGE.md et confronte le resultat a leurs
# criteres de decision.
#
#   v1 — couloir <= 1,10, coupure 2026-08-13 20:00:00 UTC
#   v2 — couloir <= 1,15, coupure 2026-08-16 00:00:00 UTC
#   v3 — etude 27 « la montee tenue », coupure 2026-08-17 00:00:00 UTC
#
# Les deux tournent en parallele. v2 ne remplace pas v1 : si les deux valident,
# la conclusion est robuste au reglage du couloir ; si seul v2 valide, le doute
# d'ajustement reste entier.
#
# UNIVERS — deviation documentee. Le protocole ecrit « pools dont le quote est
# WSOL (est_sol = 1) », ce qui suppose pumpswap_pools a jour. Cette table est
# derivee et s'est deja trouvee perimee de 18 h sans alarme. On lui prefere un
# critere intrinseque, insensible a la fraicheur d'une table annexe : reserve
# quote mediane entre 5 et 20 000 SOL, qui est le filtre que les etudes 16 et 17
# utilisaient deja pour isoler les pools libelles en SOL.
#
# LECTURE SEULE sur les tables de production. N'ecrit que ses propres tables
# tmp_rel_*, et son rapport dans le depot d'analyse.

set -euo pipefail

ENV_FILE=/opt/pumpfun/LOL/capture/.env
SORTIE_DIR=${SORTIE_DIR:-/opt/pumpfun/releves}
VERROU=/tmp/releve-borne-ancrage.lock
DISQUE_MIN_GIO=${DISQUE_MIN_GIO:-4}

journal() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >&2; }
echec()   { journal "ECHEC: $*"; exit 1; }

exec 9>"$VERROU"
flock -n 9 || { journal "un releve est deja en cours"; exit 0; }

libre=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
[ "$libre" -ge "$DISQUE_MIN_GIO" ] || echec "disque a ${libre} Gio libres"

[ -r "$ENV_FILE" ] || echec "$ENV_FILE illisible (lancer sous l'utilisateur pumpfun)"
lire_env() { grep -m1 "^$1=" "$ENV_FILE" | cut -d= -f2- || true; }
CH_PASS=$(lire_env CLICKHOUSE_PASSWORD)
CH_USER=$(lire_env CLICKHOUSE_USER)
CH_DB=$(lire_env CLICKHOUSE_DATABASE); [ -n "$CH_DB" ] || CH_DB=pumpfun
[ -n "$CH_PASS" ] || echec "CLICKHOUSE_PASSWORD absent"

ch() { clickhouse-client --user "${CH_USER:-default}" --password "$CH_PASS" --database "$CH_DB" --receive_timeout 3600 "$@"; }
ch -q "SELECT 1" >/dev/null 2>&1 || echec "ClickHouse injoignable"

mkdir -p "$SORTIE_DIR"
JOUR=$(date -u +%F)
RAPPORT="$SORTIE_DIR/releve-$JOUR.md"

journal "reconstruction du pipeline"
ch -n -q "
DROP TABLE IF EXISTS tmp_rel_c5;
CREATE TABLE tmp_rel_c5 ENGINE = MergeTree ORDER BY (pool, b) SETTINGS storage_policy = 'etage' AS
WITH vivants AS (
  SELECT pool, min(toDateTime(event_timestamp)) AS t0 FROM pumpswap_trades
  WHERE event_timestamp > 0 AND price_sol > 0 GROUP BY pool
  HAVING count() >= 200
     AND dateDiff('minute', min(toDateTime(event_timestamp)), max(toDateTime(event_timestamp))) >= 120
     AND median(quote_reserves)/1e9 BETWEEN 5 AND 20000)
SELECT t.pool AS pool,
  toUInt16(intDiv(dateDiff('second', v.t0, toDateTime(t.event_timestamp)), 300)) AS b,
  v.t0 + toIntervalSecond(300 * intDiv(dateDiff('second', v.t0, toDateTime(t.event_timestamp)), 300)) AS t5,
  argMin(t.price_sol, t.event_timestamp) AS ouverture,
  argMax(t.price_sol, t.event_timestamp) AS cloture,
  max(t.price_sol) AS plus_haut, min(t.price_sol) AS plus_bas,
  argMax(t.quote_reserves, t.event_timestamp)/1e9 AS reserve,
  count() AS trades, median(t.quote_amount/1e9) AS taille_med
FROM pumpswap_trades t INNER JOIN vivants v ON v.pool = t.pool
WHERE t.event_timestamp > 0 AND t.price_sol > 0
  AND dateDiff('second', v.t0, toDateTime(t.event_timestamp)) BETWEEN 0 AND 43200
GROUP BY t.pool, b, t5;

DROP TABLE IF EXISTS tmp_rel_bloc;
CREATE TABLE tmp_rel_bloc ENGINE = MergeTree ORDER BY (pool, bloc) AS
SELECT pool, intDiv(b,12) AS bloc, min(plus_bas) AS bas, max(plus_haut) AS borne,
  min(trades) AS trades_min, count() AS bougies, median(taille_med) AS taille_range, max(b) AS b_fin
FROM tmp_rel_c5 GROUP BY pool, bloc HAVING bougies = 12;

DROP TABLE IF EXISTS tmp_rel_ancre;
CREATE TABLE tmp_rel_ancre ENGINE = MergeTree ORDER BY (pool, bloc) AS
SELECT bl.pool AS pool, bl.bloc AS bloc, bl.bas AS bas, bl.borne AS borne,
  bl.trades_min AS trades_min, bl.taille_range AS taille_range,
  argMin(c.b, c.b) AS b_signal, argMin(c.t5, c.b) AS t_signal,
  argMin(c.taille_med, c.b) AS taille_signal
FROM tmp_rel_bloc bl INNER JOIN tmp_rel_c5 c ON c.pool = bl.pool
WHERE c.b > bl.b_fin AND c.b <= bl.b_fin + 12 AND c.cloture > bl.borne * 1.05
GROUP BY bl.pool, bl.bloc, bl.bas, bl.borne, bl.trades_min, bl.taille_range;
" || echec "reconstruction du pipeline"

couverture=$(ch -q "SELECT concat(toString(min(t5)), ' -> ', toString(max(t5))) FROM tmp_rel_c5")
journal "pipeline reconstruit — couverture $couverture"

mesure() { # $1 = couloir, $2 = coupure
  ch -q "
  SELECT concat(
    toString(uniqExact(pool)), '|', toString(count()), '|',
    toString(round(avg(x),4)), '|', toString(round(median(x),4)), '|',
    if(count() >= 4, toString(round((sum(x)-arraySum(arraySlice(arraySort(groupArray(x)), count()-2)))/(count()-3),4)), 'n/a'), '|',
    toString(round(100*countIf(x>1)/count(),1)), '|',
    toString(round(100*countIf(x<0.2)/count(),2)))
  FROM (
    SELECT a.pool AS pool, (s.cloture/e.ouverture)*(1-0.5/e.reserve)*(1-0.5/e.reserve)*0.994 AS x
    FROM tmp_rel_ancre a
    INNER JOIN tmp_rel_c5 e ON e.pool = a.pool AND e.b = a.b_signal + 1
    INNER JOIN tmp_rel_c5 s ON s.pool = a.pool AND s.b = a.b_signal + 7
    WHERE a.borne/a.bas <= $1 AND a.trades_min >= 5 AND e.reserve >= 5
      AND a.taille_range >= 0.01 AND a.taille_signal/a.taille_range <= 3
      AND a.t_signal + INTERVAL 300 SECOND > '$2')"
}

MIN_TOKENS=${MIN_TOKENS:-150}

verdict() { # $1 tokens $2 moyenne $3 sanstop3 $4 gagnants $5 effondr
  awk -v t="$1" -v m="$2" -v s="$3" -v g="$4" -v e="$5" -v mini="$MIN_TOKENS" 'BEGIN{
    if (t+0 == 0) { print "EN ATTENTE (aucun signal depuis la coupure)"; exit }

    # AUCUN verdict sous l_echantillon minimal, ni validation ni mort. Le
    # protocole fixe 150 tokens pour la decision, pas seulement pour valider :
    # on ne peut pas plus tuer sur un token que valider sur un token. Sans ce
    # garde-fou le releve du 16/08 a declare v2 TUE sur 1 token, parce que la
    # statistique « sans top 3 » vaut mecaniquement 0 quand on retire les trois
    # meilleurs d_un echantillon qui en compte un.
    if (t+0 < mini) {
      tendance = "indeterminee"
      if (t+0 >= 4) {
        if (m+0 < 0.995 || s+0 < 0.980 || e+0 > 2.0) tendance = "orientee vers la mort"
        else if (m+0 >= 1.010 && s+0 >= 1.000 && g+0 >= 60.0) tendance = "orientee vers la validation"
        else tendance = "entre les deux"
      }
      printf "NON CONCLUANT — %d/%d tokens, tendance %s\n", t, mini, tendance
      exit }

    if (m+0 < 0.995 || s+0 < 0.980 || e+0 > 2.0) { print "TUE"; exit }
    if (m+0 >= 1.010 && s+0 >= 1.000 && g+0 >= 60.0) { print "VALIDE"; exit }
    print "NON CONCLUANT" }'
}

# --- Protocole v3 : detection « tout vert », mesure au niveau trade -------
# Calcul distinct des v1/v2 : la detection porte sur les 9 premieres bougies et
# l'entree/sortie se lisent sur les trades bruts, pas sur les bougies.
COUPURE_V3="2026-08-17 00:00:00"
journal "v3 — construction des series de trades"
ch -n -q "
DROP TABLE IF EXISTS tmp_rel_v3d;
CREATE TABLE tmp_rel_v3d ENGINE = MergeTree ORDER BY pool AS
SELECT pool, min(t5) AS t0 FROM tmp_rel_c5 GROUP BY pool
HAVING countIf(b < 9) >= 8 AND countIf(b < 9 AND cloture > ouverture) = countIf(b < 9)
   AND min(t5) + INTERVAL 2700 SECOND > toDateTime('$COUPURE_V3');

DROP TABLE IF EXISTS tmp_rel_v3s;
CREATE TABLE tmp_rel_v3s ENGINE = MergeTree ORDER BY pool AS
SELECT d.pool AS pool,
  arraySort(z -> z.1, groupArray((toDateTime(t.event_timestamp), t.price_sol, t.quote_reserves/1e9))) AS serie
FROM tmp_rel_v3d d INNER JOIN pumpswap_trades t ON t.pool = d.pool
WHERE toDateTime(t.event_timestamp) >= d.t0 + INTERVAL 2700 SECOND
  AND toDateTime(t.event_timestamp) <  d.t0 + INTERVAL 3900 SECOND
  AND t.price_sol > 0
GROUP BY d.pool;" || echec "construction v3"

mesure_v3() {
  ch -q "
  SELECT concat(
    toString(count()), '|', toString(round(avg(x),4)), '|', toString(round(median(x),4)), '|',
    if(count() >= 4, toString(round((sum(x)-arraySum(arraySlice(arraySort(groupArray(x)), count()-2)))/(count()-3),4)), 'n/a'), '|',
    toString(round(100*countIf(x>1)/count(),1)), '|',
    toString(round(100*countIf(x<0.5)/count(),1)), '|',
    if(count() >= 2 AND stddevSamp(x) > 0, toString(round((avg(x)-1)/(stddevSamp(x)/sqrt(count())),2)), 'n/a'))
  FROM (
    SELECT (serie[i_s].2/serie[1].2)*(1-0.5/serie[1].3)*(1-0.5/serie[1].3)*0.994 AS x
    FROM (
      SELECT serie, arrayFirstIndex(y -> y.1 >= serie[1].1 + toIntervalSecond(900), serie) AS i0,
        if(i0 = 0, length(serie), i0) AS i_s
      FROM tmp_rel_v3s
      WHERE length(serie) > 2 AND serie[1].2 > 0 AND serie[1].3 >= 5))"
}

verdict_v3() { # $1 tokens $2 moyenne $3 sanstop3 $4 pertes_lourdes $5 t
  awk -v n="$1" -v m="$2" -v s="$3" -v pl="$4" -v t="$5" 'BEGIN{
    if (n+0 == 0) { print "EN ATTENTE (aucun token depuis la coupure)"; exit }
    # Mort possible des 500 tokens ; validation seulement a 4596, effectif
    # derive de la dispersion mesuree et non choisi.
    if (n+0 >= 500 && (m+0 < 0.995 || (t != "n/a" && t+0 <= -2.0) || pl+0 > 10.0)) { print "TUE"; exit }
    if (n+0 >= 4596 && m+0 >= 1.003 && s != "n/a" && s+0 >= 1.000 && t != "n/a" && t+0 >= 2.0) { print "VALIDE"; exit }
    printf "NON CONCLUANT — %d/4596 tokens\n", n }'
}

{
  echo "# Relevé hors échantillon — $JOUR"
  echo
  echo "Généré le $(date -u +%FT%TZ). Couverture des données : $couverture."
  echo "Univers : réserve quote médiane entre 5 et 20 000 SOL (voir en-tête du script)."
  echo
  for proto in "v1|1.10|2026-08-13 20:00:00" "v2|1.15|2026-08-16 00:00:00"; do
    nom=${proto%%|*}; reste=${proto#*|}; couloir=${reste%%|*}; coupure=${reste#*|}
    IFS='|' read -r tk tr moy med st3 gag eff <<< "$(mesure "$couloir" "$coupure")"
    [ -n "${tk:-}" ] || { echo "## Protocole $nom — aucune donnée"; echo; continue; }
    v=$(verdict "$tk" "$moy" "$st3" "$gag" "$eff")
    echo "## Protocole $nom — couloir ≤ $couloir, coupure $coupure UTC"
    echo
    echo "| Mesure | Valeur | Validation | Mort |"
    echo "|---|---|---|---|"
    echo "| Tokens | **$tk** | 150 requis | — |"
    echo "| Trades | $tr | — | — |"
    echo "| Moyenne | **$moy** | ≥ 1,010 | < 0,995 |"
    echo "| Médiane | $med | — | — |"
    echo "| Moyenne sans top 3 | **$st3** | ≥ 1,000 | < 0,980 |"
    echo "| Gagnants | $gag % | ≥ 60 % | — |"
    echo "| Effondrements | $eff % | — | > 2 % |"
    echo
    echo "**Verdict : $v**"
    echo
    journal "$nom — $tk tokens, moyenne $moy, sans top 3 $st3, gagnants $gag %, effondrements $eff % — $v"
  done
  IFS='|' read -r n3 m3 med3 st3 g3 pl3 t3 <<< "$(mesure_v3)"
  if [ -n "${n3:-}" ]; then
    v3=$(verdict_v3 "$n3" "$m3" "$st3" "$pl3" "$t3")
    echo "## Protocole v3 — étude 27, « la montée tenue » — coupure $COUPURE_V3 UTC"
    echo
    echo "| Mesure | Valeur | Validation | Mort |"
    echo "|---|---|---|---|"
    echo "| Tokens | **$n3** | 4 596 requis | 500 minimum |"
    echo "| Moyenne | **$m3** | ≥ 1,003 | < 0,995 |"
    echo "| Médiane | $med3 | — | — |"
    echo "| Moyenne sans top 3 | $st3 | ≥ 1,000 | — |"
    echo "| Gagnants | $g3 % | — | — |"
    echo "| Pertes > 50 % | $pl3 % | — | > 10 % |"
    echo "| **t de Student** | **$t3** | ≥ 2,0 | ≤ −2,0 |"
    echo
    echo "**Verdict : $v3**"
    echo
    journal "v3 — $n3 tokens, moyenne $m3, sans top 3 $st3, t $t3 — $v3"
  fi
  echo "---"
  echo
  echo "Les paramètres des trois protocoles sont figés dans"
  echo "\`capture/etudes/PROTOCOLE-BORNE-ANCRAGE.md\`. Ce relevé ne les modifie pas."
} > "$RAPPORT"

ch -n -q "DROP TABLE IF EXISTS tmp_rel_c5; DROP TABLE IF EXISTS tmp_rel_bloc; DROP TABLE IF EXISTS tmp_rel_ancre; DROP TABLE IF EXISTS tmp_rel_v3d; DROP TABLE IF EXISTS tmp_rel_v3s;"
journal "rapport ecrit : $RAPPORT"
