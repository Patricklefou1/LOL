#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
figures_chartistes.py — Quelles figures chartistes haussières sont les plus
représentées parmi les tokens GRADUÉS sur Pump.fun ?

Fenêtres analysées (UTC) :
  - mode « jours »  (défaut) : cohortes d'un jour — hier (J-1), il y a 7 jours
    (J-7), il y a 30 jours (J-30) ;
  - mode « cumule »           : fenêtres glissantes — derniers 1 / 7 / 30 jours.

Sources de données (option --source) :
  clickhouse   : la base de capture du dépôt (tables `completions` et `trades`,
                 voir capture/sql/001_schema.sql). Zéro biais du survivant,
                 aucune clé requise. Bougies = phase bonding curve (le chart
                 qui a MENÉ à la graduation). C'est la source recommandée.
  moralis      : API Moralis (clé MORALIS_API_KEY requise) — liste des gradués
                 avec `graduatedAt`, bougies via la paire post-graduation.
  pumpfun      : API frontend publique de Pump.fun, sans clé. Best-effort :
                 ces endpoints ne sont pas documentés officiellement et
                 évoluent (certains exigent désormais un JWT). La cohorte est
                 approchée par jour de création (l'horodatage de graduation
                 n'est pas exposé).
  Bougies interchangeables via --bougies (dont geckoterminal, sans clé,
  post-graduation uniquement).

Aucune dépendance externe : Python 3.9+ standard uniquement.

Exemples :
  # Sur le VPS de capture (recommandé) :
  python3 figures_chartistes.py --source clickhouse

  # Avec une clé Moralis :
  MORALIS_API_KEY=... python3 figures_chartistes.py --source moralis

  # Rejouer une date passée, fenêtres glissantes, sorties fichiers :
  python3 figures_chartistes.py --mode cumule --date-ref 2026-08-14 \
      --markdown resultats.md --json resultats.json

  # Vérifier les détecteurs sans réseau :
  python3 figures_chartistes.py --autotest
"""

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import namedtuple

# ---------------------------------------------------------------------------
# Paramètres de détection (relatifs : adaptés à la volatilité memecoin)
# ---------------------------------------------------------------------------

SEUIL_ZIGZAG_MIN = 0.05      # renversement minimal d'un pivot ZigZag (5 %)
SEUIL_ZIGZAG_MAX = 0.25      # plafond du seuil adaptatif (25 %)
SEUIL_ZIGZAG_K = 3.5         # seuil = K × amplitude médiane des bougies
MIN_BOUGIES = 20             # série plus courte = « bougies insuffisantes »
MIN_PIVOTS = 4               # pivots minimum pour chercher des figures
HORIZON_CASSURE = 40         # barres max entre fin de figure et cassure
TOL_RESISTANCE = 0.06        # « plat » : sommets dans une bande de 6 %
TOL_CREUX_DOUBLE = 0.06      # deux creux « égaux » à 6 % près
PROF_MIN_DOUBLE = 0.08       # pic intermédiaire ≥ 8 % au-dessus des creux
TOL_EPAULES = 0.12           # épaules d'une ETEi égales à 12 % près
PROF_TETE = 0.05             # la tête sous les épaules d'au moins 5 %
POLE_BARS_MAX = 20           # largeur max du mât d'un drapeau/fanion
POLE_MIN_PLANCHER = 0.30     # hausse minimale du mât (30 %)
CONSOL_MIN = 3               # barres minimum de consolidation
RETRACE_MAX_DRAPEAU = 0.5    # retracement max de la consolidation (50 % du mât)
TASSE_PROF_MIN = 0.12        # profondeur de tasse : 12 %…
TASSE_PROF_MAX = 0.65        # …à 65 % sous le bord
TASSE_LARG_MIN = 10          # largeur minimale de la tasse (barres)
TASSE_R2_MIN = 0.55          # qualité minimale de l'ajustement parabolique
CHUTE_V_MIN = 0.25           # chute minimale d'un creux en V (25 %)
LARGEUR_V_MAX = 12           # barres max pour la chute et pour la reprise
REPRISE_V = 0.80             # la reprise doit regagner 80 % de la chute
TROU_MAX_MIN = 120           # minutes sans trade tolérées (comblées à plat)
RESAMPLE_AU_DELA = 700       # au-delà de N bougies 1 min → bougies 5 min

FIGURES = [
    # (code, nom affiché, famille)
    ("canal_ascendant", "Canal ascendant (plus hauts / plus bas croissants)", "continuation"),
    ("drapeau_haussier", "Drapeau haussier (bull flag)", "continuation"),
    ("fanion_haussier", "Fanion haussier (bullish pennant)", "continuation"),
    ("triangle_ascendant", "Triangle ascendant", "continuation"),
    ("rectangle_haussier", "Rectangle haussier (range + cassure haute)", "continuation"),
    ("biseau_descendant", "Biseau descendant (falling wedge)", "renversement"),
    ("double_creux", "Double creux (double bottom, « W »)", "renversement"),
    ("triple_creux", "Triple creux (triple bottom)", "renversement"),
    ("ete_inversee", "Épaule-tête-épaule inversée (ETEi)", "renversement"),
    ("tasse_anse", "Tasse avec anse (cup & handle)", "continuation"),
    ("fond_arrondi", "Fond arrondi (soucoupe)", "renversement"),
    ("creux_en_v", "Creux en V (V-bottom)", "renversement"),
]
NOMS = {code: nom for code, nom, _ in FIGURES}

Bougie = namedtuple("Bougie", "t o h l c v")
Pivot = namedtuple("Pivot", "i p typ")  # index, prix, 'H' ou 'L'

BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{25,50}$")


# ---------------------------------------------------------------------------
# HTTP minimal (respecte HTTPS_PROXY et le magasin de CA du système)
# ---------------------------------------------------------------------------

def http_json(url, entetes=None, essais=3, patience=1.5, timeout=30):
    """GET → JSON, avec ré-essais sur 429/5xx et messages d'erreur en clair."""
    entetes = dict(entetes or {})
    entetes.setdefault("Accept", "application/json")
    entetes.setdefault("User-Agent", "figures-chartistes/1.0 (+repo LOL)")
    derniere = None
    for tentative in range(essais):
        try:
            req = urllib.request.Request(url, headers=entetes)
            with urllib.request.urlopen(req, timeout=timeout) as rep:
                return json.loads(rep.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            derniere = f"HTTP {e.code} sur {url}"
            if e.code == 429:
                time.sleep(max(patience * (2 ** tentative), 30))
                continue
            if e.code in (403, 407):
                raise RuntimeError(
                    f"{derniere} — accès refusé (politique réseau ou "
                    f"authentification requise). Ne pas ré-essayer en boucle."
                )
            if 500 <= e.code < 600 and tentative + 1 < essais:
                time.sleep(patience * (2 ** tentative))
                continue
            raise RuntimeError(derniere)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            derniere = f"réseau indisponible sur {url} ({e})"
            if tentative + 1 < essais:
                time.sleep(patience * (2 ** tentative))
                continue
            raise RuntimeError(derniere)
    raise RuntimeError(derniere or f"échec sur {url}")


# ---------------------------------------------------------------------------
# Source ClickHouse (la base de capture du dépôt)
# ---------------------------------------------------------------------------

class ClickHouse:
    def __init__(self):
        self.url = os.environ.get("CLICKHOUSE_URL", "http://localhost:8123")
        self.user = os.environ.get("CLICKHOUSE_USER", "default")
        self.mdp = os.environ.get("CLICKHOUSE_PASSWORD", "")
        self.db = os.environ.get("CLICKHOUSE_DATABASE", "pumpfun")

    def requete(self, sql, timeout=120):
        url = self.url.rstrip("/") + "/?" + urllib.parse.urlencode(
            {"default_format": "JSON", "database": self.db}
        )
        req = urllib.request.Request(
            url,
            data=sql.encode("utf-8"),
            headers={
                "X-ClickHouse-User": self.user,
                "X-ClickHouse-Key": self.mdp,
                "Content-Type": "text/plain; charset=utf-8",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as rep:
                return json.loads(rep.read().decode("utf-8")).get("data", [])
        except urllib.error.HTTPError as e:
            corps = e.read().decode("utf-8", "replace")[:400]
            raise RuntimeError(f"ClickHouse HTTP {e.code} : {corps}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise RuntimeError(
                f"ClickHouse injoignable sur {self.url} ({e}). "
                f"Lancer sur la machine de capture ou exporter CLICKHOUSE_URL."
            )

    def joignable(self):
        try:
            self.requete("SELECT 1 AS x", timeout=5)
            return True
        except Exception:
            return False

    def gradues(self, t0, t1):
        sql = (
            "SELECT mint, toUnixTimestamp(min(received_at)) AS g "
            f"FROM completions "
            f"WHERE received_at >= toDateTime64('{t0:%Y-%m-%d %H:%M:%S}', 3, 'UTC') "
            f"AND received_at < toDateTime64('{t1:%Y-%m-%d %H:%M:%S}', 3, 'UTC') "
            "GROUP BY mint"
        )
        return [(r["mint"], int(float(r["g"]))) for r in self.requete(sql)]

    def bougies(self, mints):
        """Bougies 1 min de la phase bonding curve, pour un lot de mints."""
        res = {m: [] for m in mints}
        for lot in _lots(mints, 50):
            for m in lot:
                if not BASE58.match(m):
                    raise ValueError(f"mint invalide : {m!r}")
            liste = ", ".join(f"'{m}'" for m in lot)
            sql = (
                "SELECT mint, toUnixTimestamp(toStartOfMinute(received_at)) AS t, "
                "argMin(price_sol, (slot, signature)) AS o, max(price_sol) AS h, "
                "min(price_sol) AS l, argMax(price_sol, (slot, signature)) AS c, "
                "sum(sol_amount) / 1e9 AS v "
                f"FROM trades WHERE mint IN ({liste}) AND price_sol > 0 "
                "GROUP BY mint, t ORDER BY mint, t"
            )
            for r in self.requete(sql):
                res[r["mint"]].append(Bougie(
                    int(float(r["t"])), float(r["o"]), float(r["h"]),
                    float(r["l"]), float(r["c"]), float(r["v"]),
                ))
        return res


# ---------------------------------------------------------------------------
# Source Moralis (clé requise) — gradués avec graduatedAt + OHLCV de paire
# ---------------------------------------------------------------------------

class Moralis:
    BASE = "https://solana-gateway.moralis.io"

    def __init__(self, cle):
        if not cle:
            raise RuntimeError(
                "MORALIS_API_KEY manquante (source moralis). "
                "Exporter la clé ou choisir --source clickhouse."
            )
        self.entetes = {"X-API-Key": cle}

    def gradues(self, t0, t1, max_pages=800):
        """Parcourt la liste des gradués (triée du plus récent au plus ancien)."""
        u0, u1 = t0.timestamp(), t1.timestamp()
        sortie, curseur = [], None
        for _ in range(max_pages):
            params = {"limit": "100"}
            if curseur:
                params["cursor"] = curseur
            url = (f"{self.BASE}/token/mainnet/exchange/pumpfun/graduated?"
                   + urllib.parse.urlencode(params))
            page = http_json(url, self.entetes)
            lignes = page.get("result") or []
            if not lignes:
                break
            plus_ancien = None
            for r in lignes:
                quand = _iso_vers_unix(r.get("graduatedAt") or r.get("graduated_at"))
                mint = r.get("tokenAddress") or r.get("mint") or r.get("address")
                if quand is None or not mint:
                    continue
                plus_ancien = quand if plus_ancien is None else min(plus_ancien, quand)
                if u0 <= quand < u1:
                    sortie.append((mint, int(quand)))
            curseur = page.get("cursor")
            if not curseur or (plus_ancien is not None and plus_ancien < u0):
                break
            time.sleep(0.35)
        return sortie

    def _paire_post(self, mint):
        url = f"{self.BASE}/token/mainnet/{mint}/pairs"
        rep = http_json(url, self.entetes)
        paires = rep.get("pairs") or rep.get("result") or []
        for p in paires:
            nom = (p.get("exchangeName") or "").lower().replace(" ", "")
            if "pumpswap" in nom or "raydium" in nom:
                return p.get("pairAddress")
        return paires[0].get("pairAddress") if paires else None

    def bougies(self, mint, t0, t1, timeframe="1min", max_pages=6):
        paire = self._paire_post(mint)
        if not paire:
            return []
        sortie, curseur = [], None
        for _ in range(max_pages):
            params = {
                "timeframe": timeframe, "currency": "usd", "limit": "1000",
                "fromDate": dt.datetime.fromtimestamp(t0, dt.timezone.utc).isoformat(),
                "toDate": dt.datetime.fromtimestamp(t1, dt.timezone.utc).isoformat(),
            }
            if curseur:
                params["cursor"] = curseur
            url = (f"{self.BASE}/token/mainnet/pairs/{paire}/ohlcv?"
                   + urllib.parse.urlencode(params))
            page = http_json(url, self.entetes)
            for r in page.get("result") or []:
                quand = _iso_vers_unix(r.get("timestamp"))
                if quand is None:
                    continue
                try:
                    sortie.append(Bougie(
                        int(quand), float(r["open"]), float(r["high"]),
                        float(r["low"]), float(r["close"]),
                        float(r.get("volume") or 0),
                    ))
                except (KeyError, TypeError, ValueError):
                    continue
            curseur = page.get("cursor")
            if not curseur:
                break
            time.sleep(0.35)
        sortie.sort(key=lambda b: b.t)
        return _dedoublonne(sortie)


# ---------------------------------------------------------------------------
# Source GeckoTerminal (sans clé) — bougies post-graduation uniquement
# ---------------------------------------------------------------------------

class GeckoTerminal:
    BASE = "https://api.geckoterminal.com/api/v2"
    PAUSE = 2.2  # ~27 requêtes/min, sous la limite publique de 30/min

    def _get(self, chemin):
        time.sleep(self.PAUSE)
        return http_json(self.BASE + chemin, essais=4, patience=20)

    def _pool(self, mint):
        rep = self._get(f"/networks/solana/tokens/{mint}/pools?page=1")
        donnees = rep.get("data") or []
        return donnees[0]["attributes"]["address"] if donnees else None

    def bougies(self, mint, t0, t1, aggreger=1):
        pool = self._pool(mint)
        if not pool:
            return []
        sortie, avant = [], int(t1)
        for _ in range(4):
            chemin = (f"/networks/solana/pools/{pool}/ohlcv/minute"
                      f"?aggregate={aggreger}&limit=1000&currency=usd"
                      f"&token={mint}&before_timestamp={avant}")
            rep = self._get(chemin)
            lignes = (rep.get("data") or {}).get("attributes", {}).get("ohlcv_list") or []
            if not lignes:
                break
            for t, o, h, l, c, v in lignes:
                if t0 <= t < t1:
                    sortie.append(Bougie(int(t), float(o), float(h),
                                         float(l), float(c), float(v or 0)))
            plus_ancien = min(int(x[0]) for x in lignes)
            if plus_ancien <= t0 or len(lignes) < 2:
                break
            avant = plus_ancien
        sortie.sort(key=lambda b: b.t)
        return _dedoublonne(sortie)


# ---------------------------------------------------------------------------
# Source pump.fun frontend (best-effort, sans clé, endpoints non garantis)
# ---------------------------------------------------------------------------

class PumpFun:
    BASE = "https://frontend-api-v3.pump.fun"

    def gradues(self, t0, t1, max_pages=400):
        """Approximation : coins `complete=true` dont la CRÉATION tombe dans la
        fenêtre (l'API publique n'expose pas l'horodatage de graduation).
        La grande majorité des gradués migrent le jour de leur création."""
        u0 = (t0 - dt.timedelta(days=2)).timestamp()  # marge : créés avant, gradués dans la fenêtre
        sortie = []
        for page in range(max_pages):
            url = (f"{self.BASE}/coins?offset={page * 50}&limit=50"
                   "&sort=created_timestamp&order=DESC&includeNsfw=true&complete=true")
            lignes = http_json(url)
            if isinstance(lignes, dict):
                lignes = lignes.get("coins") or lignes.get("result") or []
            if not lignes:
                break
            arret = False
            for r in lignes:
                mint = r.get("mint")
                cree = r.get("created_timestamp")
                if mint is None or cree is None:
                    continue
                cree = float(cree) / (1000.0 if float(cree) > 1e12 else 1.0)
                if cree < u0:
                    arret = True
                    break
                if t0.timestamp() <= cree < t1.timestamp():
                    sortie.append((mint, int(cree)))
            if arret:
                break
            time.sleep(0.3)
        return sortie

    def bougies(self, mint, timeframe_min=1, limite=2000):
        url = (f"{self.BASE}/candlesticks/{mint}"
               f"?offset=0&limit={limite}&timeframe={timeframe_min}")
        lignes = http_json(url)
        if isinstance(lignes, dict):
            lignes = lignes.get("candlesticks") or lignes.get("result") or []
        sortie = []
        for r in lignes:
            try:
                t = int(float(r.get("timestamp") or r.get("time")))
                if t > 1e12:
                    t //= 1000
                sortie.append(Bougie(
                    t, float(r["open"]), float(r["high"]),
                    float(r["low"]), float(r["close"]), float(r.get("volume") or 0),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        sortie.sort(key=lambda b: b.t)
        return _dedoublonne(sortie)


# ---------------------------------------------------------------------------
# Préparation des séries
# ---------------------------------------------------------------------------

def _lots(liste, taille):
    for i in range(0, len(liste), taille):
        yield liste[i:i + taille]


def _dedoublonne(bougies):
    vues, sortie = set(), []
    for b in bougies:
        if b.t not in vues:
            vues.add(b.t)
            sortie.append(b)
    return sortie


def _iso_vers_unix(s):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s) / (1000.0 if float(s) > 1e12 else 1.0)
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def combler_et_tronquer(bougies, pas=60):
    """Comble à plat les minutes sans trade (≤ TROU_MAX_MIN) ; au-delà,
    la série s'arrête au trou (token inactif ou parti sur l'AMM)."""
    if not bougies:
        return []
    sortie = [bougies[0]]
    for b in bougies[1:]:
        trou = (b.t - sortie[-1].t) // pas - 1
        if trou > TROU_MAX_MIN:
            break
        if trou > 0:
            c = sortie[-1].c
            for k in range(1, trou + 1):
                sortie.append(Bougie(sortie[-1].t + pas, c, c, c, c, 0.0))
        sortie.append(b)
    return sortie


def reechantillonner(bougies, facteur=5, pas=60):
    sortie, seau = [], []
    for b in bougies:
        if seau and b.t // (pas * facteur) != seau[0].t // (pas * facteur):
            sortie.append(_fusionne(seau))
            seau = []
        seau.append(b)
    if seau:
        sortie.append(_fusionne(seau))
    return sortie


def _fusionne(seau):
    return Bougie(
        seau[0].t, seau[0].o, max(b.h for b in seau),
        min(b.l for b in seau), seau[-1].c, sum(b.v for b in seau),
    )


def preparer(bougies):
    bougies = combler_et_tronquer([b for b in bougies if b.c > 0 and b.l > 0])
    if len(bougies) > RESAMPLE_AU_DELA:
        bougies = reechantillonner(bougies)
    return bougies


# ---------------------------------------------------------------------------
# Boîte à outils géométrique
# ---------------------------------------------------------------------------

def _droite(xs, ys):
    """Moindres carrés → (pente, ordonnée, R²)."""
    n = len(xs)
    if n < 2:
        return 0.0, ys[0] if ys else 0.0, 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, my, 0.0
    pente = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    b = my - pente * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (pente * x + b)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return pente, b, r2


def _parabole(seg):
    """Ajuste y = a·x² + b·x + c (x normalisé sur [0,1], y relatif au 1er point).
    → (a, R², position du sommet dans [0,1] ou -1)."""
    n = len(seg)
    if n < 5 or seg[0] <= 0:
        return 0.0, 0.0, -1.0
    xs = [i / (n - 1) for i in range(n)]
    ys = [p / seg[0] for p in seg]
    s = [sum(x ** k for x in xs) for k in range(5)]
    sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sx2y = sum(x * x * y for x, y in zip(xs, ys))
    mat = [
        [s[4], s[3], s[2], sx2y],
        [s[3], s[2], s[1], sxy],
        [s[2], s[1], float(n), sy],
    ]
    for col in range(3):  # élimination de Gauss avec pivot partiel
        piv = max(range(col, 3), key=lambda r: abs(mat[r][col]))
        if abs(mat[piv][col]) < 1e-12:
            return 0.0, 0.0, -1.0
        mat[col], mat[piv] = mat[piv], mat[col]
        for r in range(3):
            if r != col:
                f = mat[r][col] / mat[col][col]
                mat[r] = [v - f * w for v, w in zip(mat[r], mat[col])]
    a, b = mat[0][3] / mat[0][0], mat[1][3] / mat[1][1]
    c = mat[2][3] / mat[2][2]
    my = sy / n
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (a * x * x + b * x + c)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    sommet = -b / (2 * a) if a != 0 else -1.0
    return a, r2, sommet


def zigzag(fermetures, seuil):
    pivots, n = [], len(fermetures)
    if n < 3:
        return pivots
    max_i = min_i = 0
    tendance = 0
    for i in range(1, n):
        p = fermetures[i]
        if p > fermetures[max_i]:
            max_i = i
        if p < fermetures[min_i]:
            min_i = i
        if tendance == 0:
            if p >= fermetures[min_i] * (1 + seuil):
                pivots.append(Pivot(min_i, fermetures[min_i], "L"))
                tendance, max_i = 1, i
            elif p <= fermetures[max_i] * (1 - seuil):
                pivots.append(Pivot(max_i, fermetures[max_i], "H"))
                tendance, min_i = -1, i
        elif tendance == 1 and p <= fermetures[max_i] * (1 - seuil):
            pivots.append(Pivot(max_i, fermetures[max_i], "H"))
            tendance, min_i = -1, i
        elif tendance == -1 and p >= fermetures[min_i] * (1 + seuil):
            pivots.append(Pivot(min_i, fermetures[min_i], "L"))
            tendance, max_i = 1, i
    # dernier extrême courant, utile pour clore les motifs en fin de série
    if tendance == 1:
        pivots.append(Pivot(max_i, fermetures[max_i], "H"))
    elif tendance == -1:
        pivots.append(Pivot(min_i, fermetures[min_i], "L"))
    return pivots


class Contexte:
    """Série préparée + pivots + seuils adaptatifs, partagée par les détecteurs."""

    def __init__(self, bougies, seuil_force=None):
        self.bougies = bougies
        self.fermetures = [b.c for b in bougies]
        self.hauts = [b.h for b in bougies]
        self.bas = [b.l for b in bougies]
        amplitudes = sorted((b.h - b.l) / b.c for b in bougies if b.c > 0)
        self.amplitude_med = amplitudes[len(amplitudes) // 2] if amplitudes else 0.0
        if seuil_force:
            self.seuil = seuil_force
        else:
            self.seuil = min(SEUIL_ZIGZAG_MAX,
                             max(SEUIL_ZIGZAG_MIN, SEUIL_ZIGZAG_K * self.amplitude_med))
        self.pivots = zigzag(self.fermetures, self.seuil)
        self.pole_min = max(POLE_MIN_PLANCHER, 5 * self.amplitude_med)

    def cassure_apres(self, i, niveau, horizon=HORIZON_CASSURE):
        fin = min(len(self.fermetures), i + 1 + horizon)
        for j in range(i + 1, fin):
            if self.fermetures[j] > niveau:
                return j
        return None


# ---------------------------------------------------------------------------
# Détecteurs (un par figure ; True dès qu'une occurrence est trouvée)
# ---------------------------------------------------------------------------

def _fenetres_pivots(pivots, tailles=(4, 5, 6, 7, 8)):
    for k in range(len(pivots)):
        for taille in tailles:
            if k + taille <= len(pivots):
                yield pivots[k:k + taille]


def detecte_canal_ascendant(ctx):
    for w in _fenetres_pivots(ctx.pivots):
        hs = [p.p for p in w if p.typ == "H"]
        ls = [p.p for p in w if p.typ == "L"]
        if len(hs) >= 2 and len(ls) >= 2:
            if all(b >= a * 1.03 for a, b in zip(hs, hs[1:])) and \
               all(b >= a * 1.03 for a, b in zip(ls, ls[1:])):
                return True
    return False


def detecte_drapeau_et_fanion(ctx):
    drapeau = fanion = False
    piv = ctx.pivots
    for k in range(len(piv) - 1):
        a, b = piv[k], piv[k + 1]
        if a.typ != "L" or b.typ != "H":
            continue
        largeur = b.i - a.i
        hausse = b.p / a.p - 1 if a.p > 0 else 0
        if largeur > POLE_BARS_MAX or hausse < ctx.pole_min:
            continue
        pole_h = b.p - a.p
        plancher = b.p - RETRACE_MAX_DRAPEAU * pole_h
        j_cassure, valide = None, True
        fin = min(len(ctx.fermetures), b.i + 1 + HORIZON_CASSURE)
        for j in range(b.i + 1, fin):
            if ctx.fermetures[j] > b.p * 1.005:
                j_cassure = j
                break
            if ctx.bas[j] < plancher:
                valide = False
                break
        if not valide or j_cassure is None or j_cassure - b.i < CONSOL_MIN + 1:
            continue
        # la poussée finale vers la cassure n'appartient pas à la consolidation :
        # on retire la série terminale de clôtures strictement croissantes
        fin_consol = j_cassure - 1
        while fin_consol > b.i + 1 and ctx.fermetures[fin_consol] > ctx.fermetures[fin_consol - 1]:
            fin_consol -= 1
        if fin_consol - b.i < CONSOL_MIN:
            continue
        seg_h = ctx.hauts[b.i + 1:fin_consol + 1]
        seg_l = ctx.bas[b.i + 1:fin_consol + 1]
        xs = list(range(len(seg_h)))
        pente_h, _, _ = _droite(xs, seg_h)
        pente_l, _, _ = _droite(xs, seg_l)
        # dérive totale (en % du sommet du mât) sur toute la consolidation :
        # plus robuste au bruit qu'une pente par barre
        derive_h = pente_h * (len(seg_h) - 1) / b.p
        derive_l = pente_l * (len(seg_l) - 1) / b.p
        if derive_h <= -0.015 and derive_l >= 0.015:
            fanion = True
        elif derive_h <= 0.02:
            drapeau = True
        if drapeau and fanion:
            break
    return drapeau, fanion


def detecte_triangle_ascendant(ctx):
    for w in _fenetres_pivots(ctx.pivots):
        hs = [p for p in w if p.typ == "H"]
        ls = [p for p in w if p.typ == "L"]
        if len(hs) < 2 or len(ls) < 2:
            continue
        haut = max(p.p for p in hs)
        bas_h = min(p.p for p in hs)
        if bas_h <= 0 or (haut - bas_h) / bas_h > TOL_RESISTANCE:
            continue
        prix_ls = [p.p for p in ls]
        if not all(b >= a * 1.02 for a, b in zip(prix_ls, prix_ls[1:])):
            continue
        if ctx.cassure_apres(w[-1].i, haut * 1.005) is not None:
            return True
    return False


def detecte_rectangle_haussier(ctx):
    for w in _fenetres_pivots(ctx.pivots):
        hs = [p.p for p in w if p.typ == "H"]
        ls = [p.p for p in w if p.typ == "L"]
        if len(hs) < 2 or len(ls) < 2:
            continue
        R, S = sum(hs) / len(hs), sum(ls) / len(ls)
        if S <= 0 or not (0.05 <= (R - S) / S <= 0.35):
            continue
        if any(abs(h - R) / R > 0.04 for h in hs):
            continue
        if any(abs(l - S) / S > 0.04 for l in ls):
            continue
        if ctx.cassure_apres(w[-1].i, R * 1.01) is not None:
            return True
    return False


def detecte_biseau_descendant(ctx):
    for w in _fenetres_pivots(ctx.pivots):
        hs = [p for p in w if p.typ == "H"]
        ls = [p for p in w if p.typ == "L"]
        if len(hs) < 2 or len(ls) < 2 or w[-1].i - w[0].i < 5:
            continue
        if not all(b.p <= a.p * 0.98 for a, b in zip(hs, hs[1:])):
            continue
        if not all(b.p <= a.p * 0.995 for a, b in zip(ls, ls[1:])):
            continue
        ref = w[0].p
        pente_h = (hs[-1].p - hs[0].p) / max(1, hs[-1].i - hs[0].i) / ref
        pente_l = (ls[-1].p - ls[0].p) / max(1, ls[-1].i - ls[0].i) / ref
        if not (pente_h < pente_l <= 0.0):
            continue
        # cassure de la ligne des sommets, prolongée après le dernier pivot
        a_i, a_p, b_i, b_p = hs[0].i, hs[0].p, hs[-1].i, hs[-1].p
        pente = (b_p - a_p) / max(1, b_i - a_i)
        fin = min(len(ctx.fermetures), w[-1].i + 1 + HORIZON_CASSURE)
        for j in range(w[-1].i + 1, fin):
            ligne = b_p + pente * (j - b_i)
            if ligne > 0 and ctx.fermetures[j] > ligne * 1.005:
                return True
    return False


def detecte_double_creux(ctx):
    piv = ctx.pivots
    for k in range(len(piv) - 2):
        l1, h, l2 = piv[k], piv[k + 1], piv[k + 2]
        if l1.typ != "L" or h.typ != "H" or l2.typ != "L" or l1.p <= 0:
            continue
        if abs(l2.p - l1.p) / l1.p > TOL_CREUX_DOUBLE:
            continue
        if h.p < max(l1.p, l2.p) * (1 + PROF_MIN_DOUBLE):
            continue
        if ctx.cassure_apres(l2.i, h.p * 1.005, 60) is not None:
            return True
    return False


def detecte_triple_creux(ctx):
    piv = ctx.pivots
    for k in range(len(piv) - 4):
        w = piv[k:k + 5]
        if [p.typ for p in w] != ["L", "H", "L", "H", "L"]:
            continue
        creux = [w[0].p, w[2].p, w[4].p]
        if min(creux) <= 0 or (max(creux) - min(creux)) / min(creux) > 0.08:
            continue
        cou = max(w[1].p, w[3].p)
        if cou < min(creux) * (1 + PROF_MIN_DOUBLE):
            continue
        if ctx.cassure_apres(w[4].i, cou * 1.005, 60) is not None:
            return True
    return False


def detecte_ete_inversee(ctx):
    piv = ctx.pivots
    for k in range(len(piv) - 4):
        w = piv[k:k + 5]
        if [p.typ for p in w] != ["L", "H", "L", "H", "L"]:
            continue
        e1, c1, tete, c2, e2 = w
        if min(e1.p, e2.p) <= 0:
            continue
        if not (tete.p <= e1.p * (1 - PROF_TETE) and tete.p <= e2.p * (1 - PROF_TETE)):
            continue
        if abs(e1.p - e2.p) / min(e1.p, e2.p) > TOL_EPAULES:
            continue
        pente = (c2.p - c1.p) / max(1, c2.i - c1.i)
        fin = min(len(ctx.fermetures), e2.i + 1 + 60)
        for j in range(e2.i + 1, fin):
            cou = c2.p + pente * (j - c2.i)
            if cou > 0 and ctx.fermetures[j] > cou * 1.005:
                return True
    return False


def detecte_tasse_et_fond(ctx):
    tasse = fond = False
    n = len(ctx.fermetures)
    for p1 in (p for p in ctx.pivots if p.typ == "H"):
        a = p1.i
        bord = p1.p
        if bord <= 0 or n - a < TASSE_LARG_MIN + 2:
            continue
        r, mini = None, bord
        for j in range(a + 1, n):
            mini = min(mini, ctx.bas[j])
            if j - a >= TASSE_LARG_MIN and ctx.fermetures[j] >= bord * 0.97:
                r = j
                break
        if r is None:
            continue
        prof = 1 - mini / bord
        if not (TASSE_PROF_MIN <= prof <= TASSE_PROF_MAX):
            continue
        courbure, r2, sommet = _parabole(ctx.fermetures[a:r + 1])
        if courbure <= 0 or r2 < TASSE_R2_MIN or not (0.25 <= sommet <= 0.75):
            continue
        fond = True
        limite = min(n, r + max(5, (r - a) // 2) + 1)
        creux_anse = bord
        for j in range(r + 1, limite):
            creux_anse = min(creux_anse, ctx.bas[j])
            if creux_anse < bord * (1 - 0.5 * prof):
                break  # repli trop profond : ce n'est plus une anse
            if ctx.fermetures[j] > bord * 1.01 and j - r >= 2:
                tasse = True
                break
        if tasse:
            break
    return tasse, fond


def detecte_creux_en_v(ctx):
    piv = ctx.pivots
    n = len(ctx.fermetures)
    for k in range(len(piv) - 1):
        h, l = piv[k], piv[k + 1]
        if h.typ != "H" or l.typ != "L" or h.p <= 0:
            continue
        chute = 1 - l.p / h.p
        if chute < CHUTE_V_MIN or l.i - h.i > LARGEUR_V_MAX:
            continue
        cible = l.p + REPRISE_V * (h.p - l.p)
        fin = min(n, l.i + 1 + LARGEUR_V_MAX)
        if any(ctx.fermetures[j] >= cible for j in range(l.i + 1, fin)):
            return True
    return False


def analyser_token(bougies, seuil_force=None):
    """→ (ensemble de codes figures, nb_bougies, nb_pivots) ou None si trop court."""
    bougies = preparer(bougies)
    if len(bougies) < MIN_BOUGIES:
        return None
    ctx = Contexte(bougies, seuil_force)
    if len(ctx.pivots) < MIN_PIVOTS:
        return set(), len(bougies), len(ctx.pivots)
    trouvees = set()
    if detecte_canal_ascendant(ctx):
        trouvees.add("canal_ascendant")
    drapeau, fanion = detecte_drapeau_et_fanion(ctx)
    if drapeau:
        trouvees.add("drapeau_haussier")
    if fanion:
        trouvees.add("fanion_haussier")
    if detecte_triangle_ascendant(ctx):
        trouvees.add("triangle_ascendant")
    if detecte_rectangle_haussier(ctx):
        trouvees.add("rectangle_haussier")
    if detecte_biseau_descendant(ctx):
        trouvees.add("biseau_descendant")
    if detecte_double_creux(ctx):
        trouvees.add("double_creux")
    if detecte_triple_creux(ctx):
        trouvees.add("triple_creux")
    if detecte_ete_inversee(ctx):
        trouvees.add("ete_inversee")
    tasse, fond = detecte_tasse_et_fond(ctx)
    if tasse:
        trouvees.add("tasse_anse")
    if fond:
        trouvees.add("fond_arrondi")
    if detecte_creux_en_v(ctx):
        trouvees.add("creux_en_v")
    # hiérarchie : la figure la plus spécifique absorbe sa version générale
    if "triple_creux" in trouvees:
        trouvees.discard("double_creux")
    if "tasse_anse" in trouvees:
        trouvees.discard("fond_arrondi")
    return trouvees, len(bougies), len(ctx.pivots)


# ---------------------------------------------------------------------------
# Fenêtres temporelles et orchestration
# ---------------------------------------------------------------------------

def fenetres_temporelles(mode, date_ref, reculs):
    jour = dt.datetime(date_ref.year, date_ref.month, date_ref.day,
                       tzinfo=dt.timezone.utc)
    sortie = []
    for d in reculs:
        if mode == "jours":
            t0 = jour - dt.timedelta(days=d)
            t1 = t0 + dt.timedelta(days=1)
            libelle = "hier (J-1)" if d == 1 else f"il y a {d} jours (J-{d})"
        else:
            t0 = jour - dt.timedelta(days=d)
            t1 = jour
            libelle = f"derniers {d} jours" if d > 1 else "dernières 24 h"
        sortie.append({"libelle": libelle, "recul": d, "debut": t0, "fin": t1})
    return sortie


def echantillonner(mints_dates, n):
    """Échantillon déterministe (tri par SHA-1 du mint) → reproductible."""
    tri = sorted(mints_dates, key=lambda md: hashlib.sha1(md[0].encode()).hexdigest())
    return tri[:n]


def analyser_fenetre(fen, args, sources, verbeux=False):
    src_liste, src_bougies = sources
    t0, t1 = fen["debut"], fen["fin"]
    print(f"→ {fen['libelle']} : du {t0:%Y-%m-%d %H:%M} au {t1:%Y-%m-%d %H:%M} UTC",
          file=sys.stderr)
    gradues = src_liste(t0, t1)
    print(f"   {len(gradues)} tokens gradués trouvés", file=sys.stderr)
    lot = echantillonner(gradues, args.echantillon)
    if len(lot) < len(gradues):
        print(f"   échantillon déterministe de {len(lot)} tokens", file=sys.stderr)

    compte = {code: 0 for code, _, _ in FIGURES}
    analyses = trop_courts = 0
    total_figures = 0
    for mint, quand in lot:
        try:
            bougies = src_bougies(mint, quand)
        except RuntimeError as e:
            print(f"   ! {mint[:8]}… : {e}", file=sys.stderr)
            continue
        resultat = analyser_token(bougies, args.seuil_zigzag)
        if resultat is None:
            trop_courts += 1
            continue
        figures, nb, npiv = resultat
        analyses += 1
        total_figures += len(figures)
        for code in figures:
            compte[code] += 1
        if verbeux:
            noms = ", ".join(sorted(figures)) or "aucune"
            print(f"   {mint[:8]}… : {nb} bougies, {npiv} pivots → {noms}",
                  file=sys.stderr)

    return {
        "libelle": fen["libelle"],
        "debut": t0.isoformat(),
        "fin": t1.isoformat(),
        "gradues": len(gradues),
        "echantillon": len(lot),
        "analyses": analyses,
        "series_trop_courtes": trop_courts,
        "figures_par_token": round(total_figures / analyses, 2) if analyses else 0.0,
        "compte": compte,
    }


def bougies_clickhouse_prefetch(ch, lot):
    """ClickHouse répond en un lot : pré-charge toutes les séries d'un coup."""
    cache = ch.bougies([m for m, _ in lot])

    def acces(mint, _quand):
        return cache.get(mint, [])
    return acces


def construire_sources(args):
    """→ (liste_gradués(t0,t1), bougies(mint, graduated_at)) selon --source/--bougies."""
    source = args.source
    if source == "auto":
        ch = ClickHouse()
        if ch.joignable():
            source = "clickhouse"
        elif os.environ.get("MORALIS_API_KEY"):
            source = "moralis"
        else:
            source = "pumpfun"
        print(f"Source auto → {source}", file=sys.stderr)
    bougies = args.bougies if args.bougies != "auto" else source

    if source == "clickhouse":
        ch = ClickHouse()
        if not ch.joignable():
            raise RuntimeError(
                f"ClickHouse injoignable ({ch.url}). Lancer sur le VPS de capture "
                "ou exporter CLICKHOUSE_URL / CLICKHOUSE_USER / CLICKHOUSE_PASSWORD."
            )
        liste = ch.gradues
    elif source == "moralis":
        liste = Moralis(os.environ.get("MORALIS_API_KEY")).gradues
    elif source == "pumpfun":
        print("⚠ source pumpfun : cohorte approchée par jour de création "
              "(pas d'horodatage de graduation dans l'API publique)", file=sys.stderr)
        liste = PumpFun().gradues
    else:
        raise ValueError(source)

    minutes_post = args.minutes_post * 60
    if bougies == "clickhouse":
        ch2 = ClickHouse()

        def bougies_fn(mint, quand):
            raise RuntimeError("interne : le mode ClickHouse passe par le pré-chargement")
        bougies_fn.prefetch = lambda lot: bougies_clickhouse_prefetch(ch2, lot)
    elif bougies == "moralis":
        mo = Moralis(os.environ.get("MORALIS_API_KEY"))

        def bougies_fn(mint, quand):
            return mo.bougies(mint, quand, quand + minutes_post)
        bougies_fn.prefetch = None
    elif bougies == "geckoterminal":
        gt = GeckoTerminal()

        def bougies_fn(mint, quand):
            return gt.bougies(mint, quand, quand + minutes_post)
        bougies_fn.prefetch = None
    elif bougies == "pumpfun":
        pf = PumpFun()

        def bougies_fn(mint, quand):
            return pf.bougies(mint)
        bougies_fn.prefetch = None
    else:
        raise ValueError(bougies)

    return liste, bougies_fn, source, bougies


# ---------------------------------------------------------------------------
# Rendu
# ---------------------------------------------------------------------------

def rendu_markdown(resultats, meta):
    lignes = [
        "# Figures chartistes haussières — tokens gradués Pump.fun",
        "",
        f"Généré le {meta['genere_le']} — mode `{meta['mode']}`, "
        f"source gradués `{meta['source']}`, bougies `{meta['bougies']}`, "
        f"échantillon max {meta['echantillon']} tokens/fenêtre.",
        "",
        "Une même série peut présenter plusieurs figures ; les pourcentages "
        "sont rapportés aux tokens analysés (donc la colonne ne somme pas à 100 %).",
        "",
    ]
    for r in resultats:
        lignes += [
            f"## {r['libelle']} — {r['debut'][:10]} → {r['fin'][:10]}",
            "",
            f"Tokens gradués : **{r['gradues']}** · analysés : **{r['analyses']}** "
            f"(échantillon {r['echantillon']}, séries trop courtes : "
            f"{r['series_trop_courtes']}) · figures haussières par token : "
            f"**{r['figures_par_token']}**",
            "",
        ]
        if not r["analyses"]:
            lignes += ["_Aucune série exploitable sur cette fenêtre._", ""]
            continue
        lignes += ["| Rang | Figure | Tokens | % des analysés |",
                   "|---:|---|---:|---:|"]
        classement = sorted(r["compte"].items(), key=lambda kv: -kv[1])
        rang = 0
        for code, n in classement:
            if n == 0:
                continue
            rang += 1
            pct = 100.0 * n / r["analyses"]
            lignes.append(f"| {rang} | {NOMS[code]} | {n} | {pct:.1f} % |")
        if rang == 0:
            lignes.append("| — | aucune figure détectée | 0 | 0 % |")
        lignes.append("")
    return "\n".join(lignes)


def rendu_console(resultats):
    for r in resultats:
        print(f"\n=== {r['libelle']} ({r['debut'][:10]} → {r['fin'][:10]}) ===")
        print(f"gradués {r['gradues']} · analysés {r['analyses']} · "
              f"trop courts {r['series_trop_courtes']} · "
              f"figures/token {r['figures_par_token']}")
        classement = [kv for kv in sorted(r["compte"].items(), key=lambda kv: -kv[1])
                      if kv[1] > 0]
        if not classement:
            print("  (aucune figure détectée)")
            continue
        for rang, (code, n) in enumerate(classement, 1):
            pct = 100.0 * n / r["analyses"] if r["analyses"] else 0.0
            print(f"  {rang:2d}. {NOMS[code]:<55} {n:4d}  ({pct:5.1f} %)")


# ---------------------------------------------------------------------------
# Autotest : séries synthétiques → chaque détecteur doit reconnaître la sienne
# ---------------------------------------------------------------------------

def _serie(segments, depart=1.0, bruit=0.004):
    """Construit des bougies depuis des segments (multiplicateur_cible, nb_barres),
    interpolés en log, avec une ondulation déterministe légère."""
    prix, bougies, t, i = depart, [], 1_700_000_000, 0
    for mult, nb in segments:
        cible = prix * mult
        for k in range(nb):
            suivant = prix * (cible / prix) ** (1 / (nb - k))
            osc = 1 + bruit * math.sin(i * 1.7)
            o, c = prix * osc, suivant * osc
            h = max(o, c) * (1 + bruit)
            l = min(o, c) * (1 - bruit)
            bougies.append(Bougie(t, o, h, l, c, 1.0))
            prix, t, i = suivant, t + 60, i + 1
    return bougies


def _serie_fanion():
    """Mât puis fanion à amplitude décroissante (sommets baissants, creux montants),
    puis cassure — construit explicitement pour être convergent."""
    b = _serie([(1.02, 6), (1.9, 8)], bruit=0.002)
    haut_mat, t = b[-1].c, b[-1].t
    milieu = haut_mat * 0.90
    signe = 1
    for amp in (0.075, 0.065, 0.055, 0.045, 0.035, 0.028, 0.020, 0.014, 0.010, 0.007):
        c = milieu * (1 + signe * amp)
        o = milieu * (1 - signe * amp * 0.9)
        t += 60
        b.append(Bougie(t, o, max(o, c) * 1.002, min(o, c) * 0.998, c, 1.0))
        signe = -signe
    prix = b[-1].c
    for _ in range(4):
        o, prix = prix, prix * 1.06
        t += 60
        b.append(Bougie(t, o, prix * 1.002, o * 0.998, prix, 1.0))
    return b


def autotest():
    cas = {
        "canal_ascendant": _serie([(1.25, 6), (0.88, 5), (1.30, 6), (0.90, 5),
                                   (1.28, 6), (0.90, 5), (1.25, 6)]),
        "drapeau_haussier": _serie([(1.02, 6), (1.9, 8), (0.93, 3), (1.02, 3),
                                    (0.94, 3), (1.01, 3), (1.25, 5)]),
        "fanion_haussier": _serie_fanion(),
        "triangle_ascendant": _serie([(1.5, 6), (0.75, 5), (1.32, 5), (0.83, 5),
                                      (1.19, 5), (0.90, 4), (1.10, 4), (1.18, 5)]),
        "rectangle_haussier": _serie([(1.4, 6), (0.85, 5), (1.17, 5), (0.855, 5),
                                      (1.165, 5), (0.86, 5), (1.16, 5), (1.15, 5)]),
        "biseau_descendant": _serie([(1.02, 4), (0.72, 6), (1.18, 5), (0.80, 6),
                                     (1.12, 5), (0.86, 6), (1.35, 6)]),
        "double_creux": _serie([(1.02, 5), (0.70, 6), (1.22, 6), (0.83, 6),
                                (1.35, 8)]),
        "triple_creux": _serie([(1.02, 4), (0.72, 5), (1.16, 5), (0.865, 5),
                                (1.155, 5), (0.867, 5), (1.30, 7)]),
        "ete_inversee": _serie([(1.02, 4), (0.80, 5), (1.18, 5), (0.72, 5),
                                (1.36, 5), (0.82, 5), (1.30, 7)]),
        "tasse_anse": _serie([(1.35, 5), (0.92, 3), (0.90, 4), (0.945, 5),
                              (1.10, 5), (1.13, 4), (0.96, 3), (1.10, 4)]),
        "fond_arrondi": _serie([(1.35, 5), (0.92, 4), (0.90, 5), (0.95, 6),
                                (1.09, 6), (1.15, 5)]),
        "creux_en_v": _serie([(1.02, 4), (1.4, 8), (0.55, 5), (1.9, 8)]),
    }
    echecs = []
    for code, bougies in cas.items():
        resultat = analyser_token(bougies, seuil_force=0.05)
        trouvees = resultat[0] if resultat else set()
        # hiérarchie : triple absorbe double, tasse absorbe fond — accepté
        equivalents = {
            "double_creux": {"double_creux", "triple_creux"},
            "fond_arrondi": {"fond_arrondi", "tasse_anse"},
        }.get(code, {code})
        if not (trouvees & equivalents):
            echecs.append((code, sorted(trouvees)))
    temoin = _serie([(0.4, 30)])  # pure baisse : aucune figure haussière attendue
    r_temoin = analyser_token(temoin, seuil_force=0.05)
    figures_temoin = r_temoin[0] if r_temoin else set()
    if figures_temoin:
        echecs.append(("temoin_baissier", sorted(figures_temoin)))
    for code, obtenu in echecs:
        print(f"ÉCHEC {code} : détecté {obtenu}")
    print(f"Autotest : {len(cas) + 1 - len(echecs)}/{len(cas) + 1} cas OK")
    return 0 if not echecs else 1


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def principal():
    p = argparse.ArgumentParser(
        description="Figures chartistes haussières des tokens gradués Pump.fun "
                    "(hier / il y a 7 jours / il y a 30 jours).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--mode", choices=["jours", "cumule"], default="jours",
                   help="cohortes d'un jour (J-1/J-7/J-30) ou fenêtres glissantes")
    p.add_argument("--fenetres", default="1,7,30",
                   help="reculs en jours, séparés par des virgules")
    p.add_argument("--date-ref", default=None,
                   help="date de référence AAAA-MM-JJ (défaut : aujourd'hui UTC)")
    p.add_argument("--source", default="auto",
                   choices=["auto", "clickhouse", "moralis", "pumpfun"],
                   help="d'où vient la liste des tokens gradués")
    p.add_argument("--bougies", default="auto",
                   choices=["auto", "clickhouse", "moralis", "geckoterminal", "pumpfun"],
                   help="d'où viennent les chandelles")
    p.add_argument("--echantillon", type=int, default=150,
                   help="tokens analysés au maximum par fenêtre (déterministe)")
    p.add_argument("--minutes-post", type=int, default=720,
                   help="minutes de chart post-graduation (sources moralis/geckoterminal)")
    p.add_argument("--seuil-zigzag", type=float, default=None,
                   help="forcer le seuil ZigZag (défaut : adaptatif)")
    p.add_argument("--json", metavar="FICHIER", help="écrire les résultats en JSON")
    p.add_argument("--markdown", metavar="FICHIER", help="écrire le rapport Markdown")
    p.add_argument("--verbeux", action="store_true",
                   help="détail par token sur stderr")
    p.add_argument("--autotest", action="store_true",
                   help="vérifie les détecteurs sur des séries synthétiques puis sort")
    args = p.parse_args()

    if args.autotest:
        sys.exit(autotest())

    date_ref = (dt.date.fromisoformat(args.date_ref) if args.date_ref
                else dt.datetime.now(dt.timezone.utc).date())
    reculs = [int(x) for x in args.fenetres.split(",") if x.strip()]

    try:
        liste, bougies_fn, nom_source, nom_bougies = construire_sources(args)
    except RuntimeError as e:
        print(f"Erreur : {e}", file=sys.stderr)
        sys.exit(2)

    resultats = []
    for fen in fenetres_temporelles(args.mode, date_ref, reculs):
        try:
            if getattr(bougies_fn, "prefetch", None):
                # ClickHouse : une passe réseau par fenêtre, pas par token
                t0, t1 = fen["debut"], fen["fin"]
                gradues = liste(t0, t1)
                lot = echantillonner(gradues, args.echantillon)
                acces = bougies_fn.prefetch(lot)
                sources = (lambda a, b, g=gradues: g, acces)
            else:
                sources = (liste, bougies_fn)
            resultats.append(analyser_fenetre(fen, args, sources, args.verbeux))
        except RuntimeError as e:
            print(f"Erreur sur la fenêtre « {fen['libelle']} » : {e}", file=sys.stderr)
            resultats.append({
                "libelle": fen["libelle"], "debut": fen["debut"].isoformat(),
                "fin": fen["fin"].isoformat(), "erreur": str(e),
                "gradues": 0, "echantillon": 0, "analyses": 0,
                "series_trop_courtes": 0, "figures_par_token": 0.0,
                "compte": {code: 0 for code, _, _ in FIGURES},
            })

    meta = {
        "genere_le": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "mode": args.mode,
        "source": nom_source,
        "bougies": nom_bougies,
        "echantillon": args.echantillon,
        "date_ref": date_ref.isoformat(),
    }
    rendu_console(resultats)
    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as f:
            f.write(rendu_markdown(resultats, meta))
        print(f"\nRapport Markdown : {args.markdown}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"meta": meta, "fenetres": resultats}, f,
                      ensure_ascii=False, indent=2)
        print(f"Résultats JSON : {args.json}")


if __name__ == "__main__":
    principal()
