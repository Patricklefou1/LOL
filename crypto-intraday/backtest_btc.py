#!/usr/bin/env python3
"""
Backtest de deux effets intrajournaliers sur le BTC, combines aux chiffres ronds.

Option A, fenetre des ETF : signal entre 9h30 et 10h00 New York, position entre
15h00 et 16h00 New York, fenetre du taux de reference des ETF au comptant. Jours
ouvres seulement.

Option B, jour UTC : signal entre 00h00 et 00h30 UTC, position entre 23h30 et
00h00 UTC. Tous les jours.

Donnees : bougies d'une minute Binance, data.binance.vision, mises en cache.

Usage :
  python3 backtest_btc.py telecharger --debut 2018-01 --fin 2026-09
  python3 backtest_btc.py tester
  python3 backtest_btc.py tester --option A --frais 0.0002
  python3 backtest_btc.py tester --option B --export trades_b.csv

Les parametres par defaut sont ceux du pre-enregistrement du README. Les changer
apres avoir vu les resultats, c'est chercher jusqu'a trouver.
"""

import argparse
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ICI = Path(__file__).resolve().parent
CACHE_DEFAUT = ICI / "donnees"
URL = "https://data.binance.vision/data/spot/monthly/klines/{s}/1m/{s}-1m-{m}.zip"
DATE_ETF = pd.Timestamp("2024-01-11")
MINUTE_NS = 60 * 10**9

OPTIONS = {
    "A": {
        "nom": "fenetre des ETF",
        "fuseau": "America/New_York",
        "signal": ("09:30", "10:00"),
        "position": ("15:00", "16:00"),
        "jours_ouvres": True,
    },
    "B": {
        "nom": "jour UTC",
        "fuseau": "UTC",
        "signal": ("00:00", "00:30"),
        "position": ("23:30", "24:00"),
        "jours_ouvres": False,
    },
}


# ---------------------------------------------------------------- donnees

def mois_entre(debut, fin):
    return [p.strftime("%Y-%m") for p in pd.period_range(debut, fin, freq="M")]


