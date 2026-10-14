import { createClient, ClickHouseClient } from "@clickhouse/client";
import { config } from "./config";
import { sleep } from "./util";

// Relevé des cotations sur Binance, Coinbase, OKX, Bybit, KuCoin et Gate.
//
//   npm run listings                  -- un relevé, écrit dans cex_paires
//   npm run listings -- --essai       -- lit les six bourses, n'écrit rien
//   npm run listings -- --rapport 15  -- lancements par jour sur 15 jours
//
// Un « lancement » est un ticker jamais coté auparavant sur aucune des six
// bourses. Le premier relevé d'une bourse sert de référence : tout ce qu'il
// voit est marqué `initiale` et ne compte jamais comme un lancement.

interface Paire {
  symbole: string;
  base: string;
  quote: string;
  actif: boolean;
  // date de cotation déclarée par la bourse, en ms, quand elle en publie une
  dateBourse: number | null;
}

interface Bourse {
  nom: string;
  // 1 : Binance, Coinbase, OKX, Bybit. 2 : KuCoin, Gate, qui cotent beaucoup
  // plus tôt et beaucoup plus de petits projets.
  rang: 1 | 2;
  lire: () => Promise<Paire[]>;
}

// Tokens à effet de levier (BTC3L, ETH5S) : des produits de la bourse, pas des projets.
const LEVIER = /\d+[LS]$/;

async function getJson(url: string): Promise<any> {
  const reponse = await fetch(url, {
    // Coinbase refuse les requêtes sans User-Agent
    headers: { "user-agent": "pumpfun-capture/listings", accept: "application/json" },
    signal: AbortSignal.timeout(30_000),
  });
  if (!reponse.ok) throw new Error(`HTTP ${reponse.status} sur ${url}`);
  return reponse.json();
}

function ms(v: unknown): number | null {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : null;
}

