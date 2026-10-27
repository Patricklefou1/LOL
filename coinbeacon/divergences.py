#!/usr/bin/env python3
"""Test historique des divergences RSI, recalculees a partir des prix Binance au comptant.

Outil d'appoint : il ne reproduit pas le score de CoinBeacon, qui est ce qu'il faut tester. Il sert
a verifier la definition de leurs divergences (--cas) et a fournir un point de comparaison sans score.

Contrairement aux setups CoinBeacon, une divergence se recalcule avec les seuls prix : on peut
donc la tester sur des annees d'historique, pour toutes les paires, sans attendre une collecte.

Definition par defaut, celle de l'indicateur « RSI Divergence » de TradingView, a confirmer
contre le detecteur CoinBeacon avec --cas :
  - RSI de Wilder sur 14 bougies de cloture ;
  - pivots cherches sur le RSI, 5 bougies a gauche et 5 a droite ;
  - deux pivots consecutifs du meme genre, separes de 5 a 60 bougies ;
  - haussiere classique : prix plus bas, RSI plus haut (sur les creux) ;
    haussiere cachee : prix plus haut, RSI plus bas (sur les creux) ;
    baissiere classique : prix plus haut, RSI plus bas (sur les sommets) ;
    baissiere cachee : prix plus bas, RSI plus haut (sur les sommets).

Le signal n'existe qu'a la confirmation du second pivot, 5 bougies plus tard : l'entree se fait
a l'ouverture de la bougie 1 h qui commence a la cloture de cette bougie de confirmation.
La sortie se fait a la cloture de la bougie 1 h qui commence a l'entree + H - 1 h, pour une duree
de H exactement.

    python coinbeacon/divergences.py                          # toutes les paires USDT depuis 2023
    python coinbeacon/divergences.py --max-paires 20          # essai rapide
    python coinbeacon/divergences.py --cas 'binance|PENGUUSDT|1w|rsi|hidden|bear|1777852800000|1789948800000'

Aucune cle n'est necessaire : seules les bougies publiques de Binance sont lues, et mises en cache.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyse_setups as A  # noqa: E402

HOUR = A.HOUR_MS
DAY = A.DAY_MS
WEEK = 7 * DAY
MONDAY = 4 * DAY  # le 1er janvier 1970 est un jeudi : les semaines Binance commencent le lundi
TF_MS = {"1h": HOUR, "4h": 4 * HOUR, "1d": DAY, "1w": WEEK}
BLOCK = 1000 * HOUR
STABLES = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "USD1", "BFUSD", "USDS", "USDE", "PYUSD", "RLUSD",
           "XUSD", "EURI", "AEUR", "EUR", "UST", "USTC", "PAX", "SUSD", "GUSD"}
LEVIER = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")
HERE = Path(__file__).resolve().parent


# --------------------------------------------------------------------------- donnees


def first_hour(binance: A.Binance, symbol: str):
    """Heure de la premiere bougie 1 h de la paire : evite de demander des blocs vides avant la cotation."""
    name = f"premiere_{symbol}"
    cached = binance.cache.get_misc(name, None)
    if cached is not None:
        return cached
    r = binance.http.get(binance.base + "/api/v3/klines",
                         params={"symbol": symbol, "interval": "1h", "startTime": 0, "limit": 1})
    if r.status_code != 200 or not r.json():
        return None
    t = int(r.json()[0][0])
    binance.cache.put_misc(name, t)
    return t


def klines_1h(binance: A.Binance, symbol: str, start: int, end: int, now: int) -> A.Candles:
    rows = []
    listed = first_hour(binance, symbol)
    if listed is None:
        return A.Candles([])
    start = max(start, listed)
    for b in range(start // BLOCK, min(end, now) // BLOCK + 1):
        path = binance.cache.root / "klines_1h" / symbol / f"{b}.json.gz"
        if path.exists():
            rows += A.Cache._read(path)
            continue
        r = binance.http.get(binance.base + "/api/v3/klines", params={
            "symbol": symbol, "interval": "1h", "startTime": b * BLOCK, "endTime": (b + 1) * BLOCK - 1, "limit": 1000})
        if r.status_code == 400:
            break
        if r.status_code != 200:
            raise A.Stop(f"Binance klines 1h {symbol} : HTTP {r.status_code}", 4)
        data = [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])] for k in r.json()]
        if (b + 1) * BLOCK - 1 < now - 2 * HOUR:  # bloc clos : immuable
            A.Cache._write(path, data)
        rows += data
    c = A.Candles(rows)
    keep = c.t + HOUR <= now  # jamais la bougie en cours
    c.t, c.o, c.h, c.l, c.c = c.t[keep], c.o[keep], c.h[keep], c.l[keep], c.c[keep]
    return c


def resample(c: A.Candles, tf: str, min_fill=0.9):
    """Bougies de l'unite tf a partir des bougies 1 h, alignees comme Binance (semaines au lundi).
    Une bougie incomplete (en cours, ou trou de plus de 10 %) est ecartee."""
    if tf == "1h":
        return c.t.copy(), c.o.copy(), c.h.copy(), c.l.copy(), c.c.copy()
    step = TF_MS[tf]
    anchor = MONDAY if tf == "1w" else 0
    g = (c.t - anchor) // step
    if not len(g):
        return (np.array([], dtype=np.int64),) + (np.array([]),) * 4
    starts = np.flatnonzero(np.r_[True, g[1:] != g[:-1]])
    ends = np.r_[starts[1:], len(g)]
    count = ends - starts
    ok = count >= min_fill * (step // HOUR)
    starts, ends = starts[ok], ends[ok]
    t = g[starts] * step + anchor
    o = c.o[starts]
    cl = c.c[ends - 1]
    h = np.array([c.h[s:e].max() for s, e in zip(starts, ends)])
    lo = np.array([c.l[s:e].min() for s, e in zip(starts, ends)])
    return t, o, h, lo, cl


# --------------------------------------------------------------------------- indicateurs


def rsi_wilder(close: np.ndarray, n: int = 14) -> np.ndarray:
    out = np.full(len(close), np.nan)
    if len(close) <= n:
        return out
    d = np.diff(close)
    up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
    au, ad = up[:n].mean(), dn[:n].mean()
    for i in range(n, len(close)):
        if i > n:
            au = (au * (n - 1) + up[i - 1]) / n
            ad = (ad * (n - 1) + dn[i - 1]) / n
        out[i] = 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)
    return out


def pivots(x: np.ndarray, left: int, right: int, kind: str) -> np.ndarray:
    """Indices des pivots : strictement extremes a gauche, au moins egaux a droite."""
    n = len(x)
    res = []
    for i in range(left, n - right):
        v = x[i]
        if np.isnan(v):
            continue
        lw, rw = x[i - left:i], x[i + 1:i + right + 1]
        if np.isnan(lw).any() or np.isnan(rw).any():
            continue
        if kind == "low" and v < lw.min() and v <= rw.min():
            res.append(i)
        elif kind == "high" and v > lw.max() and v >= rw.max():
            res.append(i)
    return np.array(res, dtype=int)


def find_divergences(t, h, lo, cl, tf, args):
    rsi = rsi_wilder(cl, args.rsi)
    out = []
    for kind, price in (("low", lo), ("high", h)):
        src = rsi if args.pivots_sur == "rsi" else price
        piv = pivots(src, args.gauche, args.droite, kind)
        for a, b in zip(piv, piv[1:]):
            if not args.ecart_min <= b - a <= args.ecart_max:
                continue
            conf = b + args.droite
            if conf >= len(t):
                continue
            p1, p2, r1, r2 = price[a], price[b], rsi[a], rsi[b]
            if np.isnan(r1) or np.isnan(r2):
                continue
            if kind == "low":
                typ = "regular" if (p2 < p1 and r2 > r1) else "hidden" if (p2 > p1 and r2 < r1) else None
                direction = "bull"
            else:
                typ = "regular" if (p2 > p1 and r2 < r1) else "hidden" if (p2 < p1 and r2 > r1) else None
                direction = "bear"
            if typ is None:
                continue
            out.append({"tf": tf, "type": typ, "dir": direction, "pivot1_ms": int(t[a]), "pivot2_ms": int(t[b]),
                        "signal_ms": int(t[conf]) + TF_MS[tf], "prix1": float(p1), "prix2": float(p2),
                        "rsi1": float(r1), "rsi2": float(r2), "ecart": int(b - a)})
    return out


# --------------------------------------------------------------------------- mesure


class Mesure:
    """Evaluation vectorisee sur les bougies 1 h d'une paire."""

    def __init__(self, c: A.Candles, horizons):
        self.c = c
        self.hz = horizons
        self.roll = {}
        from numpy.lib.stride_tricks import sliding_window_view as sw
        for H in horizons:
            if len(c) >= H:
                self.roll[H] = (sw(c.h, H).max(axis=1), sw(c.l, H).min(axis=1))

    def evaluate(self, idx: np.ndarray, side: np.ndarray, H: int):
        """idx : indices d'entree (ouverture de la bougie 1 h). Renvoie brut, hausse max, baisse max
        dans le sens de la position ; nan si la fenetre n'est pas complete et continue."""
        c = self.c
        n = len(c)
        res = np.full((3, len(idx)), np.nan)
        if H not in self.roll:
            return res
        ok = (idx >= 0) & (idx + H - 1 < n)
        j = np.where(ok, idx + H - 1, 0)
        i = np.where(ok, idx, 0)
        ok &= (c.t[j] - c.t[i]) == (H - 1) * HOUR
        hi, lo = self.roll[H]
        e = c.o[i]
        gross = c.c[j] / e - 1
        up, down = hi[i] / e - 1, lo[i] / e - 1
        s = side
        g = np.where(s > 0, gross, -gross)
        u = np.where(s > 0, up, -down)
        d = np.where(s > 0, down, -up)
        res[0, ok], res[1, ok], res[2, ok] = g[ok], u[ok], d[ok]
        return res


