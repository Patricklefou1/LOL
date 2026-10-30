import { ClickHouseClient } from "@clickhouse/client";
import { evenementsSql, SOURCES } from "./listings";
import { releverTokenomics } from "./coingecko";

// Suivi des tokens lancés : prix, financement, intérêt ouvert et volume relevés
// chaque heure pendant 35 jours, pour mesurer ce que deviennent les lancements
// à J+1, J+7 et J+30.
//
// Une requête groupée par bourse et par marché renvoie les tickers de tous les
// contrats d'un coup : le coût ne dépend pas du nombre de tokens suivis.

const DUREE_JOURS = 35;
const HORIZONS = [1, 3, 7, 30];
// Référence de marché : les rendements sont aussi donnés nets de la variation de BTC
const MARCHE = "BTC";
// Seules les paires en dollars donnent un prix comparable entre bourses
const QUOTES_DOLLAR = ["USDT", "USDC", "USD", "FDUSD"];

interface Ticker {
  symbole: string;
  prix: number;
  financement?: number | null;
  oi_usd?: number | null;
  volume_usd?: number | null;
}

interface SourceTickers {
  bourse: string;
  marche: "spot" | "perp";
  lire: () => Promise<Ticker[]>;
}

async function getJson(url: string, init?: RequestInit): Promise<any> {
  const reponse = await fetch(url, {
    ...init,
    headers: { "user-agent": "pumpfun-capture/listings", accept: "application/json", ...(init?.headers ?? {}) },
    signal: AbortSignal.timeout(30_000),
  });
  if (!reponse.ok) throw new Error(`HTTP ${reponse.status} sur ${url.split("?")[0]}`);
  return reponse.json();
}

const n = (v: unknown): number | null => {
  const x = Number(v);
  return Number.isFinite(x) ? x : null;
};

