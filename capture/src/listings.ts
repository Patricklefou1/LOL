import { createClient, ClickHouseClient } from "@clickhouse/client";
import { config } from "./config";
import { sleep } from "./util";

// Relevé des cotations spot et perps sur Binance, Coinbase, OKX, Bybit, Hyperliquid,
// KuCoin, Gate et MEXC.
//
//   npm run listings                  -- un relevé, écrit dans cex_paires
//   npm run listings -- --essai       -- lit les seize sources, n'écrit rien
//   npm run listings -- --rapport 15  -- événements par jour sur 15 jours
//   npm run listings -- --rapport 15 --sans-detail  -- le tableau seul, sans la liste
//
// Le rapport ne signale que deux événements :
//   - lancement : un ticker jamais coté nulle part, ni en spot ni en perp. S'il
//     arrive d'abord en perp, il est marqué comme tel, et pré-marché le cas échéant.
//   - premier perp : le premier contrat perpétuel d'un ticker déjà coté en spot.
// Une paire ou un perp de plus sur un ticker déjà coté n'est jamais signalé.
//
// Le premier relevé de chaque source sert de référence : ce qu'il voit sans
// date déclarée par la bourse est réputé ancien et ne compte jamais.

type Marche = "spot" | "perp";

interface Paire {
  symbole: string;
  base: string;
  quote: string;
  actif: boolean;
  // date de cotation déclarée par la bourse, en ms, quand elle en publie une
  dateBourse: number | null;
  premarche: boolean;
}

interface Source {
  bourse: string;
  marche: Marche;
  // 1 : Binance, Coinbase, OKX, Bybit, et les perps Hyperliquid. 2 : KuCoin,
  // Gate, MEXC et le spot Hyperliquid, qui cotent beaucoup plus tôt et beaucoup
  // plus de petits projets. Le rang est celui de la source, pas de la bourse.
  rang: 1 | 2;
  lire: () => Promise<Paire[]>;
}

// Actions, ETF, matières premières et devises tokenisés ou en perp : les bourses
// les cotent par dizaines chaque semaine, ce ne sont pas des projets crypto.
// Appliqué au champ de catégorie que chaque bourse publie.
const TRADFI = /stock|equity|tradfi|commod|forex|metal|index/i;
const estTradfi = (...valeurs: unknown[]) => valeurs.some((v) => typeof v === "string" && TRADFI.test(v));

// Tokens à effet de levier (BTC3L, ETH5S) : des produits de la bourse, pas des projets.
const LEVIER = /\d+[LS]$/;
// Multiplicateurs des tokens à très bas prix : 1000PEPE, 1MBABYDOGE, SHIB1000,
// et kPEPE sur Hyperliquid (k minuscule, d'où le test avant la mise en majuscules).
// Sans les retirer, le perp ne se rattache pas à son token et passe pour un lancement.
const MULTIPLICATEUR_DEVANT = /^(1000000|100000|10000|1000|1M)(?=[A-Z])/;
const MULTIPLICATEUR_K = /^k(?=[A-Z])/;
const MULTIPLICATEUR_DERRIERE = /(?<=[A-Z])(1000000|100000|10000|1000)$/;
// Tickers que certaines bourses écrivent autrement
const ALIAS: Record<string, string> = { XBT: "BTC" };

export function normaliserBase(brute: string): string {
  const base = String(brute)
    .replace(MULTIPLICATEUR_K, "")
    .toUpperCase()
    .replace(MULTIPLICATEUR_DEVANT, "")
    .replace(MULTIPLICATEUR_DERRIERE, "");
  return ALIAS[base] ?? base;
}

async function getJson(url: string): Promise<any> {
  const reponse = await fetch(url, {
    // Coinbase refuse les requêtes sans User-Agent
    headers: { "user-agent": "pumpfun-capture/listings", accept: "application/json" },
    signal: AbortSignal.timeout(30_000),
  });
  if (!reponse.ok) throw new Error(`HTTP ${reponse.status} sur ${url}`);
  return reponse.json();
}

// Hyperliquid n'a qu'un point d'entrée, en POST
async function hyperliquid(type: string): Promise<any> {
  const reponse = await fetch("https://api.hyperliquid.xyz/info", {
    method: "POST",
    headers: { "content-type": "application/json", "user-agent": "pumpfun-capture/listings" },
    body: JSON.stringify({ type }),
    signal: AbortSignal.timeout(30_000),
  });
  if (!reponse.ok) throw new Error(`HTTP ${reponse.status} sur Hyperliquid ${type}`);
  return reponse.json();
}

