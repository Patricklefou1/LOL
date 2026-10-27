import { ClickHouseClient } from "@clickhouse/client";
import { sleep } from "./util";

// Source CoinGecko du relevé des cotations : les tokens nouvellement référencés,
// lancés sur DEX comme sur bourse centralisée.
//
// Clé « Demo » gratuite dans .env (COINGECKO_API_KEY) : 10 000 appels par mois,
// le relevé horaire en consomme environ 50 par jour. Sans clé, la source est
// ignorée sans faire échouer le relevé des bourses.

const API = "https://api.coingecko.com/api/v3";

// Seuil de volume sur 24 h en dessous duquel un ajout n'est que compté, pas
// listé : CoinGecko référence aussi des memecoins au volume symbolique.
const VOLUME_MIN = Number(process.env.COINGECKO_VOLUME_MIN ?? 100_000);

// Garde-fou : CoinGecko ajoute de l'ordre de 50 à 150 tokens par jour. Des
// milliers d'un coup trahissent un changement d'identifiants, pas des lancements.
const PLAFOND_NOUVEAUX = 1000;

function cle(): string | undefined {
  return process.env.COINGECKO_API_KEY || undefined;
}

async function cg(chemin: string): Promise<any> {
  let attente = 5000;
  for (let essai = 0; ; essai++) {
    const reponse = await fetch(`${API}${chemin}`, {
      headers: { "x-cg-demo-api-key": cle()!, accept: "application/json" },
      signal: AbortSignal.timeout(60_000),
    });
    // 429 : limite de 30 appels par minute de l'offre Demo
    if (reponse.status === 429 && essai < 3) {
      await sleep(attente);
      attente *= 2;
      continue;
    }
    if (!reponse.ok) throw new Error(`CoinGecko HTTP ${reponse.status} sur ${chemin.split("?")[0]}`);
    return reponse.json();
  }
}

function chDate(msEpoch: number): string {
  return new Date(msEpoch).toISOString().slice(0, 19).replace("T", " ");
}

async function journal(ch: ClickHouseClient, maintenant: number, tokens: number, nouveaux: number, erreur: string) {
  await ch.insert({
    table: "cg_releves",
    values: [{ releve_le: chDate(maintenant), tokens, nouveaux, erreur }],
    format: "JSONEachRow",
  });
}

export async function releverCoingecko(ch: ClickHouseClient, maintenant: number): Promise<void> {
  if (!cle()) {
    console.log("[listings] coingecko : COINGECKO_API_KEY absent, source ignorée");
    return;
  }

  let liste: { id: string; symbol: string; name: string; platforms?: Record<string, string> }[];
  try {
    liste = await cg("/coins/list?include_platform=true");
  } catch (err) {
    console.error(`[listings] coingecko : échec du relevé : ${err}`);
    await journal(ch, maintenant, 0, 0, String(err));
    return;
  }

  const connus = new Set(
    (
      await (await ch.query({ query: "SELECT id FROM cg_tokens", format: "JSONEachRow" })).json<{ id: string }>()
    ).map((l) => l.id),
  );
  const premier = connus.size === 0;
  const nouveaux = liste.filter((t) => t.id && !connus.has(t.id));

  if (!premier && nouveaux.length > PLAFOND_NOUVEAUX) {
    const erreur = `${nouveaux.length} tokens nouveaux pour ${connus.size} connus : relevé refusé`;
    console.error(`[listings] coingecko : ${erreur}`);
    await journal(ch, maintenant, liste.length, 0, erreur);
    return;
  }

  if (nouveaux.length > 0) {
    await ch.insert({
      table: "cg_tokens",
      values: nouveaux.map((t) => ({
        id: t.id,
        symbole: String(t.symbol ?? "").toUpperCase(),
        nom: t.name ?? "",
        contrats: JSON.stringify(t.platforms ?? {}),
        vu_le: chDate(maintenant),
        initiale: premier ? 1 : 0,
      })),
      format: "JSONEachRow",
    });
  }

  // Marchés des ajouts des 15 derniers jours, par lots de 250 (plafond de l'API)
  const recents = (
    await (
      await ch.query({
        query: `SELECT id FROM cg_tokens FINAL WHERE initiale = 0 AND vu_le >= now() - INTERVAL 15 DAY`,
        format: "JSONEachRow",
      })
    ).json<{ id: string }>()
  ).map((l) => l.id);
  for (let i = 0; i < recents.length; i += 250) {
    const lot = recents.slice(i, i + 250);
    try {
      const marches: any[] = await cg(
        `/coins/markets?vs_currency=usd&per_page=250&ids=${encodeURIComponent(lot.join(","))}`,
      );
      if (marches.length > 0) {
        await ch.insert({
          table: "cg_marches",
          values: marches.map((m) => ({
            id: m.id,
            releve_le: chDate(maintenant),
            prix: Number(m.current_price) || 0,
            mcap: Number(m.market_cap) || 0,
            volume: Number(m.total_volume) || 0,
          })),
          format: "JSONEachRow",
        });
      }
    } catch (err) {
      // Les marchés ne servent qu'au seuil : leur absence ne perd aucun ajout
      console.error(`[listings] coingecko : marchés indisponibles : ${err}`);
    }
  }

  await journal(ch, maintenant, liste.length, premier ? 0 : nouveaux.length, "");
  console.log(
    `[listings] coingecko : ${liste.length} tokens, ` +
      (premier ? "relevé de référence" : `${nouveaux.length} nouveaux`),
  );
}

