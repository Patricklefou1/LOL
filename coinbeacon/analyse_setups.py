#!/usr/bin/env python3
"""Rentabilite des detections CoinBeacon aux horizons 4 h et 24 h.

Le jeton est lu uniquement dans la variable d'environnement COINBEACON_TOKEN.
Il n'est jamais affiche, ni ecrit dans le cache, le CSV, le rapport ou les journaux.

    export COINBEACON_TOKEN=...                 # jamais dans un fichier
    export COINBEACON_API_URL=https://...       # endpoint des setups
    python coinbeacon/analyse_setups.py

Voir coinbeacon/README.md pour les options (pagination, correspondance des champs,
authentification, mode hors ligne).
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlparse

import numpy as np
import requests

try:
    from scipy import stats as sps
except ImportError:  # scipy est optionnel : sans lui, pas de tests KS / Wilcoxon
    sps = None

MIN_MS = 60_000
HOUR_MS = 60 * MIN_MS
DAY_MS = 24 * HOUR_MS
HORIZONS = (4, 24)
KLINE_LIMIT = 1000
BLOCK_MS = KLINE_LIMIT * MIN_MS
MIN_N = 30
HERE = Path(__file__).resolve().parent

# --------------------------------------------------------------------------- securite

_SECRETS: list[str] = []


def redact(text) -> str:
    text = str(text)
    for secret in _SECRETS:
        if secret:
            text = text.replace(secret, "<jeton masque>")
    return text


def log(*parts) -> None:
    print(redact(" ".join(str(p) for p in parts)), file=sys.stderr, flush=True)


class Stop(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(redact(message))
        self.code = code


# --------------------------------------------------------------------------- cache et HTTP


class Cache:
    def __init__(self, root: Path):
        self.root = root

    def _api_path(self, key: str) -> Path:
        return self.root / "api" / (hashlib.sha256(key.encode()).hexdigest()[:40] + ".json.gz")

    def _kline_path(self, symbol: str, block: int) -> Path:
        return self.root / "klines" / symbol / f"{block}.json.gz"

    @staticmethod
    def _read(path: Path):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _write(path: Path, obj) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = redact(json.dumps(obj, separators=(",", ":")))
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            f.write(text)
        tmp.replace(path)

    def get_api(self, key: str, max_age_s: float | None):
        p = self._api_path(key)
        if not p.exists():
            return None
        if max_age_s is not None and time.time() - p.stat().st_mtime > max_age_s:
            return None
        return self._read(p)

    def put_api(self, key: str, obj) -> None:
        self._write(self._api_path(key), obj)

    def get_klines(self, symbol: str, block: int):
        p = self._kline_path(symbol, block)
        return self._read(p) if p.exists() else None

    def put_klines(self, symbol: str, block: int, rows) -> None:
        self._write(self._kline_path(symbol, block), rows)

    def get_misc(self, name: str, max_age_s: float | None):
        p = self.root / "misc" / f"{name}.json.gz"
        if not p.exists() or (max_age_s is not None and time.time() - p.stat().st_mtime > max_age_s):
            return None
        return self._read(p)

    def put_misc(self, name: str, obj) -> None:
        self._write(self.root / "misc" / f"{name}.json.gz", obj)


class Http:
    def __init__(self, offline: bool, min_interval: float = 0.06, timeout: float = 30):
        self.session = requests.Session()
        self.offline = offline
        self.min_interval = min_interval
        self.timeout = timeout
        self._last = 0.0
        self.calls = 0

    def get(self, url, params=None, headers=None, retries=5):
        if self.offline:
            raise Stop(f"mode hors ligne : reponse absente du cache pour {urlparse(url).netloc}{urlparse(url).path}")
        last_error = None
        for attempt in range(retries):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            self.calls += 1
            try:
                r = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                last_error = f"{type(e).__name__}: {redact(e)}"
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 418:
                raise Stop("Binance a banni temporairement l'adresse IP (HTTP 418) : arret pour ne pas aggraver", 5)
            if r.status_code == 429 or r.status_code >= 500:
                retry_after = r.headers.get("Retry-After")
                time.sleep(float(retry_after) if retry_after and retry_after.isdigit() else 2 ** (attempt + 1))
                last_error = f"HTTP {r.status_code}"
                continue
            used = r.headers.get("X-MBX-USED-WEIGHT-1M")
            if used and used.isdigit() and int(used) > 4800:
                log(f"  poids Binance {used}/6000 : pause 20 s")
                time.sleep(20)
            return r
        raise Stop(f"echec reseau apres {retries} essais : {last_error}")


# --------------------------------------------------------------------------- API CoinBeacon

LIST_KEYS = ("data", "results", "items", "setups", "rows", "records", "docs", "detections", "signals", "content")
TOTAL_KEYS = ("total", "count", "totalCount", "total_count", "totalItems", "total_items", "totalElements", "total_results")


def _dig(obj, *paths):
    for path in paths:
        cur = obj
        ok = True
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur not in (None, ""):
            return cur
    return None


def extract_records(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in LIST_KEYS:
        v = payload.get(key)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            for k2 in LIST_KEYS:
                if isinstance(v.get(k2), list):
                    return v[k2]
    lists = [v for v in payload.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
    return lists[0] if len(lists) == 1 else []


def find_total(payload):
    if not isinstance(payload, dict):
        return None
    for prefix in ("", "meta.", "pagination.", "data.", "page_info.", "pageInfo."):
        v = _dig(payload, *[prefix + k for k in TOTAL_KEYS])
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return int(v)
    return None


def parse_link_header(value: str | None):
    if not value:
        return None
    for part in value.split(","):
        m = re.match(r'\s*<([^>]+)>\s*;\s*rel="?next"?', part)
        if m:
            return m.group(1)
    return None


class SetupsApi:
    def __init__(self, args, token, http: Http, cache: Cache):
        self.url = args.api_url
        self.token = token
        self.http = http
        self.cache = cache
        self.args = args
        self.extra = dict(kv.split("=", 1) for kv in args.api_param)
        self.ttl = None if args.offline else (0 if args.refresh_api else args.api_cache_hours * 3600)

    def _auth(self, params):
        headers = {"Accept": "application/json"}
        if self.args.auth_query_param:
            params = {**params, self.args.auth_query_param: self.token}
        else:
            scheme = self.args.auth_scheme.strip()
            headers[self.args.auth_header] = f"{scheme} {self.token}" if scheme else self.token
        return headers, params

    def _key(self, url, params):
        clean = sorted((k, str(v)) for k, v in params.items() if k != self.args.auth_query_param)
        return json.dumps([url, clean, self.args.auth_header])

    def get(self, url, params, use_cache=True):
        key = self._key(url, params)
        if use_cache:
            hit = self.cache.get_api(key, self.ttl)
            if hit is not None:
                return hit["status"], hit["payload"], hit.get("link")
        headers, full_params = self._auth(params)
        r = self.http.get(url, params=full_params, headers=headers, retries=3)
        try:
            payload = r.json()
        except ValueError:
            payload = None
        link = r.headers.get("Link")
        if r.status_code == 200 and payload is not None:
            self.cache.put_api(key, {"status": 200, "payload": payload, "link": link})
        return r.status_code, payload, link

    def first_params(self):
        params = dict(self.extra)
        a = self.args
        if a.limit_param and a.limit:
            params[a.limit_param] = a.limit
        if a.page_param:
            params[a.page_param] = a.start_page
        if a.offset_param:
            params[a.offset_param] = 0
        return params

    def _next(self, url, params, payload, link, n_recs):
        a = self.args
        if a.page_param:
            return url, {**params, a.page_param: int(params[a.page_param]) + 1}, f"parametre {a.page_param}"
        if a.offset_param:
            return url, {**params, a.offset_param: int(params[a.offset_param]) + n_recs}, f"parametre {a.offset_param}"
        nxt = parse_link_header(link)
        if nxt:
            return urljoin(url, nxt), {}, "en-tete Link"
        if isinstance(payload, dict):
            nxt = _dig(payload, "next", "links.next", "pagination.next", "meta.next", "next_page_url",
                       "meta.next_page_url", "_links.next.href", "links.next.href", "paging.next")
            if isinstance(nxt, str) and nxt.strip():
                full = urljoin(url, nxt)
                # une URL suivante relative peut perdre les filtres : on garde ceux qu'elle ne redefinit pas
                q = dict(parse_qsl(urlparse(full).query))
                kept = {k: v for k, v in self.extra.items() if k not in q}
                return full, kept, "champ next"
            cursor = _dig(payload, "next_cursor", "nextCursor", "cursor.next", "meta.next_cursor",
                          "pagination.next_cursor", "meta.nextCursor", "pagination.nextCursor", "page_info.end_cursor")
            has_more = _dig(payload, "has_more", "hasMore", "meta.has_more", "pagination.has_more",
                            "page_info.has_next_page", "pageInfo.hasNextPage", "has_next", "hasNext")
            if cursor not in (None, "") and has_more is not False:
                return url, {**params, a.cursor_param: cursor}, f"curseur ({a.cursor_param})"
            page = _dig(payload, "page", "current_page", "currentPage", "meta.page", "meta.current_page",
                        "pagination.page", "pagination.current_page", "pagination.currentPage")
            last = _dig(payload, "total_pages", "totalPages", "last_page", "lastPage", "pages", "meta.total_pages",
                        "meta.last_page", "pagination.total_pages", "pagination.totalPages", "pagination.last_page")
            if isinstance(page, (int, str)) and str(page).isdigit() and isinstance(last, (int, str)) and str(last).isdigit():
                if int(page) < int(last):
                    return url, {**params, "page": int(page) + 1}, "numeros de page"
                return None
            if has_more is True:
                off = int(params.get("offset", 0)) + n_recs
                return url, {**params, "offset": off}, "has_more + offset"
        return None

    def fetch_all(self):
        url, params = self.url, self.first_params()
        records, seen = [], set()
        meta = {"pages": 0, "methode": "page unique", "total_annonce": None, "tronque": False, "boucle": False}
        while True:
            if meta["pages"] >= self.args.max_pages:
                meta["tronque"] = True
                log(f"  arret a {self.args.max_pages} pages (--max-pages) : historique possiblement tronque")
                break
            status, payload, link = self.get(url, params)
            if status != 200:
                raise Stop(f"API CoinBeacon : HTTP {status} sur la page {meta['pages'] + 1}", 3)
            recs = [r for r in extract_records(payload) if isinstance(r, dict)]
            meta["pages"] += 1
            if meta["total_annonce"] is None:
                meta["total_annonce"] = find_total(payload)
            new = 0
            for rec in recs:
                rid = rec.get("id", rec.get("_id", rec.get("uuid")))
                key = str(rid) if rid is not None else hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()
                if key in seen:
                    continue
                seen.add(key)
                records.append(rec)
                new += 1
            if meta["pages"] % 20 == 0:
                log(f"  {meta['pages']} pages, {len(records)} detections")
            if not recs:
                break
            if new == 0:
                meta["boucle"] = True
                log("  la page suivante ne renvoie que des detections deja vues : arret (pagination en boucle ?)")
                break
            nxt = self._next(url, params, payload, link, len(recs))
            if nxt is None:
                break
            url, params, meta["methode"] = nxt
        return records, meta


# --------------------------------------------------------------------------- correspondance des champs

CANDIDATES = {
    "id": ["id", "setup_id", "setupId", "uuid", "_id", "detection_id", "detectionId"],
    "pair": ["symbol", "pair", "ticker", "market", "instrument", "trading_pair", "tradingPair", "coin", "asset"],
    "type": ["setup_type", "setupType", "type", "pattern", "strategy", "setup", "signal_type", "signalType", "kind", "name"],
    "side": ["side", "direction", "bias", "signal", "position", "sentiment", "action", "trend"],
    "time": ["detected_at", "detectedAt", "detection_time", "detectionTime", "triggered_at", "triggeredAt",
             "signal_time", "signalTime", "created_at", "createdAt", "timestamp", "time", "datetime", "date"],
    "price": ["price_at_detection", "detection_price", "entry_price", "entryPrice", "price", "close", "current_price"],
    "exit_4h": ["price_4h", "price4h", "close_4h", "price_after_4h", "priceAfter4h", "price_4h_after"],
    "exit_24h": ["price_24h", "price24h", "close_24h", "price_after_24h", "priceAfter24h", "price_24h_after"],
    "status": ["status", "state", "outcome", "result"],
}

LONG_WORDS = {"long", "buy", "bull", "bullish", "up", "haussier", "hausse", "achat", "acheteur", "call", "1", "+1"}
SHORT_WORDS = {"short", "sell", "bear", "bearish", "down", "baissier", "baisse", "vente", "vendeur", "put", "-1"}


def flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        else:
            out[key] = v
    return out


def detect_mapping(rows, overrides):
    fields = Counter()
    for r in rows:
        fields.update(k for k, v in r.items() if v not in (None, ""))
    n = max(len(rows), 1)
    by_lower = {}
    for f in fields:
        by_lower.setdefault(f.lower(), f)
        by_lower.setdefault(f.split(".")[-1].lower(), f)
    mapping = {}
    for role, cands in CANDIDATES.items():
        if role in overrides:
            mapping[role] = overrides[role]
            continue
        for c in cands:
            f = by_lower.get(c.lower())
            if f and fields[f] / n >= 0.5 and f not in mapping.values():
                mapping[role] = f
                break
    return mapping, {f: fields[f] / n for f in sorted(fields)}


def side_of(value):
    if value is None:
        return 0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return 1 if value > 0 else -1 if value < 0 else 0
    tokens = set(re.split(r"[^a-z0-9+\-]+", str(value).lower())) - {""}
    is_long, is_short = bool(tokens & LONG_WORDS), bool(tokens & SHORT_WORDS)
    return 1 if is_long and not is_short else -1 if is_short and not is_long else 0


def parse_time_ms(v):
    """Retourne (ms UTC, fuseau_absent) ou (None, False)."""
    if v is None or v == "":
        return None, False
    if isinstance(v, bool):
        return None, False
    if isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"\d+(\.\d+)?", v.strip())):
        x = float(v)
        if x > 1e17:
            return int(x / 1e6), False
        if x > 1e14:
            return int(x / 1e3), False
        if x > 1e11:
            return int(x), False
        if x > 1e8:
            return int(x * 1000), False
        return None, False
    s = str(v).strip().replace("Z", "+00:00")
    try:
        t = dt.datetime.fromisoformat(s)
    except ValueError:
        try:
            import pandas as pd
            t = pd.Timestamp(str(v)).to_pydatetime()
        except Exception:
            return None, False
    naive = t.tzinfo is None
    if naive:
        t = t.replace(tzinfo=dt.timezone.utc)
    return int(t.timestamp() * 1000), naive


def to_float(v):
    try:
        x = float(v)
        return x if math.isfinite(x) and x > 0 else None
    except (TypeError, ValueError):
        return None


def iso(ms):
    if ms is None:
        return ""
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- Binance


def normalize_symbol(raw, spot: set, default_quote: str):
    if raw is None:
        return None, False
    s = str(raw).upper().strip().split(":")[-1]
    s = re.sub(r"(\.P|[-_]?PERP(ETUAL)?|[-_]SWAP|[-_]SPOT)$", "", s)
    s = re.sub(r"[^A-Z0-9]", "", s)
    if s in spot:
        return s, False
    if default_quote and s + default_quote in spot:
        return s + default_quote, True
    return None, False


class Candles:
    def __init__(self, rows):
        a = np.array(sorted({r[0]: r for r in rows}.values()), dtype=float) if rows else np.zeros((0, 5))
        self.t = a[:, 0].astype(np.int64)
        self.o, self.h, self.l, self.c = a[:, 1], a[:, 2], a[:, 3], a[:, 4]

    def __len__(self):
        return len(self.t)

    def find(self, t_ms):
        i = int(np.searchsorted(self.t, t_ms, "left"))
        return i if i < len(self.t) and self.t[i] == t_ms else -1

    def entry_index(self, det_ms):
        """Premiere bougie qui commence strictement apres l'heure de detection."""
        i = int(np.searchsorted(self.t, det_ms, "right"))
        return i if i < len(self.t) else -1