export const TICKERS: SourceTickers[] = [
  {
    bourse: "binance",
    marche: "spot",
    lire: async () =>
      ((await getJson("https://api.binance.com/api/v3/ticker/24hr")) as any[]).map((t) => ({
        symbole: t.symbol,
        prix: Number(t.lastPrice),
        volume_usd: n(t.quoteVolume),
      })),
  },
  {
    bourse: "binance",
    marche: "perp",
    lire: async () => {
      const [prem, vol] = await Promise.all([
        getJson("https://fapi.binance.com/fapi/v1/premiumIndex"),
        getJson("https://fapi.binance.com/fapi/v1/ticker/24hr"),
      ]);
      const volumes = new Map<string, number | null>((vol as any[]).map((t) => [t.symbol, n(t.quoteVolume)]));
      return (prem as any[]).map((t) => ({
        symbole: t.symbol,
        prix: Number(t.markPrice),
        financement: n(t.lastFundingRate),
        volume_usd: volumes.get(t.symbol) ?? null,
      }));
    },
  },
  {
    bourse: "okx",
    marche: "spot",
    lire: async () =>
      ((await getJson("https://www.okx.com/api/v5/market/tickers?instType=SPOT")).data as any[]).map((t) => ({
        symbole: t.instId,
        prix: Number(t.last),
        // en spot, volCcy24h est en devise de cotation
        volume_usd: n(t.volCcy24h),
      })),
  },
  {
    bourse: "okx",
    marche: "perp",
    lire: async () => {
      const [tick, oi] = await Promise.all([
        getJson("https://www.okx.com/api/v5/market/tickers?instType=SWAP"),
        getJson("https://www.okx.com/api/v5/public/open-interest?instType=SWAP"),
      ]);
      const ois = new Map<string, number | null>((oi.data as any[]).map((o) => [o.instId, n(o.oiUsd)]));
      // OKX ne publie le financement qu'instrument par instrument : absent ici
      return (tick.data as any[]).map((t) => ({
        symbole: t.instId,
        prix: Number(t.last),
        oi_usd: ois.get(t.instId) ?? null,
        // en perp, volCcy24h est en devise de base
        volume_usd: (n(t.volCcy24h) ?? 0) * Number(t.last) || null,
      }));
    },
  },
  {
    bourse: "bybit",
    marche: "spot",
    lire: async () =>
      ((await getJson("https://api.bybit.com/v5/market/tickers?category=spot")).result.list as any[]).map((t) => ({
        symbole: t.symbol,
        prix: Number(t.lastPrice),
        volume_usd: n(t.turnover24h),
      })),
  },
  {
    bourse: "bybit",
    marche: "perp",
    lire: async () =>
      ((await getJson("https://api.bybit.com/v5/market/tickers?category=linear")).result.list as any[]).map((t) => ({
        symbole: t.symbol,
        prix: Number(t.lastPrice),
        financement: n(t.fundingRate),
        oi_usd: n(t.openInterestValue),
        volume_usd: n(t.turnover24h),
      })),
  },
  {
    bourse: "gate",
    marche: "spot",
    lire: async () =>
      ((await getJson("https://api.gateio.ws/api/v4/spot/tickers")) as any[]).map((t) => ({
        symbole: t.currency_pair,
        prix: Number(t.last),
        volume_usd: n(t.quote_volume),
      })),
  },
  {
    bourse: "gate",
    marche: "perp",
    lire: async () =>
      ((await getJson("https://api.gateio.ws/api/v4/futures/usdt/tickers")) as any[]).map((t) => ({
        symbole: t.contract,
        prix: Number(t.last),
        financement: n(t.funding_rate),
        volume_usd: n(t.volume_24h_quote),
      })),
  },
  {
    bourse: "mexc",
    marche: "spot",
    lire: async () =>
      ((await getJson("https://api.mexc.com/api/v3/ticker/24hr")) as any[]).map((t) => ({
        symbole: t.symbol,
        prix: Number(t.lastPrice),
        volume_usd: n(t.quoteVolume),
      })),
  },
  {
    bourse: "mexc",
    marche: "perp",
    lire: async () =>
      ((await getJson("https://contract.mexc.com/api/v1/contract/ticker")).data as any[]).map((t) => ({
        symbole: t.symbol,
        prix: Number(t.lastPrice),
        financement: n(t.fundingRate),
        volume_usd: n(t.amount24),
      })),
  },
  {
    bourse: "kucoin",
    marche: "spot",
    lire: async () =>
      ((await getJson("https://api.kucoin.com/api/v1/market/allTickers")).data.ticker as any[]).map((t) => ({
        symbole: t.symbol,
        prix: Number(t.last),
        volume_usd: n(t.volValue),
      })),
  },
  {
    bourse: "kucoin",
    marche: "perp",
    lire: async () =>
      ((await getJson("https://api-futures.kucoin.com/api/v1/contracts/active")).data as any[]).map((c) => ({
        symbole: c.symbol,
        prix: Number(c.lastTradePrice),
        financement: n(c.fundingFeeRate),
        // openInterest est en lots : lots × multiplicateur × prix
        oi_usd: (n(c.openInterest) ?? 0) * (n(c.multiplier) ?? 0) * Number(c.lastTradePrice) || null,
        volume_usd: n(c.turnoverOf24h),
      })),
  },
  {
    bourse: "hyperliquid",
    marche: "perp",
    lire: async () => {
      const [meta, ctxs] = await getJson("https://api.hyperliquid.xyz/info", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ type: "metaAndAssetCtxs" }),
      });
      return (meta.universe as any[]).map((u, i) => {
        const c = ctxs[i] ?? {};
        const prix = Number(c.markPx);
        return {
          symbole: u.name,
          prix,
          // Hyperliquid facture le financement toutes les heures
          financement: n(c.funding),
          oi_usd: (n(c.openInterest) ?? 0) * prix || null,
          volume_usd: n(c.dayNtlVlm),
        };
      });
    },
  },
];

function chDate(msEpoch: number): string {
  return new Date(msEpoch).toISOString().slice(0, 19).replace("T", " ");
}

// Tickers des tokens lancés ou passés en perp depuis moins de 35 jours, selon le
// même calcul d'événements que le rapport. Le premier perp compte : DNA, coté en
// spot sur Gate quelques heures avant ses perps, n'aurait sinon jamais été suivi.
async function tokensSuivis(ch: ClickHouseClient): Promise<{ base: string; le: string }[]> {
  return (
    await ch.query({
      query: `SELECT base, toString(min(le)) AS le FROM (${evenementsSql("now() + INTERVAL 1 DAY")})
              GROUP BY base`,
      query_params: { jours: DUREE_JOURS },
      format: "JSONEachRow",
    })
  ).json<{ base: string; le: string }>();
}