# --------------------------------------------------------------------------- programme


def parse_cas(text):
    """'binance|PENGUUSDT|1w|rsi|hidden|bear|t1|t2' ou l'URL complete du detecteur."""
    if "div=" in text:
        text = text.split("div=", 1)[1].split("&")[0]
    parts = unquote(text).split("|")
    if len(parts) != 8:
        raise A.Stop(f"cas illisible : {text}", 6)
    ex, sym, tf, ind, typ, dirn, t1, t2 = parts
    if tf not in TF_MS or ind != "rsi":
        raise A.Stop(f"cas non pris en charge : unite {tf}, indicateur {ind}", 6)
    return {"symbol": sym.upper(), "tf": tf, "type": typ, "dir": dirn, "pivot1_ms": int(t1), "pivot2_ms": int(t2)}


def verifier_cas(cas, binance, now, args):
    c = klines_1h(binance, cas["symbol"], cas["pivot1_ms"] - 300 * TF_MS[cas["tf"]], now, now)
    t, o, h, lo, cl = resample(c, cas["tf"])
    divs = find_divergences(t, h, lo, cl, cas["tf"], args)
    same = [d for d in divs if d["pivot1_ms"] == cas["pivot1_ms"] and d["pivot2_ms"] == cas["pivot2_ms"]]
    L = [f"Cas CoinBeacon : {cas['symbol']} {cas['tf']} {cas['type']} {cas['dir']}, pivots "
         f"{A.iso(cas['pivot1_ms'])[:10]} et {A.iso(cas['pivot2_ms'])[:10]}."]
    if same:
        d = same[0]
        ok = d["type"] == cas["type"] and d["dir"] == cas["dir"]
        L.append(("Retrouvé à l'identique" if ok else f"Mêmes pivots mais classé {d['type']} {d['dir']}")
                 + f" : prix {d['prix1']:.6g} puis {d['prix2']:.6g}, RSI {d['rsi1']:.1f} puis {d['rsi2']:.1f}, "
                 f"signal confirmé le {A.iso(d['signal_ms'])} UTC.")
    else:
        near = sorted(divs, key=lambda d: abs(d["pivot2_ms"] - cas["pivot2_ms"]) + abs(d["pivot1_ms"] - cas["pivot1_ms"]))[:3]
        L.append("Non retrouvé avec ces réglages : la définition de CoinBeacon diffère. Divergences les plus proches : "
                 + ("; ".join(f"{d['type']} {d['dir']} {A.iso(d['pivot1_ms'])[:10]} → {A.iso(d['pivot2_ms'])[:10]}"
                              for d in near) or "aucune"))
        for i in (np.searchsorted(t, cas["pivot1_ms"]), np.searchsorted(t, cas["pivot2_ms"])):
            if i < len(t) and t[i] in (cas["pivot1_ms"], cas["pivot2_ms"]):
                r = rsi_wilder(cl, args.rsi)
                L.append(f"Bougie du {A.iso(int(t[i]))[:10]} : haut {h[i]:.6g}, bas {lo[i]:.6g}, RSI {r[i]:.1f}.")
    return L


