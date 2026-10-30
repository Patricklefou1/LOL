import { ClickHouseClient } from "@clickhouse/client";

// Annonces de listing de Binance, OKX et Bybit, lues par leurs API publiques.
// Elles précèdent souvent de plusieurs heures l'ouverture de la paire, que le
// relevé des cotations ne voit qu'une fois ouverte.

export interface Annonce {
  bourse: string;
  id: string;
  titre: string;
  url: string;
  publie_le: number;
}

async function getJson(url: string): Promise<any> {
  const reponse = await fetch(url, {
    headers: { "user-agent": "pumpfun-capture/listings", accept: "application/json" },
    signal: AbortSignal.timeout(30_000),
  });
  if (!reponse.ok) throw new Error(`HTTP ${reponse.status} sur ${url.split("?")[0]}`);
  return reponse.json();
}

const SOURCES_ANNONCES: { bourse: string; lire: () => Promise<Annonce[]> }[] = [
  {
    // Rubrique 48 : « New Cryptocurrency Listing »
    bourse: "binance",
    lire: async () => {
      const j = await getJson(
        "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=48&pageNo=1&pageSize=20",
      );
      const articles: any[] = j.data?.catalogs?.[0]?.articles ?? j.data?.articles ?? [];
      return articles.map((a) => ({
        bourse: "binance",
        id: String(a.code ?? a.id),
        titre: String(a.title ?? ""),
        url: `https://www.binance.com/en/support/announcement/${a.code ?? a.id}`,
        publie_le: Number(a.releaseDate) || Date.now(),
      }));
    },
  },
  {
    bourse: "okx",
    lire: async () => {
      const j = await getJson("https://www.okx.com/api/v5/support/announcements?annType=announcements-new-listings");
      const details: any[] = j.data?.[0]?.details ?? [];
      return details.map((a) => ({
        bourse: "okx",
        id: String(a.url),
        titre: String(a.title ?? ""),
        url: String(a.url),
        publie_le: Number(a.pTime) || Date.now(),
      }));
    },
  },
  {
    bourse: "bybit",
    lire: async () => {
      const j = await getJson("https://api.bybit.com/v5/announcements/index?locale=en-US&type=new_crypto&limit=20");
      return ((j.result?.list ?? []) as any[]).map((a) => ({
        bourse: "bybit",
        id: String(a.url),
        titre: String(a.title ?? ""),
        url: String(a.url),
        publie_le: Number(a.publishTime ?? a.dateTimestamp) || Date.now(),
      }));
    },
  },
];

// Seules les annonces d'un nouveau token crypto comptent : pas les actions et ETF
// (« TradFi Perpetual », xStocks), ni les migrations, retraits, changements de nom
// ou simples ajouts de paires sur un token déjà coté.
const LISTING = /\b(list|lists|listing|listed|launch|launches|launchpool|hodler|airdrop|pre-?market)\b/i;
const HORS_SUJET =
  /\b(delist|delisting|delisted|tradfi|stocks?|xstocks?|bstocks|equit(y|ies)|etf|migration|rebrand|renam|maintenance|suspend|convert)/i;
export const estListingCrypto = (titre: string) => LISTING.test(titre) && !HORS_SUJET.test(titre);

// « Binance Will List Extended (XTEN) », « … XTENUSDT Perpetual … » : les
// tickers sont entre parenthèses ou collés à USDT/USDC
export function tickersDuTitre(titre: string): string[] {
  const trouves = new Set<string>();
  for (const m of titre.matchAll(/\(([A-Z0-9]{2,15})\)/g)) trouves.add(m[1]);
  for (const m of titre.matchAll(/\b([A-Z0-9]{2,15})(?:USDT|USDC)\b/g)) trouves.add(m[1]);
  return [...trouves];
}

function chDate(msEpoch: number): string {
  return new Date(msEpoch).toISOString().slice(0, 19).replace("T", " ");
}

// Renvoie les annonces nouvelles de ce relevé, hors relevé de référence
export async function releverAnnonces(ch: ClickHouseClient, maintenant: number): Promise<Annonce[]> {
  const nouvelles: Annonce[] = [];
  for (const source of SOURCES_ANNONCES) {
    let annonces: Annonce[];
    try {
      annonces = await source.lire();
    } catch (err) {
      console.error(`[listings] annonces ${source.bourse} : ${err}`);
      continue;
    }
    const connues = new Set(
      (
        await (
          await ch.query({
            query: "SELECT id FROM cex_annonces WHERE bourse = {bourse:String}",
            query_params: { bourse: source.bourse },
            format: "JSONEachRow",
          })
        ).json<{ id: string }>()
      ).map((l) => l.id),
    );
    const premier = connues.size === 0;
    const inedites = annonces.filter((a) => a.id && !connues.has(a.id));
    if (inedites.length === 0) continue;
    await ch.insert({
      table: "cex_annonces",
      values: inedites.map((a) => ({
        ...a,
        publie_le: chDate(a.publie_le),
        tickers: tickersDuTitre(a.titre),
        vu_le: chDate(maintenant),
        initiale: premier ? 1 : 0,
      })),
      format: "JSONEachRow",
    });
    if (!premier) nouvelles.push(...inedites.filter((a) => estListingCrypto(a.titre)));
    console.log(`[listings] annonces ${source.bourse} : ${premier ? "référence" : `${inedites.length} nouvelles`}`);
  }
  return nouvelles;
}

export async function essaiAnnonces(): Promise<void> {
  for (const source of SOURCES_ANNONCES) {
    try {
      const annonces = await source.lire();
      const derniere = annonces[0];
      console.log(
        `annonces ${source.bourse.padEnd(8)} ${annonces.length} lues` +
          `, ${annonces.filter((a) => estListingCrypto(a.titre)).length} listings crypto` +
          (derniere
            ? ` — dernière : ${derniere.titre.slice(0, 70)} [${tickersDuTitre(derniere.titre).join(", ")}]` +
              (estListingCrypto(derniere.titre) ? "" : " (ignorée)")
            : ""),
      );
    } catch (err) {
      console.log(`annonces ${source.bourse.padEnd(8)} ÉCHEC : ${err}`);
    }
  }
}

export async function rapportAnnonces(ch: ClickHouseClient, jours: number): Promise<void> {
  const annonces = await (
    await ch.query({
      query: `SELECT bourse, titre, url, toString(publie_le) AS publie
              FROM cex_annonces FINAL
              WHERE initiale = 0 AND publie_le >= toStartOfDay(now()) - INTERVAL {jours:UInt32} DAY
              ORDER BY publie DESC`,
      query_params: { jours },
      format: "JSONEachRow",
    })
  ).json<{ bourse: string; titre: string; url: string; publie: string }>();
  const listings = annonces.filter((a) => estListingCrypto(a.titre));
  console.log(
    `\nAnnonces de listing (${jours} j) : ${listings.length}` +
      (annonces.length > listings.length ? `, ${annonces.length - listings.length} autres annonces ignorées` : ""),
  );
  for (const a of listings) {
    console.log(`  ${a.publie.slice(0, 16)}  ${a.bourse.padEnd(8)} ${a.titre}\n      ${a.url}`);
  }
}
