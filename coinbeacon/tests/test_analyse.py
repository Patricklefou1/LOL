"""Tests du script sur des donnees artificielles servies localement.

Rien ici n'est un resultat : ces donnees ne servent qu'a verifier les calculs,
la pagination et l'absence du jeton dans les sorties.
"""
import csv
import gzip
import json
import math
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analyse_setups as A  # noqa: E402

TOKEN = "tok-TEST-ne-doit-jamais-sortir-123"
T0 = 1_767_225_600_000  # 2026-01-01 00:00 UTC
NOW = T0 + 40 * A.DAY_MS
SPOT = {"BTCUSDT": "TRADING", "ETHUSDT": "TRADING", "SOLUSDT": "TRADING"}


def price(sym, t):
    k = {"BTCUSDT": 1.0, "ETHUSDT": 2.0, "SOLUSDT": 3.0}[sym]
    return 100 * k * (1 + 0.05 * math.sin(t / (6 * A.HOUR_MS)) + 0.0001 * ((t // A.MIN_MS) % 7))


def make_setups():
    out = []
    for k in range(60):
        sym = ["BTC/USDT", "ETH-USDT", "SOL"][k % 3]
        det = T0 + 8 * A.DAY_MS + k * 5 * A.HOUR_MS + 17_000  # 17 s apres la minute
        out.append({"id": k + 1, "market": {"symbol": sym}, "setup_type": ["breakout", "rebond"][k % 2],
                    "direction": "bullish" if k % 4 else "bearish",
                    "detected_at": A.iso(det).replace(" ", "T") + "Z"})
    out.append({"id": 61, "market": {"symbol": "FOOUSDT"}, "setup_type": "breakout", "direction": "long",
                "detected_at": A.iso(T0 + 9 * A.DAY_MS).replace(" ", "T") + "Z"})
    out.append({"id": 62, "market": {"symbol": "BTCUSDT"}, "setup_type": "breakout", "direction": "long",
                "detected_at": A.iso(NOW - 3 * A.HOUR_MS).replace(" ", "T") + "Z"})
    # doublon : meme paire, 1 h apres la detection 1 (BTC)
    out.append({"id": 63, "market": {"symbol": "BTCUSDT"}, "setup_type": "breakout", "direction": "long",
                "detected_at": A.iso(T0 + 8 * A.DAY_MS + A.HOUR_MS).replace(" ", "T") + "Z"})
    return out


SETUPS = make_setups()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/setups":
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                return self._json({"error": "unauthorized"}, 401)
            page, size = int(q.get("page", 1)), 25
            chunk = SETUPS[(page - 1) * size: page * size]
            pages = math.ceil(len(SETUPS) / size)
            return self._json({"data": chunk, "meta": {"page": page, "total_pages": pages, "total": len(SETUPS)}})
        if u.path == "/api/v3/ping":
            return self._json({})
        if u.path == "/api/v3/time":
            return self._json({"serverTime": NOW})
        if u.path == "/api/v3/exchangeInfo":
            return self._json({"symbols": [{"symbol": s, "status": st} for s, st in SPOT.items()]})
        if u.path == "/api/v3/klines":
            sym = q["symbol"]
            if sym not in SPOT:
                return self._json({"code": -1121, "msg": "Invalid symbol."}, 400)
            step = A.DAY_MS if q["interval"] == "1d" else A.MIN_MS
            start, end = int(q["startTime"]), min(int(q["endTime"]), NOW)
            t = (start + step - 1) // step * step
            rows = []
            while t <= end and len(rows) < int(q.get("limit", 500)):
                if not (sym == "ETHUSDT" and T0 + 20 * A.DAY_MS <= t < T0 + 20 * A.DAY_MS + 30 * A.MIN_MS):
                    o, c = price(sym, t), price(sym, t + step)
                    rows.append([t, str(o), str(max(o, c) * 1.001), str(min(o, c) * 0.999), str(c)])
                t += step
            return self._json(rows)
        return self._json({"error": "not found"}, 404)


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def run(server, tmp_path, monkeypatch, *extra):
    monkeypatch.setenv("COINBEACON_TOKEN", TOKEN)
    return A.main(["--api-url", f"{server}/setups", "--binance-base", server, "--cache-dir", str(tmp_path / "cache"),
                   "--out-dir", str(tmp_path / "out"), "--bootstrap", "500", *extra])


def test_bout_en_bout(server, tmp_path, monkeypatch):
    assert run(server, tmp_path, monkeypatch) == 0
    out = tmp_path / "out"
    rows = list(csv.DictReader(open(out / "detections.csv", encoding="utf-8")))
    assert len(rows) == len(SETUPS)
    st = {r["id"]: r["statut"] for r in rows}
    assert st["61"] == "exclu : paire introuvable sur Binance spot"
    assert st["62"] == "exclu : horizon 24 h non écoulé"
    assert sum(s == "inclus" for s in st.values()) >= 55
    # id 2 : ETH, acheteur, detectee 17 s apres la minute
    r2 = next(r for r in rows if r["id"] == "2")
    det = T0 + 8 * A.DAY_MS + 5 * A.HOUR_MS + 17_000
    entry_t = (det // A.MIN_MS + 1) * A.MIN_MS
    assert r2["sens"] == "achat" and r2["heure_entree_utc"] == A.iso(entry_t)
    assert float(r2["prix_entree"]) == pytest.approx(price("ETHUSDT", entry_t))
    exit4 = price("ETHUSDT", entry_t + 4 * A.HOUR_MS)  # cloture de la bougie entree + 4 h - 1 min
    assert float(r2["prix_sortie_4h"]) == pytest.approx(exit4)
    gross = exit4 / price("ETHUSDT", entry_t) - 1
    assert float(r2["rendement_brut_4h_pct"]) == pytest.approx(gross * 100, abs=1e-3)
    assert float(r2["rendement_net_4h_pct"]) == pytest.approx((gross - 0.003) * 100, abs=1e-3)
    # id 1 : BTC, vendeur, rendement inverse
    r1 = next(r for r in rows if r["id"] == "1")
    assert r1["sens"] == "vente"
    e1 = float(r1["prix_entree"])
    assert float(r1["rendement_brut_24h_pct"]) == pytest.approx(-(float(r1["prix_sortie_24h"]) / e1 - 1) * 100, abs=1e-3)
    # id 63 : BTC une heure apres l'id 1, position encore ouverte
    assert next(r for r in rows if r["id"] == "63")["doublon_4h"] == "1"
    assert r1["doublon_4h"] == "0"
    rapport = (out / "rapport.md").read_text(encoding="utf-8")
    assert "Résultats à 4 h" in rapport and "Résultats à 24 h" in rapport and "non concluant" in rapport
    # le jeton n'apparait nulle part
    for p in list(out.rglob("*")) + list((tmp_path / "cache").rglob("*")):
        if p.is_file():
            data = p.read_bytes()
            if p.suffix == ".gz":
                data = gzip.decompress(data)
            assert TOKEN.encode() not in data, p


def test_hors_ligne_rejoue_depuis_le_cache(server, tmp_path, monkeypatch):
    assert run(server, tmp_path, monkeypatch) == 0
    first = (tmp_path / "out" / "detections.csv").read_text()
    monkeypatch.delenv("COINBEACON_TOKEN")
    assert A.main(["--api-url", f"{server}/setups", "--binance-base", "http://0.0.0.0:1", "--offline",
                   "--cache-dir", str(tmp_path / "cache"), "--out-dir", str(tmp_path / "out"),
                   "--bootstrap", "500"]) == 0
    assert (tmp_path / "out" / "detections.csv").read_text() == first


def test_controles_prealables(server, tmp_path, monkeypatch):
    monkeypatch.delenv("COINBEACON_TOKEN", raising=False)
    with pytest.raises(A.Stop) as e:
        A.main(["--api-url", f"{server}/setups", "--binance-base", server, "--cache-dir", str(tmp_path)])
    assert e.value.code == 2
    monkeypatch.setenv("COINBEACON_TOKEN", "mauvais")
    with pytest.raises(A.Stop) as e:
        A.main(["--api-url", f"{server}/setups", "--binance-base", server, "--cache-dir", str(tmp_path)])
    assert e.value.code == 3 and "HTTP 401" in str(e.value)
    monkeypatch.setenv("COINBEACON_TOKEN", TOKEN)
    with pytest.raises(A.Stop) as e:
        A.main(["--api-url", f"{server}/setups", "--binance-base", f"{server}/absent", "--cache-dir", str(tmp_path)])
    assert e.value.code == 4 and "HTTP 404" in str(e.value)


def test_evaluate_long_et_court():
    t = np.arange(0, 300) * A.MIN_MS
    rows = [[int(x), 100.0, 110.0 if k == 50 else 101.0, 90.0 if k == 100 else 99.0, 100.0] for k, x in enumerate(t)]
    rows[239][4] = 105.0
    c = A.Candles(rows)
    lg = A.evaluate(c, 0, 1, 4)
    assert lg["exit"] == 105.0 and lg["gross"] == pytest.approx(0.05)
    assert lg["up"] == pytest.approx(0.10) and lg["down"] == pytest.approx(-0.10)
    sh = A.evaluate(c, 0, -1, 4)
    assert sh["gross"] == pytest.approx(-0.05) and sh["up"] == pytest.approx(0.10) and sh["down"] == pytest.approx(-0.10)
    assert A.evaluate(c, 100, 1, 4) is None  # pas assez de bougies


def test_entree_strictement_apres():
    c = A.Candles([[k * A.MIN_MS, 1, 1, 1, 1] for k in range(10)])
    assert c.entry_index(3 * A.MIN_MS) == 4
    assert c.entry_index(3 * A.MIN_MS + 1) == 4


def test_doublons():
    rows = [{"_key": k, "paire_binance": "X", "_det_ms": m * A.HOUR_MS, "_entry_ms": m * A.HOUR_MS + A.MIN_MS}
            for k, m in enumerate([0, 1, 3, 4.5, 9])]
    dup, rep = A.mark_duplicates(rows, 4)
    assert [dup[k] for k in range(5)] == [False, True, True, False, False]
    assert [rep[k] for k in range(5)] == [False, True, True, True, False]


def test_normalisation_et_sens():
    spot = {"BTCUSDT", "PERPUSDT"}
    assert A.normalize_symbol("BINANCE:BTCUSDT.P", spot, "USDT") == ("BTCUSDT", False)
    assert A.normalize_symbol("btc/usdt", spot, "USDT") == ("BTCUSDT", False)
    assert A.normalize_symbol("BTC", spot, "USDT") == ("BTCUSDT", True)
    assert A.normalize_symbol("PERPUSDT", spot, "USDT") == ("PERPUSDT", False)
    assert A.side_of("Bullish") == 1 and A.side_of("SHORT") == -1 and A.side_of("neutral") == 0
    assert A.side_of("Bearish divergence") == -1 and A.side_of(-1) == -1


def test_pagination_curseur_et_next():
    class Args:
        page_param = offset_param = auth_query_param = None
        cursor_param = "cursor"
    api = A.SetupsApi.__new__(A.SetupsApi)
    api.args, api.extra = Args, {}
    assert api._next("https://x/s", {}, {"data": [1], "next_cursor": "abc"}, None, 1)[1] == {"cursor": "abc"}
    assert api._next("https://x/s", {}, {"data": [1], "next_cursor": "abc", "has_more": False}, None, 1) is None
    assert api._next("https://x/s", {}, {"data": [1], "next": "/s?page=2"}, None, 1)[0] == "https://x/s?page=2"
    assert api._next("https://x/s", {}, {"data": [1]}, '<https://x/s?p=2>; rel="next"', 1)[0] == "https://x/s?p=2"
    assert api._next("https://x/s", {"page": 3}, {"page": 3, "total_pages": 3}, None, 1) is None


def test_temps():
    assert A.parse_time_ms("2026-01-01T00:00:00Z") == (T0, False)
    assert A.parse_time_ms(T0 // 1000) == (T0, False)
    assert A.parse_time_ms(str(T0)) == (T0, False)
    assert A.parse_time_ms("2026-01-01 00:00:00") == (T0, True)