class Binance:
    def __init__(self, http: Http, cache: Cache, base: str, offline: bool):
        self.http, self.cache, self.base, self.offline = http, cache, base.rstrip("/"), offline

    def ping(self):
        r = self.http.get(self.base + "/api/v3/ping", retries=2)
        return r.status_code

    def server_time(self):
        """Heure Binance ; hors ligne, celle de la derniere execution en ligne, pour rejouer a l'identique."""
        if self.offline:
            cached = self.cache.get_misc("server_time", None)
            if cached is None:
                raise Stop("mode hors ligne : aucune execution en ligne en cache", 4)
            return int(cached)
        r = self.http.get(self.base + "/api/v3/time")
        now = int(r.json()["serverTime"])
        self.cache.put_misc("server_time", now)
        return now

    def spot_symbols(self):
        cached = self.cache.get_misc("exchangeInfo", None if self.offline else DAY_MS / 1000)
        if cached is None:
            r = self.http.get(self.base + "/api/v3/exchangeInfo")
            if r.status_code != 200:
                raise Stop(f"Binance exchangeInfo : HTTP {r.status_code}", 4)
            cached = {s["symbol"]: s["status"] for s in r.json()["symbols"]}
            self.cache.put_misc("exchangeInfo", cached)
        return cached

    def block(self, symbol, block, now_ms):
        rows = self.cache.get_klines(symbol, block)
        if rows is not None:
            return rows
        start = block * BLOCK_MS
        end = start + BLOCK_MS - 1
        r = self.http.get(self.base + "/api/v3/klines", params={
            "symbol": symbol, "interval": "1m", "startTime": start, "endTime": end, "limit": KLINE_LIMIT})
        if r.status_code != 200:
            raise Stop(f"Binance klines {symbol} : HTTP {r.status_code} {r.text[:200]}", 4)
        rows = [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])] for k in r.json()]
        if end < now_ms - 2 * MIN_MS:  # bloc clos : immuable, on le garde
            self.cache.put_klines(symbol, block, rows)
        return rows

    def candles(self, symbol, intervals, now_ms):
        blocks = set()
        for a, b in intervals:
            b = min(b, now_ms)
            if b > a:
                blocks.update(range(a // BLOCK_MS, b // BLOCK_MS + 1))
        rows = []
        for blk in sorted(blocks):
            rows.extend(self.block(symbol, blk, now_ms))
        return Candles(rows)

    def daily(self, symbol, start_ms, end_ms):
        name = f"daily_{symbol}_{start_ms // DAY_MS}_{end_ms // DAY_MS}"
        cached = self.cache.get_misc(name, None if self.offline else 6 * 3600)
        if cached is not None:
            return cached
        rows, cur = [], start_ms
        while cur < end_ms:
            r = self.http.get(self.base + "/api/v3/klines", params={
                "symbol": symbol, "interval": "1d", "startTime": cur, "endTime": end_ms, "limit": 1000})
            data = r.json() if r.status_code == 200 else []
            if not data:
                break
            rows.extend([[int(k[0]), float(k[1]), float(k[4])] for k in data])
            cur = int(data[-1][0]) + DAY_MS
        self.cache.put_misc(name, rows)
        return rows


# --------------------------------------------------------------------------- calculs


def evaluate(c: Candles, i: int, side: int, hours: int):
    """Position ouverte a l'ouverture de la bougie i, fermee a la cloture de celle qui
    commence a entree + H - 1 min. Retourne None si cette bougie n'existe pas."""
    entry_t = int(c.t[i])
    j = c.find(entry_t + hours * HOUR_MS - MIN_MS)
    if j < 0:
        return None
    entry, exit_ = c.o[i], c.c[j]
    hi, lo = c.h[i:j + 1].max(), c.l[i:j + 1].min()
    gross, up, down = exit_ / entry - 1, hi / entry - 1, lo / entry - 1
    if side < 0:
        gross, up, down = -gross, -down, -up
    return {"exit": float(exit_), "gross": float(gross), "up": float(up), "down": float(down),
            "missing": hours * 60 - (j - i + 1)}


def stable_int(text) -> int:
    return int(hashlib.sha256(str(text).encode()).hexdigest()[:12], 16)


def baseline(c: Candles, det_ms, side, rid, seed, n, window_days, cost):
    rng = np.random.default_rng([seed, stable_int(rid)])
    if len(c) == 0:
        return None
    lo = max(det_ms - window_days * DAY_MS, int(c.t[0])) // MIN_MS
    hi = min(det_ms + window_days * DAY_MS, int(c.t[-1]) - 24 * HOUR_MS + MIN_MS) // MIN_MS
    if hi <= lo:
        return None
    out = {h: [] for h in HORIZONS}
    tries = 0
    while len(out[HORIZONS[0]]) < n and tries < n * 20:
        tries += 1
        i = c.find(int(rng.integers(lo, hi + 1)) * MIN_MS)
        if i < 0:
            continue
        res = {h: evaluate(c, i, side, h) for h in HORIZONS}
        if any(r is None for r in res.values()):
            continue
        for h in HORIZONS:
            out[h].append(res[h]["gross"] - cost)
    if len(out[HORIZONS[0]]) < n // 2:
        return None
    return {h: np.array(v) for h, v in out.items()}


def mark_duplicates(rows, hours):
    """Par paire : on garde la premiere detection d'une serie et on ecarte les suivantes
    tant que la position precedente (entree + H) est ouverte. Retourne aussi les
    repetitions brutes (detection precedente sur la paire a moins de H)."""
    by_pair = defaultdict(list)
    for r in rows:
        by_pair[r["paire_binance"]].append(r)
    dup, rep = {}, {}
    for lst in by_pair.values():
        lst.sort(key=lambda r: r["_det_ms"])
        open_until, prev = -1, None
        for r in lst:
            dup[r["_key"]] = r["_det_ms"] < open_until
            rep[r["_key"]] = prev is not None and r["_det_ms"] - prev < hours * HOUR_MS
            prev = r["_det_ms"]
            if not dup[r["_key"]]:
                open_until = r["_entry_ms"] + hours * HOUR_MS
    return dup, rep


def boot_means(x, rng, B):
    n = len(x)
    out = np.empty(B)
    step = max(1, min(B, 2_000_000 // max(n, 1)))
    for s in range(0, B, step):
        k = min(step, B - s)
        out[s:s + k] = x[rng.integers(0, n, (k, n))].mean(axis=1)
    return out


def boot_ci(x, rng, B):
    if len(x) < 2:
        return (float("nan"), float("nan"))
    lo, hi = np.percentile(boot_means(x, rng, B), [2.5, 97.5])
    return float(lo), float(hi)


def day_block_ci(x, days, rng, B):
    """IC de la moyenne en reechantillonnant des journees entieres (detections d'un meme
    jour correlees par le marche)."""
    uniq, inv = np.unique(days, return_inverse=True)
    if len(uniq) < 5:
        return (float("nan"), float("nan"))
    sums = np.bincount(inv, weights=x)
    cnts = np.bincount(inv).astype(float)
    m = len(uniq)
    out = np.empty(B)
    step = max(1, 2_000_000 // m)
    for s in range(0, B, step):
        k = min(step, B - s)
        idx = rng.integers(0, m, (k, m))
        out[s:s + k] = sums[idx].sum(1) / cnts[idx].sum(1)
    lo, hi = np.percentile(out, [2.5, 97.5])
    return float(lo), float(hi)


def describe(rows, h, cost, seed, label, B, with_day_ci=False):
    net = np.array([r[f"_net_{h}"] for r in rows])
    n = len(net)
    res = {"groupe": label, "n": n, "non_concluant": n < MIN_N}
    if n == 0:
        return res
    rng = np.random.default_rng([seed, stable_int(f"{label}|{h}|{cost}")])
    srt = np.sort(net)[::-1]
    res.update({
        "mediane": float(np.median(net)),
        "moyenne": float(net.mean()),
        "moyenne_sans_top3": float(srt[3:].mean()) if n > 3 else float("nan"),
        "gagnants": float((net > 0).mean()),
        "med_hausse_max": float(np.median([r[f"_up_{h}"] for r in rows])),
        "med_baisse_max": float(np.median([r[f"_down_{h}"] for r in rows])),
        "ic": boot_ci(net, rng, B),
    })
    if with_day_ci:
        days = np.array([r["_det_ms"] // DAY_MS for r in rows])
        res["ic_jours"] = day_block_ci(net, days, rng, B)
    return res


def compare_to_random(rows, h, seed, B):
    rows = [r for r in rows if r.get("_base") is not None]
    if len(rows) < 2:
        return None
    setup = np.array([r[f"_net_{h}"] for r in rows])
    pooled = np.concatenate([r["_base"][h] for r in rows])
    base_mean = np.array([r["_base"][h].mean() for r in rows])
    base_med = np.array([np.median(r["_base"][h]) for r in rows])
    diff = setup - base_mean
    rng = np.random.default_rng([seed, stable_int(f"cmp|{h}|{len(rows)}")])
    q = [10, 25, 50, 75, 90]
    res = {
        "n": len(rows), "n_hasard": len(pooled),
        "q_setups": np.percentile(setup, q).tolist(), "q_hasard": np.percentile(pooled, q).tolist(),
        "moy_setups": float(setup.mean()), "moy_hasard": float(pooled.mean()),
        "gagnants_setups": float((setup > 0).mean()), "gagnants_hasard": float((pooled > 0).mean()),
        "ecart_moyen": float(diff.mean()), "ic_ecart": boot_ci(diff, rng, B),
        "ecart_median": float(np.median(diff)),
        "part_bat_hasard": float((setup > base_med).mean()),
        "ks_p": None, "mw_p": None, "wilcoxon_p": None, "binom_p": None,
    }
    if sps is not None:
        res["ks_p"] = float(sps.ks_2samp(setup, pooled).pvalue)
        res["mw_p"] = float(sps.mannwhitneyu(setup, pooled, alternative="two-sided").pvalue)
        if np.any(diff != 0):
            res["wilcoxon_p"] = float(sps.wilcoxon(diff).pvalue)
        res["binom_p"] = float(sps.binomtest(int((setup > base_med).sum()), len(setup), 0.5).pvalue)
    lo, hi = res["ic_ecart"]
    res["significatif"] = (lo > 0 or hi < 0) and (res["wilcoxon_p"] is None or res["wilcoxon_p"] < 0.05)
    return res


# --------------------------------------------------------------------------- rapport

def pct(x, d=2):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/d"
    return f"{x * 100:+.{d}f} %".replace(".", ",")


def pval(p):
    return "n/d" if p is None else ("< 0,001" if p < 0.001 else f"{p:.3f}")


def stats_table(stats):
    out = ["| Groupe | n | Médiane | Moyenne | IC 95 % moyenne | Moy. sans top 3 | Gagnants nets | Méd. hausse max | Méd. baisse max |",
           "|---|---:|---:|---:|---|---:|---:|---:|---:|"]
    for s in stats:
        if s["n"] == 0:
            out.append(f"| {s['groupe']} | 0 | | | | | | | |")
            continue
        flag = " ⚠ non concluant" if s["non_concluant"] else ""
        ic = f"[{pct(s['ic'][0])} ; {pct(s['ic'][1])}]"
        if "ic_jours" in s:
            ic += f"<br>par jour : [{pct(s['ic_jours'][0])} ; {pct(s['ic_jours'][1])}]"
        out.append(f"| {s['groupe']}{flag} | {s['n']} | {pct(s['mediane'])} | {pct(s['moyenne'])} | {ic} | "
                   f"{pct(s['moyenne_sans_top3'])} | {s['gagnants'] * 100:.1f} % | {pct(s['med_hausse_max'])} | "
                   f"{pct(s['med_baisse_max'])} |")
    return "\n".join(out)


# --------------------------------------------------------------------------- programme principal


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api-url", default=os.environ.get("COINBEACON_API_URL"), help="endpoint des setups")
    p.add_argument("--api-param", action="append", default=[], metavar="CLE=VALEUR", help="parametre fixe de requete")
    p.add_argument("--auth-header", default=os.environ.get("COINBEACON_AUTH_HEADER", "Authorization"))
    p.add_argument("--auth-scheme", default=os.environ.get("COINBEACON_AUTH_SCHEME", "Bearer"),
                   help="prefixe du jeton dans l'en-tete ; chaine vide pour le jeton seul")
    p.add_argument("--auth-query-param", default=os.environ.get("COINBEACON_AUTH_QUERY_PARAM"),
                   help="envoyer le jeton en parametre de requete plutot qu'en en-tete")
    p.add_argument("--page-param", help="forcer une pagination par numero de page (ex. page)")
    p.add_argument("--start-page", type=int, default=1)
    p.add_argument("--offset-param", help="forcer une pagination par decalage (ex. offset)")
    p.add_argument("--limit-param", help="nom du parametre de taille de page (ex. limit)")
    p.add_argument("--limit", type=int, help="taille de page demandee")
    p.add_argument("--cursor-param", default="cursor")
    p.add_argument("--max-pages", type=int, default=100_000)
    p.add_argument("--field-map", default=os.environ.get("COINBEACON_FIELD_MAP", "{}"),
                   help='JSON, ex. {"pair":"market.symbol","time":"detected_at","side":"direction"}')
    p.add_argument("--default-quote", default="USDT", help="devise ajoutee si la paire est donnee sans cotation")
    p.add_argument("--default-side", choices=["long", "short"], help="sens a supposer si l'API n'en fournit pas")
    p.add_argument("--binance-base", default=os.environ.get("BINANCE_BASE_URL", "https://api.binance.com"))
    p.add_argument("--cost", type=float, default=0.003, help="cout aller-retour (0.003 = 0,1 %% x2 + 0,05 %% x2)")
    p.add_argument("--n-random", type=int, default=20)
    p.add_argument("--window-days", type=float, default=7)
    p.add_argument("--no-random", action="store_true", help="sauter le point de comparaison (plus rapide)")
    p.add_argument("--bootstrap", type=int, default=10_000)
    p.add_argument("--seed", type=int, default=20261010)
    p.add_argument("--cache-dir", type=Path, default=HERE / ".cache")
    p.add_argument("--out-dir", type=Path, default=HERE / "resultats")
    p.add_argument("--api-cache-hours", type=float, default=6)
    p.add_argument("--refresh-api", action="store_true", help="ignorer le cache des pages de l'API")
    p.add_argument("--offline", action="store_true", help="tout lire depuis le cache, sans reseau")
    p.add_argument("--check-only", action="store_true", help="faire les trois controles puis s'arreter")
    p.add_argument("--observations", type=Path,
                   help="lire les setups collectes par collecteur.py (observations.jsonl) au lieu de l'API")
    p.add_argument("--heure-detection", choices=["premiere_vue", "declenchement"], default="premiere_vue",
                   help="premiere_vue : moment ou le collecteur a vu le setup (realiste) ; declenchement : "
                        "cloture de la bougie de declenchement (theorique, un peu optimiste)")
    p.add_argument("--bars-max", type=int, default=1,
                   help="ecarter les setups vus pour la premiere fois plus de N bougies apres leur "
                        "declenchement : ils ont survecu jusque-la, les garder recree le biais de survie")
    return p.parse_args(argv)


def load_observations(args):
    """Setups enregistres par collecteur.py, a leur premiere apparition."""
    path = args.observations
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    records, biases = [], []
    late = no_trigger = 0
    for o in rows:
        rec = dict(o.get("ligne") or {})
        rec.update({"_cle": o["cle"], "_symbole": o["symbole"],
                    "_archetype": f"{o.get('archetype')} {o.get('tf')}"})
        bars = o.get("bars_a_la_premiere_vue")
        if args.heure_detection == "premiere_vue":
            rec["_detection_ms"] = o["premiere_vue_ms"]
        elif o.get("declenchement_cloture_ms") is not None:
            rec["_detection_ms"] = o["declenchement_cloture_ms"]
        else:
            rec["_detection_ms"] = None
            rec["_motif"] = "exclu : pas de bougie de declenchement (archetype sans declencheur)"
        if bars is None:
            no_trigger += 1
        elif bars > args.bars_max and "_motif" not in rec:
            late += 1
            rec["_motif"] = f"exclu : vu pour la premiere fois {bars} bougies apres le declenchement (biais de survie)"
        records.append(rec)
    if late:
        biases.append(f"{late} setups vus pour la premiere fois plus de {args.bars_max} bougie(s) apres leur "
                      "declenchement sont ecartes : ils avaient deja survecu, les garder favoriserait ceux qui ont "
                      "marche. C'est le cas de tout le tableau present au premier appel et apres chaque coupure.")
    if no_trigger:
        biases.append(f"{no_trigger} setups sans bougie de declenchement (barsSinceTrigger nul).")
    if args.heure_detection == "declenchement":
        biases.append("Heure de detection = cloture de la bougie de declenchement : le collecteur ne voit le setup "
                      "qu'environ 90 s plus tard, donc l'entree mesuree est un peu plus tot que realisable.")
    calls_path = path.parent / "appels.jsonl"
    if calls_path.exists():
        calls = [json.loads(line) for line in open(calls_path, encoding="utf-8") if line.strip()]
        ok = [c for c in calls if c.get("http") == 200]
        errs = len(calls) - len(ok)
        trunc = sum(1 for c in ok if c.get("tronque"))
        biases.append(f"Collecte : {len(calls)} appels, {errs} en erreur, {trunc} reponses tronquees par l'API "
                      "(plus de 800 candidats : des setups ont pu echapper a la collecte).")
        by_tf = defaultdict(list)
        for c in ok:
            by_tf[c["tf"]].append(c["t"])
        for tf, ts in sorted(by_tf.items()):
            ts.sort()
            step = int(tf[:-1]) * {"m": MIN_MS, "h": HOUR_MS, "d": DAY_MS, "w": 7 * DAY_MS}[tf[-1]]
            holes = [(a, b) for a, b in zip(ts, ts[1:]) if b - a > 1.5 * step]
            if holes:
                missed = sum(round((b - a) / step) - 1 for a, b in holes)
                biases.append(f"Trous de collecte en {tf} : {len(holes)} coupures, environ {missed} clotures "
                              f"manquees (la plus longue commence le {iso(max(holes, key=lambda x: x[1]-x[0])[0])}).")
    pmeta = {"pages": 0, "methode": f"collecte locale ({path.name})", "total_annonce": None,
             "tronque": False, "boucle": False}
    return records, pmeta, biases


def preflight(args, token, api: SetupsApi, binance: Binance):
    checks = []
    if not token:
        raise Stop("ECHEC controle 1/3 : la variable d'environnement COINBEACON_TOKEN est absente ou vide", 2)
    checks.append("1/3 jeton COINBEACON_TOKEN : present")
    if not args.api_url:
        raise Stop("ECHEC controle 2/3 : URL de l'API inconnue (COINBEACON_API_URL ou --api-url)", 3)
    try:
        status, payload, _ = api.get(args.api_url, api.first_params(), use_cache=False)
    except Stop as e:
        raise Stop(f"ECHEC controle 2/3 : API CoinBeacon injoignable ({e})", 3)
    if status != 200:
        raise Stop(f"ECHEC controle 2/3 : API CoinBeacon repond HTTP {status}", 3)
    if payload is None:
        raise Stop("ECHEC controle 2/3 : API CoinBeacon repond HTTP 200 mais pas en JSON", 3)
    checks.append(f"2/3 API CoinBeacon : HTTP {status}, {len(extract_records(payload))} detections sur la premiere page")
    try:
        code = binance.ping()
    except Stop as e:
        raise Stop(f"ECHEC controle 3/3 : {binance.base} injoignable ({e})", 4)
    if code != 200:
        raise Stop(f"ECHEC controle 3/3 : {binance.base} repond HTTP {code}"
                   + (" (restriction geographique de Binance)" if code == 451 else ""), 4)
    checks.append(f"3/3 {binance.base} : HTTP {code}")
    for c in checks:
        log("  OK", c)
    return checks


def main(argv=None):
    args = parse_args(argv)
    token = os.environ.get("COINBEACON_TOKEN", "")
    if token:
        _SECRETS.append(token)
    overrides = json.loads(args.field_map)
    cache = Cache(args.cache_dir)
    http = Http(args.offline)
    api = SetupsApi(args, token, http, cache)
    binance = Binance(http, cache, args.binance_base, args.offline)
    notes = []

    log("Controles prealables")
    if args.observations and not args.offline:
        code = binance.ping()
        if code != 200:
            raise Stop(f"ECHEC controle Binance : {binance.base} repond HTTP {code}", 4)
        checks = [f"source : setups collectes ({args.observations}), API CoinBeacon non interrogee",
                  f"{binance.base} : HTTP {code}"]
        for c in checks:
            log("  OK", c)
    elif args.offline:
        checks = ["mode hors ligne : controles reseau sautes, tout est lu dans le cache"]
        if not args.api_url and not args.observations:
            raise Stop("--api-url requis meme hors ligne (cle du cache)", 3)
    else:
        checks = preflight(args, token, api, binance)
    if args.check_only:
        return 0

    # ---- 1. detections
    obs_biases = []
    if args.observations:
        log(f"Lecture des setups collectes : {args.observations}")
        records, pmeta, obs_biases = load_observations(args)
        overrides = {"id": "_cle", "time": "_detection_ms", "pair": "_symbole", "type": "_archetype", **overrides}
    else:
        log("Recuperation de l'historique des setups")
        records, pmeta = api.fetch_all()
    if not records:
        raise Stop("l'API n'a renvoye aucune detection", 3)
    flat = [flatten(r) for r in records]
    mapping, fill = detect_mapping(flat, overrides)
    for role in ("pair", "time"):
        if role not in mapping:
            raise Stop(f"champ '{role}' introuvable automatiquement. Champs fournis : {', '.join(fill)}. "
                       f"Preciser avec --field-map", 6)
    log(f"  {len(flat)} detections, {pmeta['pages']} pages ; correspondance : {mapping}")

    now_ms = binance.server_time()
    spot = binance.spot_symbols()
    spot_set = set(spot)

    dets, naive_tz, side_inferred = [], 0, 0
    if "side" not in mapping and "type" in mapping:
        vals = {str(r.get(mapping["type"])).lower() for r in flat}
        if vals and all(side_of(v) != 0 for v in vals):
            mapping["side"] = mapping["type"]
            notes.append("Le champ de type ne contient que des sens : il sert aussi de sens.")
    for k, r in enumerate(flat):
        rid = r.get(mapping.get("id")) if "id" in mapping else None
        rid = str(rid) if rid not in (None, "") else f"ligne{k + 1}"
        det_ms, naive = parse_time_ms(r.get(mapping["time"]))
        naive_tz += bool(naive)
        typ = str(r.get(mapping["type"], "")) if "type" in mapping else "(sans type)"
        side = side_of(r.get(mapping["side"])) if "side" in mapping else 0
        if side == 0 and "type" in mapping:
            side = side_of(typ)
            side_inferred += side != 0
        if side == 0 and args.default_side:
            side = 1 if args.default_side == "long" else -1
        sym, quote_assumed = normalize_symbol(r.get(mapping["pair"]), spot_set, args.default_quote)
        dets.append({
            "_key": k, "id": rid, "paire_api": r.get(mapping["pair"]), "paire_binance": sym or "",
            "_quote_assumed": quote_assumed, "type": typ or "(vide)",
            "sens": {1: "achat", -1: "vente", 0: "inconnu"}[side], "_side": side,
            "_det_ms": det_ms, "heure_detection_utc": iso(det_ms), "_raw_time": r.get(mapping["time"]),
            "_api_price": to_float(r.get(mapping["price"])) if "price" in mapping else None,
            "_api_exit": {h: to_float(r.get(mapping[f"exit_{h}h"])) if f"exit_{h}h" in mapping else None for h in HORIZONS},
            "_status": r.get(mapping["status"]) if "status" in mapping else None,
            "statut": r.get("_motif", ""),
        })

    # ---- 2. entonnoir d'exclusion avant prix
    missing_pairs = Counter()
    for d in dets:
        if d["statut"]:
            continue
        if d["_det_ms"] is None:
            d["statut"] = "exclu : heure illisible"
        elif not d["paire_binance"]:
            d["statut"] = "exclu : paire introuvable sur Binance spot"
            missing_pairs[str(d["paire_api"])] += 1
        elif d["_side"] == 0:
            d["statut"] = "exclu : sens inconnu"
        elif d["_det_ms"] > now_ms:
            d["statut"] = "exclu : heure dans le futur"
        elif d["_det_ms"] + MIN_MS + 24 * HOUR_MS > now_ms:
            d["statut"] = "exclu : horizon 24 h non écoulé"
    # ---- 3. prix
    by_sym = defaultdict(list)
    for d in dets:
        if not d["statut"]:
            by_sym[d["paire_binance"]].append(d)
    span = (args.window_days * DAY_MS if not args.no_random else 0)
    log(f"Bougies 1 min Binance pour {len(by_sym)} paires")
    tz_probe = []
    for n_sym, (sym, lst) in enumerate(sorted(by_sym.items()), 1):
        intervals = sorted((d["_det_ms"] - span - 2 * MIN_MS, d["_det_ms"] + span + 24 * HOUR_MS + 2 * MIN_MS) for d in lst)
        c = binance.candles(sym, intervals, now_ms)
        if n_sym % 10 == 0 or n_sym == len(by_sym):
            log(f"  {n_sym}/{len(by_sym)} paires, {http.calls} requetes")
        for d in lst:
            i = c.entry_index(d["_det_ms"])
            if i < 0 or c.t[i] - d["_det_ms"] > MIN_MS:
                before_listing = len(c) == 0 or d["_det_ms"] < c.t[0]
                d["statut"] = ("exclu : avant la cotation ou pair sans bougies" if before_listing
                               else "exclu : aucune bougie à l'heure de détection (trou)")
                continue
            d["_entry_ms"] = int(c.t[i])
            d["heure_entree_utc"] = iso(d["_entry_ms"])
            d["prix_entree"] = float(c.o[i])
            res = {h: evaluate(c, i, d["_side"], h) for h in HORIZONS}
            bad = [h for h in HORIZONS if res[h] is None]
            if bad:
                d["statut"] = f"exclu : bougie de sortie {bad[0]} h absente"
                continue
            for h in HORIZONS:
                r = res[h]
                d[f"_bin_exit_{h}"] = r["exit"]
                d[f"_gross_{h}"], d[f"_up_{h}"], d[f"_down_{h}"] = r["gross"], r["up"], r["down"]
                d[f"bougies_manquantes_{h}h"] = r["missing"]
            # controle d'alignement horaire avec le prix fourni par l'API
            if d["_api_price"]:
                j = c.find((d["_det_ms"] // MIN_MS) * MIN_MS)
                offs = {}
                for off in range(-12, 13):
                    jj = c.find((d["_det_ms"] // MIN_MS) * MIN_MS + off * HOUR_MS)
                    if jj >= 0:
                        offs[off] = abs(c.c[jj] / d["_api_price"] - 1)
                if j >= 0 and offs:
                    tz_probe.append((abs(c.c[j] / d["_api_price"] - 1), min(offs, key=offs.get)))
            if not args.no_random:
                d["_base"] = baseline(c, d["_det_ms"], d["_side"], d["id"], args.seed, args.n_random,
                                      args.window_days, args.cost)
            d["statut"] = "inclus"

    included = [d for d in dets if d["statut"] == "inclus"]
    if not included:
        raise Stop("aucune détection exploitable après exclusions", 7)

    # ---- 4. source des prix de sortie : API si fournis et confirmes par Binance
    price_source, api_check = "Binance (bougies 1 min)", None
    if all(f"exit_{h}h" in mapping for h in HORIZONS):
        rng = np.random.default_rng(args.seed)
        sample = [included[k] for k in rng.choice(len(included), min(50, len(included)), replace=False)]
        diffs = [abs(d["_api_exit"][h] / d[f"_bin_exit_{h}"] - 1) for d in sample for h in HORIZONS if d["_api_exit"][h]]
        if diffs:
            api_check = {"n": len(diffs), "mediane": float(np.median(diffs)), "max": float(np.max(diffs))}
            if api_check["mediane"] < 0.002:
                price_source = "API CoinBeacon (verifiee sur Binance)"
                for d in included:
                    for h in HORIZONS:
                        ex = d["_api_exit"][h]
                        if ex:
                            d[f"_exit_{h}"] = ex
                            g = ex / d["prix_entree"] - 1
                            d[f"_gross_{h}"] = -g if d["_side"] < 0 else g
    for d in included:
        for h in HORIZONS:
            d.setdefault(f"_exit_{h}", d[f"_bin_exit_{h}"])
            d[f"_net_{h}"] = d[f"_gross_{h}"] - args.cost

    # ---- 5. doublons
    dup_info = {}
    for h in HORIZONS:
        dup, rep = mark_duplicates(included, h)
        for d in included:
            d[f"_dup_{h}"] = dup[d["_key"]]
            d[f"_rep_{h}"] = rep[d["_key"]]
        dup_info[h] = (sum(dup.values()), sum(rep.values()))

    # ---- 6. statistiques
    def groups(rows):
        out = [("Tous (achat + vente)", rows),
               ("Acheteurs", [r for r in rows if r["_side"] > 0]),
               ("Vendeurs (positions courtes)", [r for r in rows if r["_side"] < 0])]
        for typ in sorted({r["type"] for r in rows}):
            for side, name in ((1, "achat"), (-1, "vente")):
                sub = [r for r in rows if r["type"] == typ and r["_side"] == side]
                if sub:
                    out.append((f"{typ} · {name}", sub))
        return out

    results = {}
    for h in HORIZONS:
        for version in ("avec", "sans"):
            rows = included if version == "avec" else [r for r in included if not r[f"_dup_{h}"]]
            stats = [describe(sub, h, args.cost, args.seed, name, args.bootstrap, with_day_ci=k < 3)
                     for k, (name, sub) in enumerate(groups(rows))]
            cmp_ = {}
            if not args.no_random:
                for name, sub in groups(rows)[:3]:
                    cmp_[name] = compare_to_random(sub, h, args.seed, args.bootstrap)
            sens = {}
            for name, sub in groups(rows)[:3]:
                if sub:
                    g = np.array([r[f"_gross_{h}"] for r in sub])
                    sens[name] = (float(g.mean()), float(np.median(g)))
            results[(h, version)] = {"stats": stats, "cmp": cmp_, "sens": sens, "n": len(rows)}

    # ---- 7. biais
    det_times = sorted(d["_det_ms"] for d in dets if d["_det_ms"] is not None)
    inc_times = sorted(d["_det_ms"] for d in included)
    first, last = det_times[0], det_times[-1]
    period_days = (last - first) / DAY_MS
    biases = []
    if pmeta["tronque"]:
        biases.append("Pagination arrêtée par la limite --max-pages : historique tronqué.")
    if pmeta["boucle"]:
        biases.append("La pagination a renvoyé des pages déjà vues : historique peut-être incomplet.")
    if pmeta["total_annonce"] is not None and pmeta["total_annonce"] != len(records):
        biases.append(f"L'API annonce {pmeta['total_annonce']} détections, {len(records)} récupérées.")
    if period_days < 90:
        biases.append(f"Période courte : {period_days:.0f} jours. Un seul régime de marché est probable.")
    big = [(iso(a)[:10], round((b - a) / DAY_MS, 1)) for a, b in zip(det_times, det_times[1:]) if (b - a) > 3 * DAY_MS]
    if big:
        biases.append("Trous de plus de 3 jours sans détection : "
                      + ", ".join(f"{d} ({g} j)" for d, g in big[:10]) + (" ..." if len(big) > 10 else ""))
    num_ids = [int(d["id"]) for d in dets if str(d["id"]).isdigit()]
    if len(num_ids) > 10:
        span_ids = max(num_ids) - min(num_ids) + 1
        missing_ids = span_ids - len(set(num_ids))
        if missing_ids > 0:
            biases.append(f"Identifiants numériques : {missing_ids} absents sur {span_ids} "
                          f"({missing_ids / span_ids * 100:.1f} %) entre {min(num_ids)} et {max(num_ids)}. "
                          "Setups supprimés de l'API ou numérotation partagée : à vérifier.")
    biases.extend(obs_biases)
    if not args.observations:  # la collecte enregistre deja chaque setup a sa premiere apparition
        snap_dir = args.out_dir / "instantanes"
        snap_dir.mkdir(parents=True, exist_ok=True)
        previous = sorted(snap_dir.glob("ids_*.json"))
        current_ids = {d["id"]: d["heure_detection_utc"] for d in dets}
        disappeared = []
        if previous:
            old = json.loads(previous[-1].read_text())
            disappeared = [i for i, t in old.items() if i not in current_ids and t and t <= iso(last)]
            if disappeared:
                biases.append(f"{len(disappeared)} détections présentes dans l'instantané {previous[-1].name} "
                              "ont disparu de l'API : biais de survie probable.")
        else:
            biases.append("Premier instantané des identifiants : impossible de savoir si des setups ont déjà été retirés. "
                          "Relancer le script plus tard permettra de le détecter.")
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M")
        (snap_dir / f"ids_{stamp}.json").write_text(json.dumps(current_ids, indent=0, sort_keys=True))
    if naive_tz:
        biases.append(f"{naive_tz} heures de détection sans fuseau : supposées en UTC.")
    if tz_probe:
        med = float(np.median([p[0] for p in tz_probe]))
        best = Counter(p[1] for p in tz_probe).most_common(1)[0]
        line = (f"Prix de l'API à l'heure de détection vs clôture Binance de la même minute : écart médian {med * 100:.3f} % "
                f"sur {len(tz_probe)} détections.")
        if best[0] != 0 and best[1] > len(tz_probe) / 2:
            line += f" ⚠ Le meilleur alignement est obtenu avec un décalage de {best[0]:+d} h : erreur de fuseau probable."
        biases.append(line)
    seconds = Counter((t // 1000) % 60 == 0 for t in det_times)
    if seconds[True] == len(det_times):
        gran = Counter(next(m for m in (60, 15, 5, 1) if (t // MIN_MS) % m == 0) for t in det_times)
        biases.append("Toutes les heures de détection tombent à la minute pile "
                      f"(répartition multiple de 60/15/5/1 min : {dict(gran)}) : les détections semblent émises à la "
                      "clôture d'une bougie ; l'entrée à la minute suivante est donc réaliste si l'alerte est immédiate.")
    if any(d["_status"] is not None for d in dets):
        st = Counter(str(d["_status"]) for d in dets)
        biases.append(f"Champ de statut fourni ({mapping['status']}) : {dict(st.most_common(8))}. "
                      "Si l'API ne garde que certains statuts, l'échantillon est biaisé.")
    pair_counts = Counter(d["paire_binance"] for d in included)
    top = pair_counts.most_common(5)
    top_share = sum(c for _, c in top) / len(included)
    hhi = sum((c / len(included)) ** 2 for c in pair_counts.values())
    conc_line = (f"Concentration : {len(pair_counts)} paires ; les 5 premières font {top_share * 100:.0f} % des "
                 f"détections ({', '.join(f'{p} {c}' for p, c in top)}) ; indice HHI {hhi:.3f}.")
    if top_share > 0.5 or hhi > 0.1:
        conc_line = "⚠ " + conc_line
    biases.append(conc_line)
    excl_top = {}
    top3 = {p for p, _ in pair_counts.most_common(3)}
    for h in HORIZONS:
        rest = [r[f"_net_{h}"] for r in included if r["paire_binance"] not in top3]
        excl_top[h] = (len(rest), float(np.mean(rest)) if rest else float("nan"))
    if any(d["_quote_assumed"] for d in dets):
        biases.append(f"{sum(d['_quote_assumed'] for d in dets)} paires données sans devise de cotation : "
                      f"{args.default_quote} supposée.")
    if side_inferred:
        biases.append(f"{side_inferred} sens déduits du nom du type de setup.")
    if args.default_side:
        biases.append(f"Sens absent pour certaines détections : '{args.default_side}' supposé (--default-side).")
    gappy = sum(1 for d in included if d.get("bougies_manquantes_24h", 0) > 0)
    if gappy:
        biases.append(f"{gappy} positions avec des minutes sans bougie entre l'entrée et 24 h (trous Binance).")
    regime = None
    try:
        daily = binance.daily("BTCUSDT", first - DAY_MS, min(last + 2 * DAY_MS, now_ms))
        if len(daily) >= 2:
            btc = daily[-1][2] / daily[0][1] - 1
            regime = btc
            biases.append(f"Régime de marché : BTCUSDT {pct(btc, 1)} sur la période des détections. "
                          + ("Tendance marquée : les acheteurs et les vendeurs ne sont pas testés dans un marché neutre."
                             if abs(btc) > 0.2 else "Variation modérée."))
    except Stop as e:
        notes.append(f"Régime de marché non mesuré : {e}")
    longs = sum(1 for d in included if d["_side"] > 0)
    biases.append(f"Répartition des sens : {longs} achats, {len(included) - longs} ventes.")

    # ---- 8. sorties
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "detections.csv", dets, args)
    report = build_report(args, checks, pmeta, records, fill, mapping, dets, included, missing_pairs, first, last,
                          period_days, price_source, api_check, dup_info, results, biases, notes, excl_top, regime,
                          len(det_times), inc_times)
    (args.out_dir / "rapport.md").write_text(redact(report), encoding="utf-8")
    summary = {f"{h}h_{v}": {"n": r["n"], "stats": r["stats"], "cmp": r["cmp"], "sens": r["sens"]}
               for (h, v), r in results.items()}
    (args.out_dir / "resume.json").write_text(redact(json.dumps(summary, indent=1, default=str)), encoding="utf-8")
    log(f"Termine : {len(included)} detections analysees sur {len(dets)}. Sorties dans {args.out_dir}")
    return 0


def write_csv(path, dets, args):
    import csv
    cols = ["id", "paire_api", "paire_binance", "type", "sens", "heure_detection_utc", "heure_entree_utc",
            "prix_entree", "prix_sortie_4h", "prix_sortie_24h",
            "rendement_brut_4h_pct", "rendement_net_4h_pct", "rendement_brut_24h_pct", "rendement_net_24h_pct",
            "hausse_max_4h_pct", "baisse_max_4h_pct", "hausse_max_24h_pct", "baisse_max_24h_pct",
            "doublon_4h", "doublon_24h", "repetition_moins_4h", "repetition_moins_24h",
            "bougies_manquantes_4h", "bougies_manquantes_24h",
            "hasard_moyenne_net_4h_pct", "hasard_mediane_net_4h_pct", "hasard_moyenne_net_24h_pct",
            "hasard_mediane_net_24h_pct", "statut"]

    def p(x):
        return "" if x is None else f"{x * 100:.4f}"

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for d in sorted(dets, key=lambda d: (d["_det_ms"] or 0, d["_key"])):
            inc = d["statut"] == "inclus"
            base = d.get("_base")
            row = {
                "id": d["id"], "paire_api": d["paire_api"], "paire_binance": d["paire_binance"], "type": d["type"],
                "sens": d["sens"], "heure_detection_utc": d["heure_detection_utc"],
                "heure_entree_utc": d.get("heure_entree_utc", ""), "prix_entree": d.get("prix_entree", ""),
                "statut": d["statut"],
            }
            for h in HORIZONS:
                row[f"prix_sortie_{h}h"] = d.get(f"_exit_{h}", "")
                row[f"rendement_brut_{h}h_pct"] = p(d.get(f"_gross_{h}")) if inc else ""
                row[f"rendement_net_{h}h_pct"] = p(d.get(f"_net_{h}")) if inc else ""
                row[f"hausse_max_{h}h_pct"] = p(d.get(f"_up_{h}")) if inc else ""
                row[f"baisse_max_{h}h_pct"] = p(d.get(f"_down_{h}")) if inc else ""
                row[f"doublon_{h}h"] = int(d[f"_dup_{h}"]) if inc else ""
                row[f"repetition_moins_{h}h"] = int(d[f"_rep_{h}"]) if inc else ""
                row[f"bougies_manquantes_{h}h"] = d.get(f"bougies_manquantes_{h}h", "")
                row[f"hasard_moyenne_net_{h}h_pct"] = p(float(base[h].mean())) if base is not None else ""
                row[f"hasard_mediane_net_{h}h_pct"] = p(float(np.median(base[h]))) if base is not None else ""
            w.writerow([redact(row[c]) if isinstance(row[c], str) else row[c] for c in cols])


def build_report(args, checks, pmeta, records, fill, mapping, dets, included, missing_pairs, first, last, period_days,
                 price_source, api_check, dup_info, results, biases, notes, excl_top, regime, n_timed, inc_times):
    L = []
    host = urlparse(args.api_url or "").netloc
    L.append("# Rentabilité des détections CoinBeacon à 4 h et 24 h\n")
    L.append(f"Généré le {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC par `coinbeacon/analyse_setups.py`. "
             f"Coût aller-retour {args.cost * 100:.2f} %, graine {args.seed}, {args.bootstrap} rééchantillonnages, "
             f"{args.n_random} entrées au hasard par détection dans ±{args.window_days:g} jours.\n")
    L.append("## 1. Données\n")
    L.append("Contrôles préalables :\n")
    L.extend(f"- {c}" for c in checks)
    L.append("")
    L.append((f"- Source : {pmeta['methode']}, heure de détection = {args.heure_detection}, "
              f"setups vus plus de {args.bars_max} bougie(s) après déclenchement écartés" if args.observations else
              f"- Source : `{host}`, {pmeta['pages']} pages, pagination : {pmeta['methode']}")
             + (f", total annoncé par l'API : {pmeta['total_annonce']}" if pmeta["total_annonce"] is not None else "") + ".")
    L.append(f"- Période couverte : **{iso(first)} → {iso(last)} UTC**, soit {period_days:.1f} jours.")
    L.append(f"- Détections récupérées : **{len(records)}** ; analysées : **{len(included)}**.")
    L.append("- Correspondance des champs : " + ", ".join(f"{k} = `{v}`" for k, v in mapping.items()) + ".")
    L.append(f"- Prix de sortie : {price_source}. Entrée : ouverture de la première bougie 1 min qui commence après la détection.")
    if api_check:
        L.append(f"- Vérification des prix de l'API sur {api_check['n']} sorties : écart médian "
                 f"{api_check['mediane'] * 100:.3f} %, maximal {api_check['max'] * 100:.3f} %.")
    L.append("\nChamps fournis par l'API, avec leur taux de remplissage :\n")
    L.append(", ".join(f"`{f}` {v * 100:.0f} %" for f, v in fill.items()))
    L.append("\nEntonnoir :\n")
    L.append("| Statut | Détections |\n|---|---:|")
    for st, n in Counter(d["statut"] for d in dets).most_common():
        L.append(f"| {st} | {n} |")
    if missing_pairs:
        L.append("\nPaires introuvables sur Binance spot : "
                 + ", ".join(f"`{p}` ({n})" for p, n in missing_pairs.most_common()) + ".")
    L.append("")

    for k, h in enumerate(HORIZONS, 2):
        L.append(f"## {k}. Résultats à {h} h, nets de frais\n")
        for version in ("avec", "sans"):
            r = results[(h, version)]
            L.append(f"**{version.capitalize()} doublons** ({r['n']} détections) :\n")
            L.append(stats_table(r["stats"]))
            L.append("")
        L.append("La hausse et la baisse maximales sont exprimées dans le sens de la position : pour un vendeur, "
                 "la hausse maximale est la plus forte baisse du prix. « par jour » : intervalle obtenu en "
                 "rééchantillonnant des journées entières, plus honnête quand des détections d'un même jour "
                 "dépendent du même mouvement de marché.\n")

    L.append("## 4. Comparaison avec des entrées au hasard\n")
    if args.no_random:
        L.append("Sautée (--no-random).\n")
    else:
        L.append("Pour chaque détection, 20 entrées tirées au hasard sur la même paire dans ±7 jours, même sens, "
                 "mêmes horizons, mêmes frais. Écart apparié = rendement du setup − moyenne de ses propres tirages.\n")
        L.append("| Horizon | Doublons | Groupe | n | Moy. setups | Moy. hasard | Gagnants setups / hasard | "
                 "Quantiles 10/25/50/75/90 setups | idem hasard | Écart apparié [IC 95 %] | Part > médiane hasard | "
                 "p KS | p Wilcoxon | Significatif |")
        L.append("|---|---|---|---:|---:|---:|---|---|---|---|---:|---:|---:|---|")
        for h in HORIZONS:
            for version in ("avec", "sans"):
                for name, c in results[(h, version)]["cmp"].items():
                    if not c:
                        continue
                    q1 = " / ".join(f"{x * 100:+.1f}" for x in c["q_setups"])
                    q2 = " / ".join(f"{x * 100:+.1f}" for x in c["q_hasard"])
                    L.append(f"| {h} h | {version} | {name} | {c['n']} | {pct(c['moy_setups'])} | {pct(c['moy_hasard'])} | "
                             f"{c['gagnants_setups'] * 100:.0f} % / {c['gagnants_hasard'] * 100:.0f} % | {q1} | {q2} | "
                             f"{pct(c['ecart_moyen'])} [{pct(c['ic_ecart'][0])} ; {pct(c['ic_ecart'][1])}] | "
                             f"{c['part_bat_hasard'] * 100:.0f} % | {pval(c['ks_p'])} | {pval(c['wilcoxon_p'])} | "
                             f"{'oui' if c['significatif'] else 'non'} |")
        L.append("\nLes tirages au hasard d'une même détection se chevauchent : les p-valeurs KS et Mann-Whitney, qui "
                 "les supposent indépendants, sont trop optimistes. Le critère retenu est l'écart apparié : intervalle "
                 "de confiance excluant zéro et test de Wilcoxon sous 0,05.\n")

    L.append("## 5. Sensibilité aux frais\n")
    L.append("Coût aller-retour au-delà duquel la moyenne, puis la médiane, deviennent négatives (les frais sont "
             "retranchés du rendement brut, donc le seuil est le rendement brut lui-même) :\n")
    L.append("| Horizon | Doublons | Groupe | Seuil moyenne | Seuil médiane |\n|---|---|---|---:|---:|")
    for h in HORIZONS:
        for version in ("avec", "sans"):
            for name, (m, med) in results[(h, version)]["sens"].items():
                fm = "négative sans frais" if m <= 0 else f"{m * 100:.2f} %"
                fmed = "négative sans frais" if med <= 0 else f"{med * 100:.2f} %"
                L.append(f"| {h} h | {version} | {name} | {fm} | {fmed} |")
    L.append("")

    L.append("## 6. Doublons\n")
    for h in HORIZONS:
        dup, rep = dup_info[h]
        L.append(f"- {h} h : {rep} détections suivent une autre détection de la même paire à moins de {h} h ; "
                 f"{dup} sont écartées dans la version sans doublons (position précédente encore ouverte).")
    L.append("")

    L.append("## 7. Biais et limites\n")
    L.extend(f"- {b}" for b in biases)
    for h in HORIZONS:
        n, m = excl_top[h]
        if n == 0:
            continue
        L.append(f"- Sans les 3 paires les plus fréquentes, moyenne nette à {h} h : {pct(m)} sur {n} détections.")
    L.append("- **Positions courtes** : les vendeurs sont traités comme des ventes à découvert. C'est impossible au "
             "comptant sur Binance ; sur un contrat perpétuel il faudrait ajouter le financement, payé ou reçu toutes "
             "les 8 h, et l'écart de prix entre perpétuel et comptant. Les résultats vendeurs sont donc optimistes "
             "ou pessimistes d'un montant inconnu et ne sont pas directement réalisables.")
    L.append("- Frais fixes de 0,30 % aller-retour : le glissement réel dépend de la liquidité de chaque paire et "
             "peut être bien supérieur sur les petites capitalisations.")
    L.append("- Paires absentes du comptant Binance exclues : si ce sont des paires radiées, l'échantillon est biaisé "
             "en faveur des survivantes.")
    L.extend(f"- {n}" for n in notes)
    L.append("")

    L.append("## 8. Conclusion\n")
    for h in HORIZONS:
        r = results[(h, "sans")]
        for s in r["stats"][1:3]:
            if s["n"] == 0:
                continue
            c = r["cmp"].get(s["groupe"]) if r["cmp"] else None
            crit = {
                f"au moins {MIN_N} détections": s["n"] >= MIN_N,
                "borne basse de l'IC de la moyenne nette > 0": s["ic"][0] > 0,
                "borne basse de l'IC par jour > 0": s.get("ic_jours", (float("nan"),))[0] > 0,
                "médiane nette > 0": s["mediane"] > 0,
                "moyenne sans les 3 meilleurs > 0": s["moyenne_sans_top3"] > 0,
                "meilleur que le hasard (écart apparié significatif et positif)":
                    bool(c and c["significatif"] and c["ecart_moyen"] > 0),
            }
            ok = all(crit.values())
            verdict = ("**avantage plausible**, à confirmer sur des détections futures" if ok else
                       "**pas d'avantage démontré**")
            failed = [k for k, v in crit.items() if not v]
            L.append(f"- {h} h, {s['groupe'].lower()}, sans doublons : {verdict}. Moyenne nette {pct(s['moyenne'])}, "
                     f"médiane {pct(s['mediane'])}."
                     + (f" Critères non remplis : {'; '.join(failed)}." if failed else ""))
    L.append("\nUn avantage n'est retenu que si tous les critères sont réunis : une moyenne positive tirée par "
             "quelques gros gains, ou qui ne bat pas des entrées au hasard sur les mêmes paires et la même période, "
             "traduit la tendance du marché et non la qualité des détections.\n")
    L.append("Ce qui reste incertain :\n")
    L.append(f"- Une seule période de {period_days:.0f} jours ; rien ne garantit que le résultat tienne dans un autre "
             "régime de marché.")
    L.append("- La complétude de l'historique fourni par l'API : seule une comparaison entre plusieurs exécutions "
             "du script peut révéler des setups retirés.")
    L.append("- La latence réelle entre la détection et la réception de l'alerte : une entrée une minute après la "
             "détection est un cas favorable.")
    L.append("- Les tests par type de setup sont nombreux : un type qui ressort significatif parmi beaucoup peut "
             "l'être par hasard. Le traiter comme une hypothèse à vérifier sur les détections suivantes.")
    L.append("- Le coût réel des positions courtes, non modélisé.")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Stop as e:
        log(f"ARRET : {e}")
        sys.exit(e.code)