def universe(binance, args):
    spot = binance.spot_symbols()
    if args.paires:
        return [p.upper() for p in args.paires]
    statuts = {"TRADING", "BREAK"} if args.inclure_retirees else {"TRADING"}
    out = []
    for s, st in spot.items():
        st = st[0] if isinstance(st, (list, tuple)) else st
        if not s.endswith("USDT") or st not in statuts or s.endswith(LEVIER):
            continue
        if s[:-4] in STABLES:
            continue
        out.append(s)
    out.sort()
    return out[: args.max_paires] if args.max_paires else out


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--depuis", default="2023-01-01", help="debut de la periode testee (UTC)")
    p.add_argument("--timeframes", nargs="+", default=["4h", "1d", "1w"], choices=list(TF_MS))
    p.add_argument("--horizons", nargs="+", type=int, default=[4, 24], help="en heures")
    p.add_argument("--paires", nargs="+")
    p.add_argument("--max-paires", type=int)
    p.add_argument("--inclure-retirees", action=argparse.BooleanOptionalAction, default=True,
                   help="inclure les paires suspendues encore listees (BREAK), contre le biais de survie")
    p.add_argument("--rsi", type=int, default=14)
    p.add_argument("--gauche", type=int, default=5)
    p.add_argument("--droite", type=int, default=5)
    p.add_argument("--ecart-min", type=int, default=5)
    p.add_argument("--ecart-max", type=int, default=60)
    p.add_argument("--pivots-sur", choices=["rsi", "prix"], default="rsi")
    p.add_argument("--cost", type=float, default=0.003)
    p.add_argument("--n-random", type=int, default=20)
    p.add_argument("--fenetre-jours", type=float, default=30, help="tirages au hasard dans +- N jours")
    p.add_argument("--bootstrap", type=int, default=2000)
    p.add_argument("--seed", type=int, default=20261027)
    p.add_argument("--cas", action="append", default=[], help="divergence CoinBeacon a retrouver (lien ou parametre div)")
    p.add_argument("--binance-base", default="https://api.binance.com")
    p.add_argument("--cache-dir", type=Path, default=HERE / ".cache")
    p.add_argument("--out-dir", type=Path, default=HERE / "resultats-divergences")
    p.add_argument("--offline", action="store_true")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    http = A.Http(args.offline)
    binance = A.Binance(http, A.Cache(args.cache_dir), args.binance_base, args.offline)
    if not args.offline:
        code = binance.ping()
        if code != 200:
            raise A.Stop(f"Binance : HTTP {code}" + (" (restriction geographique)" if code == 451 else ""), 4)
    now = binance.server_time()
    start = int(dt.datetime.fromisoformat(args.depuis).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    hmax = max(args.horizons)
    warm = max(120 * TF_MS[tf] for tf in args.timeframes)  # chauffe du RSI et des pivots

    cas_lignes = []
    for text in args.cas:
        cas_lignes += verifier_cas(parse_cas(text), binance, now, args)
    for line in cas_lignes:
        A.log(line)

    pairs = universe(binance, args)
    A.log(f"{len(pairs)} paires, unites {', '.join(args.timeframes)}, depuis {args.depuis}")
    rows, absent = [], []
    W = int(args.fenetre_jours * 24)
    for k, sym in enumerate(pairs, 1):
        c = klines_1h(binance, sym, start - warm, now, now)
        if len(c) < 24 * 30:
            absent.append(sym)
            continue
        mes = Mesure(c, args.horizons)
        sigs = []
        for tf in args.timeframes:
            t, o, h, lo, cl = resample(c, tf)
            sigs += [d for d in find_divergences(t, h, lo, cl, tf, args) if d["signal_ms"] >= start]
        if not sigs:
            continue
        idx = np.searchsorted(c.t, [d["signal_ms"] for d in sigs])
        idx = np.where(idx < len(c), idx, len(c) - 1)
        exact = c.t[idx] == np.array([d["signal_ms"] for d in sigs])
        side = np.array([1 if d["dir"] == "bull" else -1 for d in sigs])
        ev = {H: mes.evaluate(np.where(exact, idx, -1), side, H) for H in args.horizons}
        rng = np.random.default_rng([args.seed, A.stable_int(sym)])
        draws = idx[:, None] + rng.integers(-W, W + 1, size=(len(sigs), args.n_random))
        base = {H: np.stack([mes.evaluate(draws[:, j], side, H)[0] for j in range(args.n_random)], axis=1) - args.cost
                for H in args.horizons}
        for n_, d in enumerate(sigs):
            d.update({"paire": sym, "_key": len(rows), "paire_binance": f"{sym}|{d['tf']}",
                      "_det_ms": d["signal_ms"], "_entry_ms": d["signal_ms"], "_side": 1 if d["dir"] == "bull" else -1})
            if not exact[n_]:
                d["statut"] = "exclu : pas de bougie 1 h au signal"
            elif d["signal_ms"] + hmax * HOUR > now:
                d["statut"] = "exclu : horizon non ecoule"
            elif any(np.isnan(ev[H][0, n_]) for H in args.horizons):
                d["statut"] = "exclu : trou dans les bougies"
            else:
                d["statut"] = "inclus"
                for H in args.horizons:
                    d[f"_gross_{H}"], d[f"_up_{H}"], d[f"_down_{H}"] = (float(x) for x in ev[H][:, n_])
                    d[f"_net_{H}"] = d[f"_gross_{H}"] - args.cost
                b = {H: base[H][n_][~np.isnan(base[H][n_])] for H in args.horizons}
                d["_base"] = b if all(len(v) >= args.n_random // 2 for v in b.values()) else None
            rows.append(d)
        if k % 25 == 0 or k == len(pairs):
            A.log(f"  {k}/{len(pairs)} paires, {len(rows)} divergences, {http.calls} requetes")

    inc = [r for r in rows if r["statut"] == "inclus"]
    if not inc:
        raise A.Stop("aucune divergence exploitable", 7)
    for H in args.horizons:
        dup, _ = A.mark_duplicates(inc, H)
        for r in inc:
            r[f"_dup_{H}"] = dup[r["_key"]]
    write_outputs(args, rows, inc, absent, cas_lignes, start, now)
    return 0


def groups(rows, tfs):
    out = []
    for tf in tfs:
        for typ in ("regular", "hidden"):
            for dirn, nom in (("bull", "haussière · achat"), ("bear", "baissière · vente")):
                sub = [r for r in rows if r["tf"] == tf and r["type"] == typ and r["dir"] == dirn]
                if sub:
                    label = "classique" if typ == "regular" else "cachée"
                    out.append((f"{tf} · {label} {nom}", sub))
    return out


def write_outputs(args, rows, inc, absent, cas_lignes, start, now):
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    cols = ["paire", "tf", "type", "dir", "pivot1_utc", "pivot2_utc", "signal_utc", "prix1", "prix2", "rsi1", "rsi2",
            "ecart"]
    for H in args.horizons:
        cols += [f"brut_{H}h_pct", f"net_{H}h_pct", f"hausse_max_{H}h_pct", f"baisse_max_{H}h_pct",
                 f"doublon_{H}h", f"hasard_moy_net_{H}h_pct"]
    cols.append("statut")
    with open(out / "divergences.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in sorted(rows, key=lambda r: (r["signal_ms"], r["paire"])):
            v = {"paire": r["paire"], "tf": r["tf"], "type": r["type"], "dir": r["dir"],
                 "pivot1_utc": A.iso(r["pivot1_ms"]), "pivot2_utc": A.iso(r["pivot2_ms"]),
                 "signal_utc": A.iso(r["signal_ms"]), "prix1": r["prix1"], "prix2": r["prix2"],
                 "rsi1": round(r["rsi1"], 2), "rsi2": round(r["rsi2"], 2), "ecart": r["ecart"], "statut": r["statut"]}
            for H in args.horizons:
                ok = r["statut"] == "inclus"
                f_ = (lambda k: round(r[k] * 100, 4) if ok else "")
                v.update({f"brut_{H}h_pct": f_(f"_gross_{H}"), f"net_{H}h_pct": f_(f"_net_{H}"),
                          f"hausse_max_{H}h_pct": f_(f"_up_{H}"), f"baisse_max_{H}h_pct": f_(f"_down_{H}"),
                          f"doublon_{H}h": int(r[f"_dup_{H}"]) if ok else "",
                          f"hasard_moy_net_{H}h_pct": round(float(r["_base"][H].mean()) * 100, 4)
                          if ok and r.get("_base") else ""})
            w.writerow([v[c] for c in cols])

    first, last = min(r["signal_ms"] for r in inc), max(r["signal_ms"] for r in inc)
    split = first + (last - first) * 2 // 3
    L = ["# Divergences RSI : test historique\n",
         f"Généré le {A.iso(now)} UTC par `coinbeacon/divergences.py`. Binance au comptant, paires USDT, "
         f"signaux du {A.iso(first)[:10]} au {A.iso(last)[:10]}. RSI {args.rsi}, pivots sur le {args.pivots_sur} "
         f"({args.gauche} bougies à gauche, {args.droite} à droite), {args.ecart_min} à {args.ecart_max} bougies entre "
         f"deux pivots. Coût aller-retour {args.cost * 100:.2f} %. Entrée à la confirmation du second pivot. "
         f"Hasard : {args.n_random} entrées sur la même paire dans ±{args.fenetre_jours:g} jours, même sens. "
         f"{args.bootstrap} rééchantillonnages, graine {args.seed}.\n"]
    if cas_lignes:
        L.append("## Comparaison avec le détecteur CoinBeacon\n")
        L += [f"- {x}" for x in cas_lignes]
        L.append("")
    L.append("## Entonnoir\n")
    L.append("| Statut | Divergences |\n|---|---:|")
    for st, n in Counter(r["statut"] for r in rows).most_common():
        L.append(f"| {st} | {n} |")
    if absent:
        L.append(f"\n{len(absent)} paires sans assez d'historique.")
    L.append("")
    n_tests = 0
    summary = {}
    for H in args.horizons:
        L.append(f"## Horizon {H} h, net de frais, sans doublons\n")
        sans = [r for r in inc if not r[f"_dup_{H}"]]
        stats, cmp_rows = [], []
        for name, sub in groups(sans, args.timeframes):
            s = A.describe(sub, H, args.cost, args.seed, name, args.bootstrap, with_day_ci=True)
            stats.append(s)
            c = A.compare_to_random(sub, H, args.seed, args.bootstrap)
            n_tests += 1
            old = [r[f"_net_{H}"] for r in sub if r["signal_ms"] < split]
            new = [r[f"_net_{H}"] for r in sub if r["signal_ms"] >= split]
            cmp_rows.append((name, c, old, new, float(np.mean([r[f"_gross_{H}"] for r in sub]))))
            summary[f"{H}h|{name}"] = {"n": s["n"], "moyenne": s.get("moyenne"), "ic_jours": s.get("ic_jours"),
                                       "ecart_hasard": c["ecart_moyen"] if c else None,
                                       "ic_ecart": c["ic_ecart"] if c else None}
        L.append(A.stats_table(stats))
        L.append("")
        L.append("| Groupe | Écart moyen avec le hasard [IC 95 %] | p Wilcoxon | Moy. 2/3 anciens | Moy. 1/3 récent | "
                 "Coût qui annule la moyenne |")
        L.append("|---|---|---:|---:|---:|---:|")
        for name, c, old, new, gm in cmp_rows:
            ec = "n/d" if not c else f"{A.pct(c['ecart_moyen'])} [{A.pct(c['ic_ecart'][0])} ; {A.pct(c['ic_ecart'][1])}]"
            L.append(f"| {name} | {ec} | {A.pval(c['wilcoxon_p']) if c else 'n/d'} | "
                     f"{A.pct(float(np.mean(old))) if old else 'n/d'} ({len(old)}) | "
                     f"{A.pct(float(np.mean(new))) if new else 'n/d'} ({len(new)}) | "
                     f"{'négative sans frais' if gm <= 0 else f'{gm * 100:.2f} %'.replace('.', ',')} |")
        L.append("")
    L.append("## Lecture\n")
    L += [
        f"- **{n_tests} groupes testés** : au seuil de 5 %, on attend environ {max(1, round(n_tests * 0.05))} "
        "faux positif(s) par pur hasard. Un groupe ne compte que si l'intervalle par jour exclut zéro, s'il bat le hasard "
        "sur la même paire, et si son signe tient sur le tiers le plus récent de la période.",
        "- Les divergences d'un même jour sur de nombreuses paires suivent le même mouvement du marché : "
        "l'intervalle « par jour » est la référence, l'autre est trop étroit.",
        "- Ventes : positions courtes théoriques, impossibles au comptant ; financement d'un perpétuel non compté.",
        "- Paires retirées de Binance : seules celles encore listées (statut BREAK) sont incluses ; les autres manquent, "
        "ce qui favorise les survivantes." if args.inclure_retirees else
        "- Paires retirées de Binance exclues : biais de survie en faveur des paires encore cotées.",
        "- La définition reprend TradingView. Tant que le cas CoinBeacon n'est pas retrouvé à l'identique, "
        "ce test porte sur des divergences proches de celles de CoinBeacon, pas forcément identiques.",
    ]
    (out / "rapport.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (out / "resume.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    A.log(f"Termine : {len(inc)} divergences analysees sur {len(rows)}. Sorties dans {out}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except A.Stop as e:
        A.log(f"ARRET : {e}")
        sys.exit(e.code)
