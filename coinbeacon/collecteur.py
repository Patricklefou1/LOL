#!/usr/bin/env python3
"""Collecte du tableau des setups CoinBeacon, a chaque cloture de bougie.

L'API ne garde aucun historique : elle renvoie le tableau du moment, et un setup qui
echoue disparait sans trace. Pour mesurer la rentabilite sans biais de survie, il faut
enregistrer chaque setup la premiere fois qu'on le voit. C'est ce que fait ce script.

    export COINBEACON_TOKEN=...      # jamais dans un fichier
    python coinbeacon/collecteur.py --boucle

Le jeton reste en memoire : le collecteur tourne en boucle dans tmux, et non en tache
planifiee, qui exigerait de l'ecrire sur le disque.

Sorties, hors du depot par defaut (~/coinbeacon-donnees) :
  observations.jsonl  une ligne par setup, a sa premiere apparition
  vues.jsonl          une ligne par setup et par appel (suivi score, prix, disparition)
  appels.jsonl        une ligne par appel : statut HTTP, credits restants, troncature
  brut/               reponses completes compressees, pour pouvoir tout recalculer
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyse_setups import (CANDIDATES, Stop, _SECRETS, extract_records, flatten,  # noqa: E402
                            iso, log, redact)

API = "https://api.coinbeacon.io/public/setups"
FIRED = "pattern_breakout,trendline_break,breakout_retest"
TF_MS = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 7 * 86_400_000}


def tf_ms(tf: str) -> int:
    tf = str(tf).strip().lower()
    return int(tf[:-1]) * TF_MS[tf[-1]]


def pick(row: dict, names):
    for n in names:
        if row.get(n) not in (None, ""):
            return row[n]
    low = {k.lower(): k for k in row}
    for n in names:
        k = low.get(n.lower())
        if k and row.get(k) not in (None, ""):
            return row[k]
    return None


def describe_row(row: dict, default_tf: str):
    """Extrait ce qui identifie un setup. Les noms de champs viennent du message de
    CoinBeacon (tf, computedAt, archetype.barsSinceTrigger) ; la paire est cherchee
    parmi les noms usuels et peut etre forcee avec --champ-paire."""
    flat = flatten(row)
    arche = row.get("archetype")
    if isinstance(arche, dict):
        arche_type = pick(arche, ["type", "name", "id", "key", "kind", "archetype"])
        bars = arche.get("barsSinceTrigger")
    else:
        arche_type, bars = arche, row.get("barsSinceTrigger")
    tf = row.get("tf") or default_tf
    computed = row.get("computedAt")
    return flat, (str(arche_type) if arche_type is not None else None), bars, tf, computed


def setup_key(symbol, tf, arche_type, trigger_close, first_computed):
    anchor = trigger_close if trigger_close is not None else f"vu:{first_computed}"
    return hashlib.sha256(f"{symbol}|{tf}|{arche_type}|{anchor}".encode()).hexdigest()[:24]


class Collecteur:
    def __init__(self, args, token):
        self.args = args
        self.token = token
        self.dir = args.dossier
        (self.dir / "brut").mkdir(parents=True, exist_ok=True)
        self.seen = set()
        obs = self.dir / "observations.jsonl"
        if obs.exists():
            with open(obs, encoding="utf-8") as f:
                self.seen = {json.loads(line)["cle"] for line in f if line.strip()}
        self.session = requests.Session()
        self.pair_field = args.champ_paire

    def _append(self, name, obj):
        with open(self.dir / name, "a", encoding="utf-8") as f:
            f.write(redact(json.dumps(obj, separators=(",", ":"), ensure_ascii=False)) + "\n")

    def poll(self, tf: str):
        params = {"exchange": self.args.exchange, "timeframe": tf, "sort": "fresh"}
        if self.args.archetypes:
            params["archetype"] = self.args.archetypes
        now_ms = int(time.time() * 1000)
        try:
            r = self.session.get(self.args.api_url, params=params, timeout=30,
                                 headers={"X-API-Key": self.token, "Accept": "application/json"})
        except requests.RequestException as e:
            self._append("appels.jsonl", {"t": now_ms, "tf": tf, "erreur": f"{type(e).__name__}: {redact(e)}"})
            log(f"  {tf} : erreur reseau {type(e).__name__}")
            return None
        credits = r.headers.get("X-Credits-Remaining")
        call = {"t": now_ms, "tf": tf, "http": r.status_code, "credits": credits}
        if r.status_code in (401, 403):
            self._append("appels.jsonl", call)
            raise Stop(f"API CoinBeacon : HTTP {r.status_code} (jeton refuse ou expire)", 3)
        if r.status_code != 200:
            self._append("appels.jsonl", call)
            log(f"  {tf} : HTTP {r.status_code}")
            return None
        payload = r.json()
        rows = [x for x in extract_records(payload) if isinstance(x, dict)]
        call["lignes"] = len(rows)
        call["tronque"] = bool(payload.get("truncated")) if isinstance(payload, dict) else None
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(now_ms / 1000))
        raw = self.dir / "brut" / tf / f"{stamp}.json.gz"
        raw.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(raw, "wt", encoding="utf-8") as f:
            f.write(redact(json.dumps(payload, separators=(",", ":"))))
        new = 0
        for row in rows:
            flat, arche_type, bars, row_tf, computed = describe_row(row, tf)
            symbol = flat.get(self.pair_field) if self.pair_field else pick(flat, CANDIDATES["pair"])
            if symbol is None or computed is None:
                call.setdefault("lignes_incompletes", 0)
                call["lignes_incompletes"] += 1
                continue
            computed = int(computed)
            trigger_close = None
            if isinstance(bars, (int, float)):
                # computedAt est la derniere milliseconde de la bougie ; la bougie de
                # declenchement s'est fermee bars bougies plus tot
                trigger_close = computed - int(bars) * tf_ms(row_tf)
            key = setup_key(symbol, row_tf, arche_type, trigger_close, computed)
            self._append("vues.jsonl", {"cle": key, "t": now_ms, "computedAt": computed, "bars": bars,
                                        "score": pick(flat, ["score"]), "price": pick(flat, ["price"])})
            if key in self.seen:
                continue
            self.seen.add(key)
            new += 1
            self._append("observations.jsonl", {
                "cle": key, "premiere_vue_ms": now_ms, "premiere_vue_utc": iso(now_ms),
                "symbole": symbol, "tf": row_tf, "archetype": arche_type, "bars_a_la_premiere_vue": bars,
                "declenchement_cloture_ms": trigger_close, "computedAt_premiere_vue": computed,
                "exchange": self.args.exchange, "ligne": row,
            })
        call["nouveaux"] = new
        self._append("appels.jsonl", call)
        log(f"  {iso(now_ms)} {tf} : {len(rows)} lignes, {new} nouveaux setups"
            + (", TRONQUE" if call["tronque"] else "") + (f", credits restants {credits}" if credits else ""))
        if credits and credits.isdigit() and int(credits) < self.args.credits_min:
            raise Stop(f"credits restants {credits} sous le seuil {self.args.credits_min} : arret", 8)
        return call

    def run_once(self):
        for tf in self.args.timeframes:
            self.poll(tf)

    def run_loop(self):
        delay_ms = int(self.args.delai * 1000)
        last_close = {tf: None for tf in self.args.timeframes}
        step = min(tf_ms(tf) for tf in self.args.timeframes)
        log(f"Collecte en boucle : {', '.join(self.args.timeframes)}, {self.args.delai:g} s apres chaque cloture. "
            f"{len(self.seen)} setups deja connus. Ctrl+C pour arreter.")
        self.run_once()
        for tf in self.args.timeframes:
            last_close[tf] = (int(time.time() * 1000) - delay_ms) // tf_ms(tf)
        while True:
            now = int(time.time() * 1000)
            nxt = ((now - delay_ms) // step + 1) * step + delay_ms
            time.sleep(max(1.0, (nxt - now) / 1000))
            now = int(time.time() * 1000)
            for tf in self.args.timeframes:
                idx = (now - delay_ms) // tf_ms(tf)
                if idx != last_close[tf]:
                    last_close[tf] = idx
                    try:
                        self.poll(tf)
                    except Stop:
                        raise
                    except Exception as e:  # une erreur ponctuelle ne doit pas arreter des semaines de collecte
                        log(f"  {tf} : erreur {type(e).__name__}: {redact(e)}")
                        self._append("appels.jsonl", {"t": now, "tf": tf, "erreur": f"{type(e).__name__}: {redact(e)}"})


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api-url", default=os.environ.get("COINBEACON_API_URL", API))
    p.add_argument("--exchange", default="binance", help="binance = comptant, binance-futures = contrats")
    p.add_argument("--timeframes", nargs="+", default=["1h", "4h"])
    p.add_argument("--archetypes", default=FIRED,
                   help="setups declenches seulement, selon CoinBeacon ; chaine vide pour tout le tableau")
    p.add_argument("--champ-paire", help="nom du champ de la paire, si la detection automatique se trompe")
    p.add_argument("--dossier", type=Path, default=Path.home() / "coinbeacon-donnees")
    p.add_argument("--delai", type=float, default=90, help="secondes apres la cloture avant l'appel")
    p.add_argument("--credits-min", type=int, default=100)
    p.add_argument("--boucle", action="store_true", help="tourner indefiniment")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    token = os.environ.get("COINBEACON_TOKEN", "")
    if not token:
        raise Stop("la variable d'environnement COINBEACON_TOKEN est absente ou vide", 2)
    _SECRETS.append(token)
    c = Collecteur(args, token)
    if args.boucle:
        c.run_loop()
    else:
        c.run_once()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Stop as e:
        log(f"ARRET : {e}")
        sys.exit(e.code)
    except KeyboardInterrupt:
        log("Arret demande.")
        sys.exit(0)