export async function releverSuivi(ch: ClickHouseClient, maintenant: number): Promise<void> {
  const lances = await tokensSuivis(ch);
  if (lances.length === 0) {
    console.log("[listings] suivi : aucun lancement de moins de 35 jours");
    return;
  }
  await releverTokenomics(
    ch,
    lances.map((s) => s.base),
    maintenant,
  );
  const suivis = [...lances, { base: MARCHE, le: "" }];

  // Symbole de chaque paire en dollars des tokens suivis, par bourse et marché
  const paires = await (
    await ch.query({
      query: `SELECT bourse, marche, symbole, base FROM cex_paires FINAL
              WHERE base IN {bases:Array(String)} AND quote IN {quotes:Array(String)}`,
      query_params: { bases: suivis.map((s) => s.base), quotes: QUOTES_DOLLAR },
      format: "JSONEachRow",
    })
  ).json<{ bourse: string; marche: string; symbole: string; base: string }>();
  const baseDe = new Map(paires.map((p) => [`${p.bourse}|${p.marche}|${p.symbole}`, p.base]));

  const lignes: Record<string, unknown>[] = [];
  let echecs = 0;
  for (const source of TICKERS) {
    if (!paires.some((p) => p.bourse === source.bourse && p.marche === source.marche)) continue;
    try {
      for (const t of await source.lire()) {
        const base = baseDe.get(`${source.bourse}|${source.marche}|${t.symbole}`);
        if (!base || !(t.prix > 0)) continue;
        lignes.push({
          base,
          releve_le: chDate(maintenant),
          bourse: source.bourse,
          marche: source.marche,
          prix: t.prix,
          financement: t.financement ?? null,
          oi_usd: t.oi_usd ?? null,
          volume_usd: t.volume_usd ?? null,
        });
      }
    } catch (err) {
      // Une bourse muette ce relevé-ci : les autres suffisent à donner le prix
      echecs++;
      console.error(`[listings] suivi ${source.bourse} ${source.marche} : ${err}`);
    }
  }

  if (lignes.length > 0) {
    await ch.insert({ table: "suivi_lancements", values: lignes, format: "JSONEachRow" });
  }
  console.log(
    `[listings] suivi : ${lances.length} tokens, ${lignes.length} cotations relevées` +
      (echecs ? `, ${echecs} sources en échec` : ""),
  );
}