def lire_zip(chemin):
    with zipfile.ZipFile(chemin) as z:
        with z.open(z.namelist()[0]) as f:
            brut = pd.read_csv(f, header=None, usecols=range(5),
                               names=["t", "open", "high", "low", "close"])
    # certains fichiers ont une ligne d'en-tete : elle devient NaN et saute
    brut = brut.apply(pd.to_numeric, errors="coerce").dropna()
    t = brut["t"].astype("int64").to_numpy()
    # depuis janvier 2025, Binance publie le spot en microsecondes
    t = np.where(t > 10**14, t // 1000, t)
    brut.index = pd.to_datetime(t, unit="ms", utc=True)
    return brut[["open", "high", "low", "close"]].astype("float64")


def construire_cache(cache, symbole):
    zips = sorted((cache / "zip").glob(f"{symbole}-1m-*.zip"))
    if not zips:
        sys.exit("Aucun fichier telecharge.")
    df = pd.concat([lire_zip(z) for z in zips]).sort_index()
    df = df[~df.index.duplicated(keep="first")]
    sortie = cache / f"{symbole}_1m.pkl"
    df.to_pickle(sortie)
    print(f"{len(df):,} bougies, {df.index[0]} -> {df.index[-1]}, dans {sortie}")


def telecharger(args):
    cache = Path(args.cache)
    (cache / "zip").mkdir(parents=True, exist_ok=True)
    for m in mois_entre(args.debut, args.fin):
        cible = cache / "zip" / f"{args.symbole}-1m-{m}.zip"
        if cible.exists():
            continue
        try:
            with urllib.request.urlopen(URL.format(s=args.symbole, m=m), timeout=120) as r:
                contenu = r.read()
        except urllib.error.HTTPError as e:
            print(f"{m} : absent ({e.code})", file=sys.stderr)
            continue
        except urllib.error.URLError as e:
            sys.exit(f"{m} : data.binance.vision injoignable ({e.reason})")
        cible.write_bytes(contenu)
        print(f"{m} : ok")
    construire_cache(cache, args.symbole)


def charger(cache, symbole):
    chemin = Path(cache) / f"{symbole}_1m.pkl"
    if not chemin.exists():
        sys.exit(f"{chemin} introuvable : lancer d'abord la commande telecharger.")
    return pd.read_pickle(chemin)


# ---------------------------------------------------------------- calendrier

def instants(jours, heure, fuseau):
    h, m = (int(x) for x in heure.split(":"))
    locaux = jours + pd.Timedelta(hours=h, minutes=m)
    return locaux.tz_localize(fuseau).tz_convert("UTC")


def fenetres(cfg, debut, fin):
    """Une ligne par jour : les quatre instants utiles, en UTC."""
    jours = pd.date_range(debut.normalize(), fin.normalize(), freq="D")
    if cfg["jours_ouvres"]:
        # les jours feries americains restent dedans : une dizaine par an, sans flux d'ETF
        jours = jours[jours.dayofweek < 5]
    f = cfg["fuseau"]
    return pd.DataFrame({
        "jour": jours,
        "sig0": instants(jours, cfg["signal"][0], f),
        "sig1": instants(jours, cfg["signal"][1], f),
        "entree": instants(jours, cfg["position"][0], f),
        "sortie": instants(jours, cfg["position"][1], f),
    })


# ---------------------------------------------------------------- marche

class Marche:
    def __init__(self, df, tolerance_min):
        self.t = df.index.as_unit("ns").asi8
        self.h = df["high"].to_numpy()
        self.l = df["low"].to_numpy()
        self.c = df["close"].to_numpy()
        self.tol = (tolerance_min + 1) * MINUTE_NS

    def prix(self, quand):
        """Prix juste avant l'instant : cloture de la derniere bougie commencee avant.
        NaN si cette bougie est trop ancienne (trou dans les donnees)."""
        q = pd.DatetimeIndex(quand).as_unit("ns").asi8
        i = np.searchsorted(self.t, q, side="left") - 1
        ok = (i >= 0) & (q - self.t[np.maximum(i, 0)] <= self.tol)
        return np.where(ok, self.c[np.maximum(i, 0)], np.nan)

    def extremes(self, debut, fin):
        """Plus haut et plus bas des bougies commencees dans [debut, fin)."""
        a = np.searchsorted(self.t, debut, side="left")
        b = np.searchsorted(self.t, fin, side="left")
        if b <= a:
            return np.nan, np.nan
        return self.h[a:b].max(), self.l[a:b].min()


def tendance_h4(df, periodes):
    """Pour chaque bougie H4 alignee UTC : instant de fin, et signe de la cloture
    par rapport a sa moyenne mobile sur `periodes` bougies H4."""
    h4 = df["close"].resample("4h").last()
    sma = h4.rolling(periodes, min_periods=periodes).mean()
    signe = np.sign(h4 - sma).to_numpy()
    fin = (h4.index + pd.Timedelta(hours=4)).as_unit("ns").asi8
    return fin, signe


# ---------------------------------------------------------------- simulation

def niveau_devant(p, d, pas):
    """Premier chiffre rond strictement devant le prix, dans le sens d."""
    if d > 0:
        return (np.floor(p / pas) + 1) * pas
    return (np.ceil(p / pas) - 1) * pas


def simuler(df, cfg, sens, a):
    marche = Marche(df, a.tolerance)
    fen = fenetres(cfg, df.index[0].tz_convert(None), df.index[-1].tz_convert(None))
    p0 = marche.prix(fen["sig0"])
    p1 = marche.prix(fen["sig1"])
    pe = marche.prix(fen["entree"])
    px = marche.prix(fen["sortie"])
    fin_h4, signe_h4 = tendance_h4(df, a.sma_h4)

    lignes = []
    for k in range(len(fen)):
        if np.isnan([p0[k], p1[k], pe[k], px[k]]).any():
            continue
        signal = p1[k] / p0[k] - 1
        if signal == 0:
            continue
        d = np.sign(signal) if sens == "momentum" else -np.sign(signal)
        e = fen["entree"].iloc[k].value
        x = fen["sortie"].iloc[k].value

        mouvement = px[k] / pe[k] - 1

        # chiffres ronds a l'entree
        devant = niveau_devant(pe[k], d, a.pas_rond)
        obstacle = abs(devant - pe[k]) / pe[k] <= a.proche
        haut_av, bas_av = marche.extremes(e - a.recul * MINUTE_NS, e)
        if d > 0:
            franchi = np.floor(pe[k] / a.pas_rond) > np.floor(bas_av / a.pas_rond)
        else:
            franchi = np.ceil(pe[k] / a.pas_rond) < np.ceil(haut_av / a.pas_rond)
        categorie = "obstacle" if obstacle else ("franchi" if franchi else "neutre")

        # objectif juste avant le prochain chiffre rond, s'il est atteint dans la fenetre
        objectif = devant * (1 - d * a.marge_objectif)
        if (objectif - pe[k]) * d <= 0:
            objectif += d * a.pas_rond
        haut, bas = marche.extremes(e, x)
        atteint = (haut >= objectif) if d > 0 else (bas <= objectif)
        avec_objectif = d * (objectif / pe[k] - 1) if atteint else d * mouvement

        # tendance H4 : derniere bougie H4 terminee avant l'entree
        j = np.searchsorted(fin_h4, e, side="right") - 1
        tendance = signe_h4[j] if j >= 0 else np.nan

        lignes.append({
            "jour": fen["jour"].iloc[k].date(),
            "annee": fen["jour"].iloc[k].year,
            "apres_etf": fen["jour"].iloc[k] >= DATE_ETF,
            "signal": signal,
            "direction": int(d),
            "prix_entree": pe[k],
            "mouvement": mouvement,
            "brut": d * mouvement,
            "brut_objectif": avec_objectif,
            "objectif_atteint": bool(atteint),
            "categorie": categorie,
            "dans_tendance": tendance == d,
        })
    return pd.DataFrame(lignes)


# ---------------------------------------------------------------- statistiques

def pval_signe(mouvement, direction, n_perm, rng):
    """Part des directions tirees au hasard qui font au moins aussi bien."""
    m = np.asarray(mouvement)
    if len(m) == 0:
        return np.nan
    observe = np.mean(np.asarray(direction) * m)
    signes = rng.choice([-1.0, 1.0], size=(n_perm, len(m)))
    return float(((signes @ m) / len(m) >= observe).mean())


def resume(tr, colonne, frais, rng, n_perm, perm=True):
    if tr.empty:
        return None
    brut = tr[colonne].to_numpy()
    net = np.sort(brut - 2 * frais)[::-1]
    sans = lambda k: net[k:].mean() * 1e4 if len(net) > k else np.nan
    return {
        "jours": len(tr),
        "brut pb": brut.mean() * 1e4,
        "net pb": net.mean() * 1e4,
        "mediane nette pb": np.median(net) * 1e4,
        "gagnants": (net > 0).mean() * 100,
        "sans top 3": sans(3),
        "sans top 10": sans(10),
        "p hasard": pval_signe(tr["mouvement"], tr["direction"], n_perm, rng) if perm else np.nan,
    }


def tableau(lignes, titre_ligne):
    lignes = [(nom, r) for nom, r in lignes if r is not None]
    if not lignes:
        print("_aucun jour_\n")
        return
    cols = list(lignes[0][1])
    print(f"| {titre_ligne} | " + " | ".join(cols) + " |")
    print("|---" * (len(cols) + 1) + "|")
    for nom, r in lignes:
        cellules = []
        for c in cols:
            v = r[c]
            if c == "jours":
                cellules.append(f"{v:,}".replace(",", " "))
            elif c == "gagnants":
                cellules.append(f"{v:.1f} %")
            elif c == "p hasard":
                cellules.append("—" if np.isnan(v) else f"{v:.3f}")
            else:
                cellules.append("—" if np.isnan(v) else f"{v:+.1f}")
        print(f"| {nom} | " + " | ".join(cellules) + " |")
    print()


def rapport(tr, sens, option, a, rng):
    f, n = a.frais, a.permutations
    print(f"## Sens : {sens}\n")
    if tr.empty:
        print("_aucun jour exploitable_\n")
        return

    print("### Variantes\n")
    cat = tr["categorie"]
    tableau([
        ("base", resume(tr, "brut", f, rng, n)),
        ("tendance H4", resume(tr[tr["dans_tendance"]], "brut", f, rng, n)),
        ("sans obstacle", resume(tr[cat != "obstacle"], "brut", f, rng, n)),
        ("tendance H4 + sans obstacle",
         resume(tr[tr["dans_tendance"] & (cat != "obstacle")], "brut", f, rng, n)),
        ("objectif avant le rond", resume(tr, "brut_objectif", f, rng, n, perm=False)),
    ], "variante")

    print("### Par categorie de chiffre rond\n")
    tableau([(c, resume(tr[cat == c], "brut", f, rng, n))
             for c in ("obstacle", "franchi", "neutre")], "categorie")

    print("### Par annee, variante de base\n")
    tableau([(str(an), resume(g, "brut", f, rng, n))
             for an, g in tr.groupby("annee")], "annee")

    if option == "A":
        print("### Avant et apres les ETF au comptant (11 janvier 2024)\n")
        print("Si l'effet vient des ETF, il doit apparaitre apres et pas avant.\n")
        tableau([("avant", resume(tr[~tr["apres_etf"]], "brut", f, rng, n)),
                 ("apres", resume(tr[tr["apres_etf"]], "brut", f, rng, n))], "periode")

    print("### Selon la taille du signal, en terciles\n")
    taille = pd.qcut(tr["signal"].abs(), 3, labels=["petit", "moyen", "grand"])
    tableau([(str(t), resume(tr[taille == t], "brut", f, rng, n))
             for t in ("petit", "moyen", "grand")], "signal")

    print("### Sensibilite aux frais, variante de base\n")
    tableau([(f"{x * 1e4:g} pb par cote", resume(tr, "brut", x, rng, n, perm=False))
             for x in (0, 0.0002, 0.0005, 0.001)], "frais")


def tester(args):
    df = charger(args.cache, args.symbole)
    if args.depuis:
        df = df[df.index >= pd.Timestamp(args.depuis, tz="UTC")]
    if args.jusqua:
        df = df[df.index < pd.Timestamp(args.jusqua, tz="UTC")]
    rng = np.random.default_rng(args.graine)
    options = ["A", "B"] if args.option == "les-deux" else [args.option]
    sens = ["momentum", "retournement"] if args.sens == "les-deux" else [args.sens]

    print(f"# Backtest {args.symbole}, {df.index[0].date()} -> {df.index[-1].date()}\n")
    print(f"Frais : {args.frais * 1e4:g} pb par cote. Rond : multiples de {args.pas_rond:g}, "
          f"obstacle a moins de {args.proche * 100:g} %, franchi sur {args.recul} min. "
          f"Tendance : cloture H4 contre sa moyenne {args.sma_h4} periodes.\n")
    print("pb = point de base, 0,01 %. « p hasard » = part de directions aleatoires "
          "qui font au moins aussi bien, sur les memes jours.\n")

    exports = []
    for o in options:
        cfg = OPTIONS[o]
        print(f"# Option {o} : {cfg['nom']} — signal {'-'.join(cfg['signal'])}, "
              f"position {'-'.join(cfg['position'])}, {cfg['fuseau']}\n")
        for s in sens:
            tr = simuler(df, cfg, s, args)
            rapport(tr, s, o, args, rng)
            exports.append(tr.assign(option=o, sens=s))
        if not exports[-1].empty:
            m = exports[-1]["mouvement"]
            print(f"Reference : toujours long sur la meme fenetre, {m.mean() * 1e4:+.1f} pb brut, "
                  f"{(m.mean() - 2 * args.frais) * 1e4:+.1f} pb net, sur {len(m)} jours.\n")

    if args.export:
        pd.concat(exports).to_csv(args.export, index=False)
        print(f"Trades exportes dans {args.export}")


# ---------------------------------------------------------------- ligne de commande

def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--cache", default=str(CACHE_DEFAUT))
    p.add_argument("--symbole", default="BTCUSDT")
    sp = p.add_subparsers(dest="commande", required=True)

    t = sp.add_parser("telecharger", help="recuperer les bougies 1 min de Binance")
    t.add_argument("--debut", default="2018-01")
    t.add_argument("--fin", default=(pd.Timestamp.now() - pd.DateOffset(months=1)).strftime("%Y-%m"))

    b = sp.add_parser("tester", help="lancer le backtest")
    b.add_argument("--option", choices=["A", "B", "les-deux"], default="les-deux")
    b.add_argument("--sens", choices=["momentum", "retournement", "les-deux"], default="les-deux")
    b.add_argument("--frais", type=float, default=0.0005, help="par cote, 0.0005 = 0,05 %%")
    b.add_argument("--pas-rond", type=float, default=1000.0)
    b.add_argument("--proche", type=float, default=0.002, help="distance d'un obstacle, 0.002 = 0,2 %%")
    b.add_argument("--recul", type=int, default=60, help="minutes pour juger un rond franchi")
    b.add_argument("--marge-objectif", type=float, default=0.0005, help="objectif place avant le rond")
    b.add_argument("--sma-h4", type=int, default=50)
    b.add_argument("--tolerance", type=int, default=5, help="minutes de trou acceptees")
    b.add_argument("--permutations", type=int, default=2000)
    b.add_argument("--graine", type=int, default=0)
    b.add_argument("--depuis", help="AAAA-MM-JJ")
    b.add_argument("--jusqua", help="AAAA-MM-JJ, exclu")
    b.add_argument("--export", help="fichier CSV des trades")

    args = p.parse_args()
    {"telecharger": telecharger, "tester": tester}[args.commande](args)


if __name__ == "__main__":
    main()