function ms(v: unknown): number | null {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function secondes(v: unknown): number | null {
  const n = ms(v);
  return n === null ? null : n * 1000;
}

// Bybit pagine ; le plafond de pages évite une boucle infinie si le curseur
// cesse un jour de se vider
async function bybit(categorie: string): Promise<any[]> {
  const liste: any[] = [];
  let curseur = "";
  for (let page = 0; page < 20; page++) {
    const url =
      `https://api.bybit.com/v5/market/instruments-info?category=${categorie}&limit=1000` +
      (curseur ? `&cursor=${encodeURIComponent(curseur)}` : "");
    const j = await getJson(url);
    if (j.retCode !== 0) throw new Error(`Bybit retCode ${j.retCode} : ${j.retMsg}`);
    liste.push(...j.result.list);
    curseur = j.result.nextPageCursor ?? "";
    if (!curseur) return liste;
  }
  throw new Error(`Bybit ${categorie} : pagination non terminée après 20 pages`);
}

export const SOURCES: Source[] = [
  {
    bourse: "binance",
    marche: "spot",
    rang: 1,
    lire: async () => {
      const j = await getJson("https://api.binance.com/api/v3/exchangeInfo?permissions=SPOT");
      return (j.symbols as any[]).map((s) => ({
        symbole: s.symbol,
        base: s.baseAsset,
        quote: s.quoteAsset,
        actif: s.status === "TRADING",
        dateBourse: null,
        premarche: false,
      }));
    },
  },
  {
    bourse: "binance",
    marche: "perp",
    rang: 1,
    lire: async () => {
      const j = await getJson("https://fapi.binance.com/fapi/v1/exchangeInfo");
      return (j.symbols as any[])
        // TRADIFI_PERPETUAL et underlyingType EQUITY : actions
        .filter((s) => s.contractType === "PERPETUAL" && !estTradfi(s.underlyingType))
        .map((s) => ({
          symbole: s.symbol,
          base: s.baseAsset,
          quote: s.quoteAsset,
          actif: s.status === "TRADING",
          dateBourse: ms(s.onboardDate),
          premarche: s.underlyingType === "PREMARKET",
        }));
    },
  },
  {
    bourse: "coinbase",
    marche: "spot",
    rang: 1,
    lire: async () => {
      const j = await getJson("https://api.exchange.coinbase.com/products");
      return (j as any[]).map((p) => ({
        symbole: p.id,
        base: p.base_currency,
        quote: p.quote_currency,
        actif: p.status === "online" && !p.trading_disabled,
        dateBourse: null,
        premarche: false,
      }));
    },
  },
  {
    // Les perps de Coinbase sont sur sa bourse internationale, pas sur le spot
    bourse: "coinbase",
    marche: "perp",
    rang: 1,
    lire: async () => {
      const j = await getJson("https://api.international.coinbase.com/api/v1/instruments");
      return (j as any[])
        .filter((i) => i.type === "PERP" && !estTradfi(i.underlying_type))
        .map((i) => ({
          symbole: i.symbol,
          base: i.base_asset_name,
          quote: i.quote_asset_name,
          // PAUSED est fréquent, BTC-PERP compris : le contrat reste coté
          actif: ["TRADING", "PAUSED", "LIMIT_ONLY", "POST_ONLY", "CANCEL_ONLY"].includes(i.trading_state),
          dateBourse: null,
          premarche: false,
        }));
    },
  },
  {
    bourse: "okx",
    marche: "spot",
    rang: 1,
    lire: async () => {
      const j = await getJson("https://www.okx.com/api/v5/public/instruments?instType=SPOT");
      if (j.code !== "0") throw new Error(`OKX code ${j.code} : ${j.msg}`);
      // instCategory : 1 crypto, 3 actions
      return (j.data as any[]).filter((i) => (i.instCategory ?? "1") === "1").map((i) => ({
        symbole: i.instId,
        base: i.baseCcy,
        quote: i.quoteCcy,
        actif: i.state === "live",
        dateBourse: ms(i.listTime),
        premarche: i.ruleType === "pre_market",
      }));
    },
  },
  {
    bourse: "okx",
    marche: "perp",
    rang: 1,
    lire: async () => {
      const j = await getJson("https://www.okx.com/api/v5/public/instruments?instType=SWAP");
      if (j.code !== "0") throw new Error(`OKX code ${j.code} : ${j.msg}`);
      // uly vaut « BTC-USDT » : ctValCcy ne convient pas, il vaut « USD » sur
      // les contrats inverses
      return (j.data as any[]).filter((i) => (i.instCategory ?? "1") === "1").map((i) => {
        const [base, quote] = String(i.uly ?? i.instFamily ?? "").split("-");
        return {
          symbole: i.instId,
          base,
          quote,
          actif: i.state === "live",
          dateBourse: ms(i.listTime),
          premarche: i.ruleType === "pre_market",
        };
      });
    },
  },
  {
    bourse: "bybit",
    marche: "spot",
    rang: 1,
    lire: async () =>
      (await bybit("spot"))
        // symbolType xstocks : actions tokenisées
        .filter((i) => !estTradfi(i.symbolType))
        .map((i) => ({
        symbole: i.symbol,
        base: i.baseCoin,
        quote: i.quoteCoin,
        actif: i.status === "Trading",
        dateBourse: null,
        premarche: false,
      })),
  },
  {
    bourse: "bybit",
    marche: "perp",
    rang: 1,
    lire: async () =>
      (await bybit("linear"))
        // LinearFutures : contrats à échéance, pas des perps
        .filter((i) => i.contractType === "LinearPerpetual" && !estTradfi(i.symbolType))
        .map((i) => {
          const premarche = i.isPreListing === true;
          return {
            symbole: i.symbol,
            base: i.baseCoin,
            quote: i.quoteCoin,
            // en pré-marché, la négociation continue se fait sous le statut PreLaunch
            actif:
              i.status === "Trading" ||
              (premarche && i.preListingInfo?.curAuctionPhase === "ContinuousTrading"),
            dateBourse: ms(i.launchTime),
            premarche,
          };
        }),
  },
  {
    bourse: "kucoin",
    marche: "spot",
    rang: 2,
    lire: async () => {
      const j = await getJson("https://api.kucoin.com/api/v2/symbols");
      if (j.code !== "200000") throw new Error(`KuCoin code ${j.code}`);
      // market « Stocks » : actions tokenisées
      return (j.data as any[]).filter((s) => !estTradfi(s.market)).map((s) => ({
        symbole: s.symbol,
        base: s.baseCurrency,
        quote: s.quoteCurrency,
        actif: s.enableTrading === true,
        dateBourse: null,
        premarche: false,
      }));
    },
  },
  {
    bourse: "kucoin",
    marche: "perp",
    rang: 2,
    lire: async () => {
      const j = await getJson("https://api-futures.kucoin.com/api/v1/contracts/active");
      if (j.code !== "200000") throw new Error(`KuCoin futures code ${j.code}`);
      return (j.data as any[])
        // FFWCSX : perpétuel ; FFICSX : contrat à échéance
        // assetClass STOCK : actions
        .filter((c) => c.type === "FFWCSX" && !estTradfi(c.assetClass, c.subMarketType))
        .map((c) => ({
          symbole: c.symbol,
          base: c.baseCurrency,
          quote: c.quoteCurrency,
          actif: c.status === "Open",
          dateBourse: ms(c.firstOpenDate),
          premarche: false,
        }));
    },
  },
  {
    bourse: "gate",
    marche: "spot",
    rang: 2,
    lire: async () => {
      const j = await getJson("https://api.gateio.ws/api/v4/spot/currency_pairs");
      // Pas de champ de catégorie : xStocks et Ondo se reconnaissent à leur nom
      return (j as any[]).filter((p) => !/xStock|Tokenized/i.test(p.base_name ?? "")).map((p) => ({
        symbole: p.id,
        base: p.base,
        quote: p.quote,
        actif: p.trade_status === "tradable",
        // buy_start est en secondes, 0 pour les paires anciennes
        dateBourse: secondes(p.buy_start),
        premarche: false,
      }));
    },
  },
  {
    bourse: "gate",
    marche: "perp",
    rang: 2,
    lire: async () => {
      const j = await getJson("https://api.gateio.ws/api/v4/futures/usdt/contracts");
      return (j as any[]).filter((c) => !estTradfi(c.contract_type)).map((c) => {
        const [base, quote] = String(c.name).split("_");
        return {
          symbole: c.name,
          base,
          quote,
          actif: !c.in_delisting && (c.status ?? "trading") === "trading",
          dateBourse: secondes(c.launch_time ?? c.create_time),
          premarche: c.is_pre_market === true,
        };
      });
    },
  },
  {
    // Seul le dex principal est relevé : les perps HIP-3 des déployeurs tiers
    // demandent une requête par dex et relèvent d'une autre logique de cotation
    bourse: "hyperliquid",
    marche: "perp",
    rang: 1,
    lire: async () => {
      const j = await hyperliquid("meta");
      return (j.universe as any[]).map((u) => ({
        symbole: u.name,
        base: u.name,
        quote: "USDC",
        actif: u.isDelisted !== true,
        dateBourse: null,
        premarche: false,
      }));
    },
  },
  {
    // Le spot Hyperliquid est ouvert à tout déployeur qui remporte l'enchère :
    // rang 2, et ses noms de tokens sont libres
    bourse: "hyperliquid",
    marche: "spot",
    rang: 2,
    lire: async () => {
      const j = await hyperliquid("spotMeta");
      const tokens = new Map<number, string>((j.tokens as any[]).map((t) => [t.index, t.name]));
      return (j.universe as any[]).map((u) => ({
        symbole: u.name,
        base: tokens.get(u.tokens[0]) ?? "",
        quote: tokens.get(u.tokens[1]) ?? "",
        actif: true,
        dateBourse: null,
        premarche: false,
      }));
    },
  },
  {
    bourse: "mexc",
    marche: "spot",
    rang: 2,
    lire: async () => {
      const j = await getJson("https://api.mexc.com/api/v3/exchangeInfo");
      return (j.symbols as any[]).map((s) => ({
        symbole: s.symbol,
        base: s.baseAsset,
        quote: s.quoteAsset,
        // « 1 » en ligne, « 2 » en pause, « 3 » hors ligne ; ENABLED dans l'ancien format
        actif: (s.status === "1" || s.status === "ENABLED") && s.isSpotTradingAllowed !== false,
        dateBourse: null,
        premarche: false,
      }));
    },
  },
  {
    bourse: "mexc",
    marche: "perp",
    rang: 2,
    lire: async () => {
      const j = await getJson("https://contract.mexc.com/api/v1/contract/detail");
      if (j.success !== true) throw new Error(`MEXC futures code ${j.code}`);
      // Les contrats MEXC sont tous perpétuels. state : 0 actif, 4 en pause
      return (j.data as any[]).filter((c) => !estTradfi(...(c.conceptPlate ?? []))).map((c) => ({
        symbole: c.symbol,
        base: c.baseCoin,
        quote: c.quoteCoin,
        actif: c.state === 0,
        // openingTime vaut 0 une fois ouvert ; createTime date la création
        dateBourse: ms(c.openingTime) ?? ms(c.createTime),
        premarche: c.preMarket === true,
      }));
    },
  },
];

// Normalise et filtre une liste brute. Les doublons de symbole (rares, mais
// possibles sur une API paginée) sont fusionnés en gardant l'état actif.
export function nettoyer(brutes: Paire[]): Paire[] {
  const parSymbole = new Map<string, Paire>();
  for (const p of brutes) {
    if (!p.symbole || !p.base || !p.quote) continue;
    if (LEVIER.test(String(p.base).toUpperCase())) continue;
    const propre = { ...p, base: normaliserBase(p.base), quote: String(p.quote).toUpperCase() };
    const deja = parSymbole.get(p.symbole);
    if (!deja || (!deja.actif && propre.actif)) parSymbole.set(p.symbole, propre);
  }
  return [...parSymbole.values()];
}

async function avecReprise<T>(f: () => Promise<T>): Promise<T> {
  let attente = 2000;
  for (let essai = 0; ; essai++) {
    try {
      return await f();
    } catch (err) {
      if (essai === 3) throw err;
      await sleep(attente);
      attente *= 2;
    }
  }
}

// DateTime ClickHouse, à la seconde, en UTC
function chDate(msEpoch: number): string {
  return new Date(msEpoch).toISOString().slice(0, 19).replace("T", " ");
}

function nomSource(s: Source): string {
  return `${s.bourse} ${s.marche}`;
}

interface Connue {
  symbole: string;
  vu_le: string;
  ouvert_le: string | null;
  date_bourse: string | null;
  initiale: number;
  premarche: number;
}

export async function releverSource(ch: ClickHouseClient, source: Source, maintenant: number): Promise<void> {
  let paires: Paire[];
  try {
    paires = nettoyer(await avecReprise(source.lire));
  } catch (err) {
    console.error(`[listings] ${nomSource(source)} : échec du relevé : ${err}`);
    await journal(ch, source, maintenant, 0, 0, String(err));
    return;
  }

  const connues = new Map<string, Connue>();
  const lignes = await (
    await ch.query({
      query: `SELECT symbole, toString(vu_le) AS vu_le, toString(ouvert_le) AS ouvert_le,
                     toString(date_bourse) AS date_bourse, initiale, premarche
              FROM cex_paires FINAL
              WHERE bourse = {bourse:String} AND marche = {marche:String}`,
      query_params: { bourse: source.bourse, marche: source.marche },
      format: "JSONEachRow",
    })
  ).json<Connue>();
  for (const l of lignes) connues.set(l.symbole, l);

  const premier = connues.size === 0;
  const maintenantCh = chDate(maintenant);
  const aEcrire: Record<string, unknown>[] = [];
  let nouvelles = 0;

  for (const p of paires) {
    const connue = connues.get(p.symbole);
    if (!connue) {
      nouvelles++;
      aEcrire.push({
        bourse: source.bourse,
        marche: source.marche,
        symbole: p.symbole,
        base: p.base,
        quote: p.quote,
        vu_le: maintenantCh,
        ouvert_le: p.actif ? maintenantCh : null,
        date_bourse: p.dateBourse === null ? null : chDate(p.dateBourse),
        initiale: premier ? 1 : 0,
        premarche: p.premarche ? 1 : 0,
      });
    } else if (connue.ouvert_le === null && p.actif) {
      // Paire annoncée lors d'un relevé précédent, échangeable depuis celui-ci.
      // Le drapeau pré-marché est conservé : c'est ainsi qu'elle a démarré.
      aEcrire.push({
        bourse: source.bourse,
        marche: source.marche,
        symbole: p.symbole,
        base: p.base,
        quote: p.quote,
        vu_le: connue.vu_le,
        ouvert_le: maintenantCh,
        date_bourse: connue.date_bourse,
        initiale: connue.initiale,
        premarche: connue.premarche,
      });
    }
  }

  // Garde-fou : si une bourse change le format de ses symboles, toutes ses
  // paires paraissent nouvelles et le relevé inventerait des centaines de
  // lancements en une heure. On refuse plutôt que d'écrire.
  const plafond = Math.max(50, connues.size * 0.2);
  if (!premier && nouvelles > plafond) {
    const erreur = `${nouvelles} paires nouvelles pour ${connues.size} connues : format modifié ? relevé refusé`;
    console.error(`[listings] ${nomSource(source)} : ${erreur}`);
    await journal(ch, source, maintenant, paires.length, 0, erreur);
    return;
  }

  if (aEcrire.length > 0) {
    await ch.insert({ table: "cex_paires", values: aEcrire, format: "JSONEachRow" });
  }
  // Le relevé de référence ne voit aucune cotation, seulement l'existant
  await journal(ch, source, maintenant, paires.length, premier ? 0 : nouvelles, "");
  console.log(
    `[listings] ${nomSource(source)} : ${paires.length} paires, ` +
      (premier ? "relevé de référence" : `${nouvelles} nouvelles`),
  );
}

async function journal(
  ch: ClickHouseClient,
  source: Source,
  maintenant: number,
  paires: number,
  nouvelles: number,
  erreur: string,
): Promise<void> {
  await ch.insert({
    table: "cex_releves",
    values: [
      { releve_le: chDate(maintenant), bourse: source.bourse, marche: source.marche, paires, nouvelles, erreur },
    ],
    format: "JSONEachRow",
  });
}

async function essai(): Promise<void> {
  for (const source of SOURCES) {
    const nom = nomSource(source).padEnd(14);
    try {
      const paires = nettoyer(await avecReprise(source.lire));
      const actives = paires.filter((p) => p.actif).length;
      const datees = paires.filter((p) => p.dateBourse !== null).length;
      const premarche = paires.filter((p) => p.premarche).length;
      const tickers = new Set(paires.map((p) => p.base)).size;
      const recentes = paires
        .filter((p) => p.dateBourse !== null)
        .sort((a, b) => b.dateBourse! - a.dateBourse!)
        .slice(0, 3)
        .map((p) => `${p.base} ${chDate(p.dateBourse!).slice(0, 10)}`);
      console.log(
        `${nom} ${String(paires.length).padStart(5)} paires, ${actives} actives, ${tickers} tickers, ` +
          `${datees} datées, ${premarche} en pré-marché` +
          (recentes.length ? ` — plus récentes : ${recentes.join(", ")}` : ""),
      );
    } catch (err) {
      console.log(`${nom} ÉCHEC : ${err}`);
    }
  }
}

// Une date par paire. Une paire du relevé de référence sans date de bourse est
// réputée ancienne (epoch 0) : elle peut masquer un vrai lancement des premiers
// jours, mais jamais en inventer un. Une paire jamais ouverte n'a pas de date.
// Les deux événements sont ensuite calculés par ticker, spot et perp séparés.
const EVENEMENTS = `
  WITH
    paires AS (
      SELECT bourse, marche, base, premarche,
             if(initiale = 1 AND date_bourse IS NULL,
                toDateTime(0),
                coalesce(date_bourse, ouvert_le)) AS d
      FROM cex_paires FINAL
    ),
    tickers AS (
      SELECT base,
             minIf(d, marche = 'spot') AS spot_d,
             minIf(d, marche = 'perp') AS perp_d,
             argMinIf(premarche, d, marche = 'perp' AND d IS NOT NULL) AS perp_premarche,
             arraySort(groupUniqArrayIf(bourse, marche = 'spot' AND d IS NOT NULL)) AS bourses_spot,
             arraySort(groupUniqArrayIf(bourse, marche = 'perp' AND d IS NOT NULL)) AS bourses_perp
      FROM paires
      GROUP BY base
    ),
    evenements AS (
      SELECT 'lancement' AS evenement, base,
             if(spot_d IS NULL, perp_d, if(perp_d IS NULL, spot_d, least(spot_d, perp_d))) AS le,
             (perp_d IS NOT NULL AND (spot_d IS NULL OR perp_d < spot_d)) AS par_perp,
             (par_perp AND perp_premarche = 1) AS premarche,
             bourses_spot, bourses_perp
      FROM tickers
      UNION ALL
      SELECT 'premier perp' AS evenement, base, perp_d AS le,
             1 AS par_perp, (perp_premarche = 1) AS premarche,
             bourses_spot, bourses_perp
      FROM tickers
      WHERE spot_d IS NOT NULL AND perp_d > spot_d
    )
  SELECT * FROM evenements
  WHERE le >= toStartOfDay(now()) - INTERVAL {jours:UInt32} DAY
    AND le <  toStartOfDay(now())`;

// Ordre du rapport : les événements d'abord, puis le tableau par jour, puis la
// couverture, réduite à une ligne quand toutes les sources ont répondu.
export async function rapport(ch: ClickHouseClient, jours: number, avecDetail = true): Promise<void> {
  const rang1 = (marche: Marche) =>
    SOURCES.filter((s) => s.rang === 1 && s.marche === marche)
      .map((s) => `'${s.bourse}'`)
      .join(",");
  const perpRang1 = `hasAny(bourses_perp, [${rang1("perp")}])`;
  const estRang1 = `(hasAny(bourses_spot, [${rang1("spot")}]) OR ${perpRang1})`;

  if (avecDetail) {
    const detail = await (
      await ch.query({
        query: `SELECT evenement, base, toString(le) AS le, par_perp, premarche, bourses_spot, bourses_perp,
                       ${estRang1} AS rang1
                FROM (${EVENEMENTS})
                ORDER BY rang1 DESC, le DESC`,
        query_params: { jours },
        format: "JSONEachRow",
      })
    ).json<{
      evenement: string;
      base: string;
      le: string;
      par_perp: number;
      premarche: number;
      bourses_spot: string[];
      bourses_perp: string[];
      rang1: number;
    }>();

    const majeurs = detail.filter((d) => Number(d.rang1) === 1);
    console.log(`Événements touchant au moins une bourse de rang 1 :`);
    if (majeurs.length === 0) console.log(`  aucun`);
    for (const d of majeurs) {
      const quoi =
        d.evenement === "lancement"
          ? `lancement${Number(d.par_perp) ? " par perp" : ""}${Number(d.premarche) ? " (pré-marché)" : ""}`
          : `premier perp${Number(d.premarche) ? " (pré-marché)" : ""}`;
      console.log(
        `  ${d.le.slice(0, 16)}  ${d.base.padEnd(12)} ${quoi.padEnd(32)} ` +
          `spot : ${d.bourses_spot.join(", ") || "—"} | perp : ${d.bourses_perp.join(", ") || "—"}`,
      );
    }
    const mineurs = detail.length - majeurs.length;
    if (mineurs > 0) {
      const noms = detail.filter((d) => Number(d.rang1) !== 1).map((d) => d.base);
      console.log(`
Sur les bourses de rang 2 seulement (${mineurs}) : ${noms.join(", ")}`);
    }
    console.log("");
  }

  const parJour = await (
    await ch.query({
      query: `
        SELECT toString(toDate(le)) AS jour,
               countIf(evenement = 'lancement') AS lancements,
               countIf(evenement = 'lancement' AND par_perp) AS par_perp,
               countIf(evenement = 'lancement' AND premarche) AS premarche,
               countIf(evenement = 'lancement' AND ${estRang1}) AS rang1,
               countIf(evenement = 'premier perp') AS premiers_perps,
               countIf(evenement = 'premier perp' AND ${perpRang1}) AS perps_rang1
        FROM (${EVENEMENTS})
        GROUP BY jour ORDER BY jour`,
      query_params: { jours },
      format: "JSONEachRow",
    })
  ).json<Record<string, string | number>>();

  const colonnes = ["lancements", "par_perp", "premarche", "rang1", "premiers_perps", "perps_rang1"];
  const entetes = ["lancements", "dont perp", "pré-marché", "rang 1", "1ers perps", "perps rang 1"];
  console.log(`jour        ${entetes.map((e) => e.padStart(13)).join("")}`);
  const totaux = colonnes.map(() => 0);
  for (const l of parJour) {
    console.log(`${l.jour}  ${colonnes.map((c) => String(l[c]).padStart(13)).join("")}`);
    colonnes.forEach((c, i) => (totaux[i] += Number(l[c])));
  }
  console.log(`moyenne/j   ${totaux.map((t) => (t / jours).toFixed(1).padStart(13)).join("")}`);

  const couverture = await (
    await ch.query({
      query: `
        SELECT bourse, marche,
               toString(min(releve_le)) AS depuis,
               countIf(erreur = '' AND releve_le >= now() - INTERVAL {jours:UInt32} DAY) AS ok,
               countIf(erreur != '' AND releve_le >= now() - INTERVAL {jours:UInt32} DAY) AS echecs
        FROM cex_releves GROUP BY bourse, marche ORDER BY bourse, marche`,
      query_params: { jours },
      format: "JSONEachRow",
    })
  ).json<{ bourse: string; marche: string; depuis: string; ok: string | number; echecs: string | number }>();

  const vues = new Set(couverture.map((c) => `${c.bourse} ${c.marche}`));
  const absentes = SOURCES.map(nomSource).filter((n) => !vues.has(n));
  const enEchec = couverture.filter((c) => Number(c.echecs) > 0 || Number(c.ok) === 0);
  const reussis = couverture.reduce((t, c) => t + Number(c.ok), 0);
  const depuis = couverture.map((c) => c.depuis).sort()[0] ?? "—";

  console.log(
    `
Couverture (${jours} j) : ${SOURCES.length - absentes.length - enEchec.length} sources sur ` +
      `${SOURCES.length} sans échec, ${reussis} relevés réussis, relevé depuis ${depuis}`,
  );
  // Le format « N échecs » est celui que recap-listings.sh cherche pour l'alerte
  for (const c of enEchec) {
    console.log(`  ${c.bourse} ${c.marche} : ${c.echecs} échecs, ${c.ok} relevés réussis`);
  }
  for (const n of absentes) console.log(`  ${n} : jamais relevée`);
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  if (args.includes("--essai")) return essai();

  const ch = createClient({
    url: config.clickhouse.url,
    username: config.clickhouse.username,
    password: config.clickhouse.password,
    database: config.clickhouse.database,
  });

  const iRapport = args.indexOf("--rapport");
  if (iRapport !== -1) {
    await rapport(ch, Number(args[iRapport + 1] ?? 15) || 15, !args.includes("--sans-detail"));
  } else {
    // Même horodatage pour toutes les sources : un relevé est un instant
    const maintenant = Date.now();
    for (const source of SOURCES) await releverSource(ch, source, maintenant);
  }
  await ch.close();
}

if (require.main === module) {
  main().catch((err) => {
    console.error(err);
    process.exit(1);
  });
}