export const BOURSES: Bourse[] = [
  {
    nom: "binance",
    rang: 1,
    lire: async () => {
      const j = await getJson("https://api.binance.com/api/v3/exchangeInfo?permissions=SPOT");
      return (j.symbols as any[]).map((s) => ({
        symbole: s.symbol,
        base: s.baseAsset,
        quote: s.quoteAsset,
        actif: s.status === "TRADING",
        dateBourse: null,
      }));
    },
  },
  {
    nom: "coinbase",
    rang: 1,
    lire: async () => {
      const j = await getJson("https://api.exchange.coinbase.com/products");
      return (j as any[]).map((p) => ({
        symbole: p.id,
        base: p.base_currency,
        quote: p.quote_currency,
        actif: p.status === "online" && !p.trading_disabled,
        dateBourse: null,
      }));
    },
  },
  {
    nom: "okx",
    rang: 1,
    lire: async () => {
      const j = await getJson("https://www.okx.com/api/v5/public/instruments?instType=SPOT");
      if (j.code !== "0") throw new Error(`OKX code ${j.code} : ${j.msg}`);
      return (j.data as any[]).map((i) => ({
        symbole: i.instId,
        base: i.baseCcy,
        quote: i.quoteCcy,
        actif: i.state === "live",
        dateBourse: ms(i.listTime),
      }));
    },
  },
  {
    nom: "bybit",
    rang: 1,
    lire: async () => {
      const paires: Paire[] = [];
      let curseur = "";
      // Bybit pagine ; le plafond de pages évite une boucle infinie si le
      // curseur cesse un jour de se vider
      for (let page = 0; page < 20; page++) {
        const url =
          "https://api.bybit.com/v5/market/instruments-info?category=spot&limit=1000" +
          (curseur ? `&cursor=${encodeURIComponent(curseur)}` : "");
        const j = await getJson(url);
        if (j.retCode !== 0) throw new Error(`Bybit retCode ${j.retCode} : ${j.retMsg}`);
        for (const i of j.result.list as any[]) {
          paires.push({
            symbole: i.symbol,
            base: i.baseCoin,
            quote: i.quoteCoin,
            actif: i.status === "Trading",
            dateBourse: null,
          });
        }
        curseur = j.result.nextPageCursor ?? "";
        if (!curseur) return paires;
      }
      throw new Error("Bybit : pagination non terminée après 20 pages");
    },
  },
  {
    nom: "kucoin",
    rang: 2,
    lire: async () => {
      const j = await getJson("https://api.kucoin.com/api/v2/symbols");
      if (j.code !== "200000") throw new Error(`KuCoin code ${j.code}`);
      return (j.data as any[]).map((s) => ({
        symbole: s.symbol,
        base: s.baseCurrency,
        quote: s.quoteCurrency,
        actif: s.enableTrading === true,
        dateBourse: null,
      }));
    },
  },
  {
    nom: "gate",
    rang: 2,
    lire: async () => {
      const j = await getJson("https://api.gateio.ws/api/v4/spot/currency_pairs");
      return (j as any[]).map((p) => ({
        symbole: p.id,
        base: p.base,
        quote: p.quote,
        actif: p.trade_status === "tradable",
        // buy_start est en secondes, 0 pour les paires anciennes
        dateBourse: ms(p.buy_start) === null ? null : Number(p.buy_start) * 1000,
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
    const base = String(p.base).toUpperCase();
    if (LEVIER.test(base)) continue;
    const propre = { ...p, base, quote: String(p.quote).toUpperCase() };
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

interface Connue {
  symbole: string;
  vu_le: string;
  ouvert_le: string | null;
  date_bourse: string | null;
  initiale: number;
}

export async function releverBourse(ch: ClickHouseClient, bourse: Bourse, maintenant: number): Promise<void> {
  let paires: Paire[];
  try {
    paires = nettoyer(await avecReprise(bourse.lire));
  } catch (err) {
    console.error(`[listings] ${bourse.nom} : échec du relevé : ${err}`);
    await journal(ch, bourse.nom, maintenant, 0, 0, String(err));
    return;
  }

  const connues = new Map<string, Connue>();
  const lignes = await (
    await ch.query({
      query: `SELECT symbole, toString(vu_le) AS vu_le, toString(ouvert_le) AS ouvert_le,
                     toString(date_bourse) AS date_bourse, initiale
              FROM cex_paires FINAL WHERE bourse = {bourse:String}`,
      query_params: { bourse: bourse.nom },
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
        bourse: bourse.nom,
        symbole: p.symbole,
        base: p.base,
        quote: p.quote,
        vu_le: maintenantCh,
        ouvert_le: p.actif ? maintenantCh : null,
        date_bourse: p.dateBourse === null ? null : chDate(p.dateBourse),
        initiale: premier ? 1 : 0,
      });
    } else if (connue.ouvert_le === null && p.actif) {
      // Paire annoncée lors d'un relevé précédent, échangeable depuis celui-ci
      aEcrire.push({
        bourse: bourse.nom,
        symbole: p.symbole,
        base: p.base,
        quote: p.quote,
        vu_le: connue.vu_le,
        ouvert_le: maintenantCh,
        date_bourse: connue.date_bourse,
        initiale: connue.initiale,
      });
    }
  }

  // Garde-fou : si une bourse change le format de ses symboles, toutes ses
  // paires paraissent nouvelles et le relevé inventerait des centaines de
  // lancements en une heure. On refuse plutôt que d'écrire.
  const plafond = Math.max(50, connues.size * 0.2);
  if (!premier && nouvelles > plafond) {
    const erreur = `${nouvelles} paires nouvelles pour ${connues.size} connues : format modifié ? relevé refusé`;
    console.error(`[listings] ${bourse.nom} : ${erreur}`);
    await journal(ch, bourse.nom, maintenant, paires.length, 0, erreur);
    return;
  }

  if (aEcrire.length > 0) {
    await ch.insert({ table: "cex_paires", values: aEcrire, format: "JSONEachRow" });
  }
  // Le relevé de référence ne voit aucune cotation, seulement l'existant
  await journal(ch, bourse.nom, maintenant, paires.length, premier ? 0 : nouvelles, "");
  console.log(
    `[listings] ${bourse.nom} : ${paires.length} paires, ` +
      (premier ? "relevé de référence" : `${nouvelles} nouvelles`),
  );
}

async function journal(
  ch: ClickHouseClient,
  bourse: string,
  maintenant: number,
  paires: number,
  nouvelles: number,
  erreur: string,
): Promise<void> {
  await ch.insert({
    table: "cex_releves",
    values: [{ releve_le: chDate(maintenant), bourse, paires, nouvelles, erreur }],
    format: "JSONEachRow",
  });
}

async function essai(): Promise<void> {
  for (const bourse of BOURSES) {
    try {
      const paires = nettoyer(await avecReprise(bourse.lire));
      const actives = paires.filter((p) => p.actif).length;
      const datees = paires.filter((p) => p.dateBourse !== null).length;
      const bases = new Set(paires.map((p) => p.base)).size;
      console.log(
        `${bourse.nom.padEnd(9)} ${String(paires.length).padStart(5)} paires, ` +
          `${actives} actives, ${bases} tickers, ${datees} datées par la bourse`,
      );
    } catch (err) {
      console.log(`${bourse.nom.padEnd(9)} ÉCHEC : ${err}`);
    }
  }
}

// Date de lancement d'un ticker : la plus ancienne date connue parmi ses paires.
// Une paire du relevé de référence sans date de bourse rend le ticker
// « incertain » : il était peut-être coté là bien avant.
const LANCEMENTS = `
  WITH
    paires AS (
      SELECT bourse, base,
             coalesce(date_bourse, if(initiale = 1, NULL, ouvert_le)) AS d,
             (initiale = 1 AND date_bourse IS NULL) AS inconnue
      FROM cex_paires FINAL
    ),
    tickers AS (
      SELECT base,
             min(d) AS lancement,
             max(inconnue) AS incertain,
             arraySort(groupUniqArray(bourse)) AS bourses
      FROM paires
      GROUP BY base
    )
  SELECT * FROM tickers
  WHERE lancement >= toStartOfDay(now()) - INTERVAL {jours:UInt32} DAY
    AND lancement <  toStartOfDay(now())`;

async function rapport(ch: ClickHouseClient, jours: number): Promise<void> {
  const rang1 = BOURSES.filter((b) => b.rang === 1).map((b) => `'${b.nom}'`).join(",");

  const parJour = await (
    await ch.query({
      query: `
        SELECT toString(toDate(lancement)) AS jour,
               count() AS lancements,
               countIf(NOT incertain) AS certains,
               countIf(hasAny(bourses, [${rang1}])) AS rang1,
               countIf(length(bourses) >= 2) AS multi
        FROM (${LANCEMENTS})
        GROUP BY jour ORDER BY jour`,
      query_params: { jours },
      format: "JSONEachRow",
    })
  ).json<{ jour: string; lancements: string; certains: string; rang1: string; multi: string }>();

  const couverture = await (
    await ch.query({
      query: `
        SELECT bourse,
               toString(min(releve_le)) AS depuis,
               countIf(erreur = '' AND releve_le >= now() - INTERVAL {jours:UInt32} DAY) AS ok,
               countIf(erreur != '' AND releve_le >= now() - INTERVAL {jours:UInt32} DAY) AS echecs
        FROM cex_releves GROUP BY bourse ORDER BY bourse`,
      query_params: { jours },
      format: "JSONEachRow",
    })
  ).json<{ bourse: string; depuis: string; ok: string; echecs: string }>();

  console.log(`Couverture du relevé (${jours} derniers jours) :`);
  for (const c of couverture) {
    console.log(`  ${c.bourse.padEnd(9)} depuis ${c.depuis}, ${c.ok} relevés réussis, ${c.echecs} échecs`);
  }

  console.log(`\njour        lancements  certains  rang 1  ≥2 bourses`);
  const total = { lancements: 0, certains: 0, rang1: 0, multi: 0 };
  for (const l of parJour) {
    console.log(
      `${l.jour}  ${l.lancements.padStart(10)}  ${l.certains.padStart(8)}  ` +
        `${l.rang1.padStart(6)}  ${l.multi.padStart(10)}`,
    );
    total.lancements += Number(l.lancements);
    total.certains += Number(l.certains);
    total.rang1 += Number(l.rang1);
    total.multi += Number(l.multi);
  }
  const moy = (n: number) => (n / jours).toFixed(1);
  console.log(
    `moyenne/j   ${moy(total.lancements).padStart(10)}  ${moy(total.certains).padStart(8)}  ` +
      `${moy(total.rang1).padStart(6)}  ${moy(total.multi).padStart(10)}`,
  );

  const detail = await (
    await ch.query({
      query: `SELECT base, toString(lancement) AS lancement, incertain, bourses
              FROM (${LANCEMENTS})
              WHERE hasAny(bourses, [${rang1}]) ORDER BY lancement DESC`,
      query_params: { jours },
      format: "JSONEachRow",
    })
  ).json<{ base: string; lancement: string; incertain: number; bourses: string[] }>();

  console.log(`\nLancements cotés sur au moins une bourse de rang 1 :`);
  for (const d of detail) {
    console.log(
      `  ${d.lancement}  ${d.base.padEnd(12)} ${d.bourses.join(", ")}${d.incertain ? "  (incertain)" : ""}`,
    );
  }
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
    await rapport(ch, Number(args[iRapport + 1] ?? 15) || 15);
  } else {
    // Même horodatage pour les six bourses : un relevé est un instant
    const maintenant = Date.now();
    for (const bourse of BOURSES) await releverBourse(ch, bourse, maintenant);
  }
  await ch.close();
}

if (require.main === module) {
  main().catch((err) => {
    console.error(err);
    process.exit(1);
  });
}