export async function essaiCoingecko(): Promise<void> {
  if (!cle()) {
    console.log("coingecko      COINGECKO_API_KEY absent de .env");
    return;
  }
  try {
    const liste: any[] = await cg("/coins/list?include_platform=true");
    const avecContrat = liste.filter((t) => Object.values(t.platforms ?? {}).some(Boolean)).length;
    console.log(`coingecko      ${liste.length} tokens, ${avecContrat} avec adresse de contrat`);
  } catch (err) {
    console.log(`coingecko      ÉCHEC : ${err}`);
  }
}

// Noms courts des chaînes les plus fréquentes, pour un mail lisible
const CHAINES: Record<string, string> = {
  "binance-smart-chain": "BSC",
  ethereum: "ETH",
  solana: "SOL",
  base: "Base",
  "arbitrum-one": "Arbitrum",
  "polygon-pos": "Polygon",
  avalanche: "Avalanche",
  "optimistic-ethereum": "Optimism",
  sui: "Sui",
  tron: "Tron",
  "the-open-network": "TON",
  "hyperliquid": "Hyperliquid",
};

export async function rapportCoingecko(ch: ClickHouseClient, jours: number, avecDetail: boolean): Promise<void> {
  const etat = await (
    await ch.query({
      query: `SELECT countIf(erreur = '') AS ok, countIf(erreur != '') AS echecs, toString(min(releve_le)) AS depuis
              FROM cg_releves WHERE releve_le >= now() - INTERVAL {jours:UInt32} DAY`,
      query_params: { jours },
      format: "JSONEachRow",
    })
  ).json<{ ok: number | string; echecs: number | string; depuis: string }>();
  const { ok, echecs } = etat[0] ?? { ok: 0, echecs: 0 };

  const ajouts = await (
    await ch.query({
      query: `
        WITH
          m AS (SELECT id, argMax(mcap, releve_le) AS mcap, argMax(volume, releve_le) AS volume
                FROM cg_marches GROUP BY id),
          -- Seules les cotations récentes comptent : une paire ancienne qui porte
          -- le même ticker est un autre token (« BTC » Big Titty Coin n'est pas
          -- coté sur Binance). La référence sans date est réputée ancienne.
          c AS (SELECT base, arraySort(groupUniqArray(bourse)) AS bourses
                FROM cex_paires FINAL
                WHERE ouvert_le IS NOT NULL
                  AND NOT (initiale = 1 AND date_bourse IS NULL)
                  AND coalesce(date_bourse, ouvert_le) >= now() - INTERVAL 60 DAY
                GROUP BY base)
        SELECT t.id AS id, t.symbole AS symbole, t.nom AS nom, t.contrats AS contrats,
               toString(t.vu_le) AS vu_le, m.mcap AS mcap, m.volume AS volume, c.bourses AS bourses
        FROM (SELECT * FROM cg_tokens FINAL
              WHERE initiale = 0
                AND vu_le >= toStartOfDay(now()) - INTERVAL {jours:UInt32} DAY
                AND vu_le <  toStartOfDay(now())) AS t
        LEFT JOIN m ON m.id = t.id
        LEFT JOIN c ON c.base = t.symbole
        ORDER BY m.volume DESC`,
      query_params: { jours },
      format: "JSONEachRow",
    })
  ).json<{
    id: string;
    symbole: string;
    nom: string;
    contrats: string;
    vu_le: string;
    mcap: number;
    volume: number;
    bourses: string[];
  }>();

  const retenus = ajouts.filter((a) => Number(a.volume) >= VOLUME_MIN);
  const k = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)} M$` : `${Math.round(n / 1e3)} k$`);

  console.log(
    `\nCoinGecko (${jours} j) : ${ajouts.length} tokens ajoutés, ` +
      `${retenus.length} au-dessus de ${k(VOLUME_MIN)} de volume sur 24 h` +
      (jours > 1 ? `, soit ${(retenus.length / jours).toFixed(1)} par jour` : ""),
  );
  if (avecDetail) {
    for (const a of retenus) {
      const contrats = Object.entries(JSON.parse(a.contrats || "{}") as Record<string, string>).filter(([, v]) => v);
      const ou = contrats.length
        ? contrats
            .slice(0, 2)
            .map(([chaine, adr]) => `${CHAINES[chaine] ?? chaine} ${adr}`)
            .join(" ; ")
        : "chaîne propre";
      const cex = a.bourses?.length ? `coté sur ${a.bourses.join(", ")}` : "DEX seulement";
      console.log(
        `  ${a.symbole.padEnd(10)} ${a.nom.slice(0, 28).padEnd(28)} vol ${k(Number(a.volume)).padStart(8)}` +
          `  mcap ${k(Number(a.mcap)).padStart(8)}  ${cex}\n      ${ou}`,
      );
    }
  }
  // Le format « N échecs » est celui que recap-listings.sh cherche pour l'alerte
  if (cle() && Number(ok) === 0) console.log(`  coingecko : jamais relevée`);
  if (Number(echecs) > 0) console.log(`  coingecko : ${echecs} échecs, ${ok} relevés réussis`);
}