const pct = (x: number | null) => (x === null ? "—" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(0)} %`);
const mediane = (xs: number[]) => {
  if (xs.length === 0) return null;
  const t = [...xs].sort((a, b) => a - b);
  const m = Math.floor(t.length / 2);
  return t.length % 2 ? t[m] : (t[m - 1] + t[m]) / 2;
};

// Rendement de chaque lancement à J+1, J+3, J+7, J+30 et maintenant, brut et net
// de BTC, à partir du prix médian toutes bourses confondues de chaque relevé
// horaire ; plus haut et plus bas atteints ; flottant et FDV / capitalisation
// au premier relevé de tokenomics.
export async function rapportSuivi(ch: ClickHouseClient): Promise<void> {
  const rang1 = (marche: string) =>
    SOURCES.filter((s) => s.rang === 1 && s.marche === marche)
      .map((s) => `'${s.bourse}'`)
      .join(",");

  const evenements = await (
    await ch.query({
      // Un ticker, un départ : le plus ancien de ses événements
      query: `SELECT base, toString(min(le)) AS depart, argMin(evenement, le) AS premier,
                     max(hasAny(bourses_spot, [${rang1("spot")}]) OR hasAny(bourses_perp, [${rang1("perp")}])) AS rang1
              FROM (${evenementsSql("now() + INTERVAL 1 DAY")})
              GROUP BY base
              ORDER BY depart DESC`,
      query_params: { jours: DUREE_JOURS },
      format: "JSONEachRow",
    })
  ).json<{ base: string; depart: string; premier: string; rang1: number }>();
  if (evenements.length === 0) return;
  const bases = evenements.map((e) => e.base);

  const releves = await (
    await ch.query({
      query: `SELECT base, toUnixTimestamp(releve_le) AS t, median(prix) AS prix,
                     avgIf(financement, financement IS NOT NULL) AS financement,
                     sumIf(oi_usd, oi_usd IS NOT NULL) AS oi
              FROM suivi_lancements
              WHERE base IN {bases:Array(String)}
              GROUP BY base, releve_le ORDER BY base, releve_le`,
      query_params: { bases: [...bases, MARCHE] },
      format: "JSONEachRow",
    })
  ).json<{ base: string; t: number | string; prix: number; financement: number | null; oi: number }>();

  const tokenomics = await (
    await ch.query({
      // Premier relevé à capitalisation connue : la tokenomics au lancement
      query: `SELECT base, argMin(t.mcap, t.releve_le) AS mcap0, argMin(t.fdv, t.releve_le) AS fdv0,
                     argMin(t.circulant, t.releve_le) AS circulant0, argMin(t.total, t.releve_le) AS total0
              FROM suivi_tokenomics AS t WHERE t.base IN {bases:Array(String)} AND t.mcap > 0
              GROUP BY base`,
      query_params: { bases },
      format: "JSONEachRow",
    })
  ).json<{ base: string; mcap0: number; fdv0: number; circulant0: number; total0: number }>();
  const tokDe = new Map(
    tokenomics.map((t) => [t.base, { mcap: t.mcap0, fdv: t.fdv0, circulant: t.circulant0, total: t.total0 }]),
  );
  const flottantDe = (base: string): number | null => {
    const t = tokDe.get(base);
    return t && Number(t.total) > 0 ? Number(t.circulant) / Number(t.total) : null;
  };

  const parBase = new Map<string, { t: number; prix: number; financement: number | null; oi: number }[]>();
  for (const r of releves) {
    const liste = parBase.get(r.base) ?? [];
    liste.push({ t: Number(r.t) * 1000, prix: Number(r.prix), financement: r.financement, oi: Number(r.oi) });
    parBase.set(r.base, liste);
  }
  const btc = new Map((parBase.get(MARCHE) ?? []).map((s) => [s.t, s.prix]));

  // Médianes par horizon : toutes, puis séparées par flottant (< 20 % ou non)
  type Stat = { brut: number[]; net: number[] };
  const nouvelle = (): Record<number, Stat> =>
    Object.fromEntries(HORIZONS.map((j) => [j, { brut: [], net: [] }])) as Record<number, Stat>;
  const stats = { tous: nouvelle(), faible: nouvelle(), large: nouvelle() };
  const lignes: string[] = [];

  for (const e of evenements) {
    const serie = parBase.get(e.base);
    if (!serie?.length) continue;
    const t0 = Date.parse(e.depart.replace(" ", "T") + "Z");
    const p0 = serie[0];
    // Un premier relevé plus de 6 h après le lancement manque le départ :
    // le rendement part du premier prix connu, pas du prix de lancement
    const partiel = p0.t - t0 > 6 * 3600e3;
    const btc0 = btc.get(p0.t);
    const mesure = (s: { t: number; prix: number }) => {
      const brut = s.prix / p0.prix - 1;
      const b = btc.get(s.t);
      return { brut, net: btc0 && b ? (1 + brut) / (b / btc0) - 1 : null };
    };
    const r = HORIZONS.map((j) => {
      const s = serie.find((x) => x.t >= t0 + j * 86400e3);
      return s ? mesure(s) : null;
    });
    const dernier = serie[serie.length - 1];
    const depuis = mesure(dernier);
    const haut = Math.max(...serie.map((s) => s.prix)) / p0.prix - 1;
    const bas = Math.min(...serie.map((s) => s.prix)) / p0.prix - 1;
    const flottant = flottantDe(e.base);
    const tok = tokDe.get(e.base);

    if (Number(e.rang1) !== 1) continue;
    if (!partiel) {
      const cohortes = [stats.tous, ...(flottant === null ? [] : [flottant < 0.2 ? stats.faible : stats.large])];
      HORIZONS.forEach((j, i) => {
        const x = r[i];
        if (!x) return;
        for (const c of cohortes) {
          c[j].brut.push(x.brut);
          if (x.net !== null) c[j].net.push(x.net);
        }
      });
    }
    const fmt = (x: { brut: number; net: number | null } | null) =>
      x ? `${pct(x.brut)}${x.net === null ? "" : ` (${pct(x.net)})`}` : "—";
    lignes.push(
      `  ${e.base.padEnd(10)} ${e.premier === "lancement" ? "lancé" : e.premier} ${e.depart.slice(0, 10)}` +
        (flottant === null ? "" : `  flottant ${Math.round(flottant * 100)} %`) +
        (tok && Number(tok.mcap) > 0 && Number(tok.fdv) > 0
          ? `  FDV/mcap ${(Number(tok.fdv) / Number(tok.mcap)).toFixed(1)}`
          : "") +
        (partiel ? "  (départ manqué)" : "") +
        `\n      ${HORIZONS.map((j, i) => `J+${j} ${fmt(r[i])}`).join("  ")}  depuis ${fmt(depuis)}` +
        `\n      haut ${pct(haut)}  bas ${pct(bas)}` +
        `  fin. ${dernier.financement === null ? "—" : `${(dernier.financement * 100).toFixed(3)} %`}` +
        (dernier.oi > 0 ? `  OI ${(dernier.oi / 1e6).toFixed(1)} M$` : ""),
    );
  }

  const resume = (titre: string, c: Record<number, Stat>) => {
    const parties = HORIZONS.filter((j) => c[j].brut.length > 0).map((j) => {
      const xs = c[j].brut;
      const baisses = xs.filter((x) => x < 0).length;
      const net = mediane(c[j].net);
      return (
        `J+${j} ${pct(mediane(xs))}${net === null ? "" : ` (${pct(net)})`} ` +
        `n=${xs.length} ${Math.round((baisses / xs.length) * 100)} % en baisse`
      );
    });
    if (parties.length) console.log(`  ${titre.padEnd(16)} ${parties.join(" | ")}`);
  };
  console.log(`\nSuivi des lancements de rang 1 (35 derniers jours) — médianes, entre parenthèses nettes de BTC :`);
  resume("tous", stats.tous);
  resume("flottant < 20 %", stats.faible);
  resume("flottant ≥ 20 %", stats.large);
  for (const l of lignes) console.log(l);
}
