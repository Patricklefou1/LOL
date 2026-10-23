#!/usr/bin/env python3
"""Convertit les DRY de suivi_dry.py (dry.json) au format lu par analyse_setups.py --observations.

    python coinbeacon/dry_vers_observations.py ~/coinbeacon/coinbeacon/.dry/dry.json --groupe principal \\
        --sortie ~/coinbeacon-analyse/principal/observations.jsonl

- Heure de detection : le releve qui a vu le setup (max de computedAt et de l'heure du releve).
  C'est le seul moment ou l'on aurait pu agir.
- Meme actif, meme sens, meme bougie dans plusieurs devises (WUSDT et WUSDC) : un seul mouvement,
  on garde la paire au meilleur score, comme suivi_dry.py.
- Actifs de base stables exclus, comme suivi_dry.py.
- Aucune cle n'est lue : dry.json n'en contient pas.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

TF_MS = {"15m": 15 * 60_000, "1h": 3_600_000, "4h": 4 * 3_600_000, "1d": 86_400_000}
QUOTES = ("FDUSD", "USDT", "USDC", "TUSD", "BUSD", "USD1", "EUR", "TRY", "BRL", "JPY", "BTC", "ETH", "BNB")
STABLES = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "USD1", "BFUSD", "USDS", "USDE", "PYUSD", "RLUSD",
           "XUSD", "EURI", "AEUR", "EUR", "USDT"}


def base_of(symbol: str) -> str:
    for q in QUOTES:
        if symbol.endswith(q) and len(symbol) > len(q):
            return symbol[: -len(q)]
    return symbol


def convert(dry, groupe):
    keep = [d for d in dry if groupe == "tous" or d.get("groupe", "principal") == groupe]
    stats = Counter()
    best = {}
    for d in keep:
        if d.get("sens") not in ("long", "short") or d.get("tf") not in TF_MS:
            stats["sens ou unite inconnus"] += 1
            continue
        base = base_of(d["symbol"])
        if base in STABLES:
            stats["actif de base stable"] += 1
            continue
        k = (d.get("groupe", "principal"), d["tf"], base, d["sens"], d["t0"])
        if k in best:
            stats["doublon d'une autre devise"] += 1
            if (d["score0"], d["symbol"]) > (best[k]["score0"], best[k]["symbol"]):
                best[k] = d
        else:
            best[k] = d
    out = []
    for d in best.values():
        step = TF_MS[d["tf"]]
        bars = None if d.get("trig") is None else round((d["t0"] - d["trig"]) / step)
        out.append({
            "cle": d["id"],
            "premiere_vue_ms": max(d["t0"], d.get("inscrit_ms") or d["t0"]),
            "symbole": d["symbol"], "tf": d["tf"], "archetype": d.get("type"),
            "bars_a_la_premiere_vue": bars,
            # meme formule que CoinBeacon : computedAt - barsSinceTrigger x tf
            "declenchement_cloture_ms": None if bars is None else d["t0"] - bars * step,
            "computedAt_premiere_vue": d["t0"],
            "ligne": {"direction": d["sens"], "score": d.get("score0"), "groupe": d.get("groupe", "principal"),
                      "origine": d.get("origine")},
        })
    out.sort(key=lambda o: (o["premiere_vue_ms"], o["cle"]))
    return out, stats


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dry", type=Path, help="chemin de dry.json")
    p.add_argument("--groupe", choices=["principal", "temoin", "tous"], default="principal")
    p.add_argument("--sortie", type=Path, required=True)
    a = p.parse_args(argv)
    dry = json.loads(a.dry.read_text(encoding="utf-8"))["dry"]
    out, stats = convert(dry, a.groupe)
    a.sortie.parent.mkdir(parents=True, exist_ok=True)
    a.sortie.write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in out), encoding="utf-8")
    print(f"{len(out)} setups ecrits dans {a.sortie} ; ecartes : {dict(stats) or 'aucun'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
