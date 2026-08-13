import bs58 from "bs58";
import { createClient } from "@clickhouse/client";
import { config } from "./config";

// Renseigne `pumpswap_pools` en lisant les comptes Pool par RPC.
//
//   npm run pools            -- tous les pools inconnus
//   npm run pools -- 5000    -- les 5000 plus actifs seulement
//
// Relançable sans risque : seuls les pools absents de la table sont demandés.

const PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA";
const WSOL = "So11111111111111111111111111111111111111112";

// Compte Pool, après les 8 octets de discriminator Anchor :
//   @8 pool_bump | @9 index | @11 creator | @43 base_mint | @75 quote_mint
//   @107 lp_mint | @139 pool_base_ata | @171 pool_quote_ata | @203 lp_supply
//   @211 coin_creator
const OFF_BASE_MINT = 43;
const OFF_QUOTE_MINT = 75;
const OFF_COIN_CREATOR = 211;
const TAILLE_MIN = OFF_COIN_CREATOR + 32;

const LOT = 100; // plafond de getMultipleAccounts

interface Pool {
  pool: string;
  base_mint: string;
  quote_mint: string;
  coin_creator: string;
  est_sol: number;
}

function cle(buf: Buffer, offset: number): string {
  return bs58.encode(buf.subarray(offset, offset + 32));
}

async function rpc(url: string, methode: string, params: unknown[]): Promise<any> {
  const reponse = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: methode, params }),
  });
  if (!reponse.ok) throw new Error(`RPC ${methode} : HTTP ${reponse.status}`);
  const json = (await reponse.json()) as any;
  if (json.error) throw new Error(`RPC ${methode} : ${JSON.stringify(json.error)}`);
  return json.result;
}

// Un lot peut échouer pour une raison passagère (limite de débit, coupure).
// On réessaie avec un recul croissant plutôt que d'abandonner le lot : un pool
// manquant se traduirait par une exclusion silencieuse dans toutes les études.
async function avecReprise<T>(f: () => Promise<T>, quoi: string): Promise<T | null> {
  let attente = 500;
  for (let essai = 0; essai < 5; essai++) {
    try {
      return await f();
    } catch (err) {
      if (essai === 4) {
        console.error(`  échec définitif sur ${quoi} : ${err}`);
        return null;
      }
      await new Promise((r) => setTimeout(r, attente));
      attente = Math.min(attente * 2, 8000);
    }
  }
  return null;
}

async function main(): Promise<void> {
  const url = process.env.RPC_URL;
  if (!url) throw new Error("Variable d'environnement manquante : RPC_URL");

  const limite = Number(process.argv[2] ?? 0);
  const ch = createClient({
    url: config.clickhouse.url,
    username: config.clickhouse.username,
    password: config.clickhouse.password,
    database: config.clickhouse.database,
  });

  // Les pools les plus actifs d'abord : si la lecture est interrompue, ce sont
  // ceux dont l'absence fausserait le plus les mesures.
  const requete = `
    SELECT t.pool AS pool
    FROM (SELECT pool, count() AS n FROM pumpswap_trades GROUP BY pool) t
    LEFT ANTI JOIN pumpswap_pools p ON p.pool = t.pool
    ORDER BY t.n DESC
    ${limite > 0 ? `LIMIT ${limite}` : ""}`;

  const lignes = await (await ch.query({ query: requete, format: "JSONEachRow" })).json<{ pool: string }>();
  const inconnus = lignes.map((l) => l.pool);
  console.log(`${inconnus.length} pools à identifier`);
  if (inconnus.length === 0) {
    await ch.close();
    return;
  }

  let ecrits = 0;
  let illisibles = 0;
  let etrangers = 0;

  for (let i = 0; i < inconnus.length; i += LOT) {
    const lot = inconnus.slice(i, i + LOT);
    const res = await avecReprise(
      () => rpc(url, "getMultipleAccounts", [lot, { encoding: "base64" }]),
      `lot ${i / LOT + 1}`,
    );
    if (!res) continue;

    const trouves: Pool[] = [];
    (res.value ?? []).forEach((compte: any, n: number) => {
      if (!compte) {
        illisibles++;
        return;
      }
      // Un compte qui n'appartient pas à PumpSwap n'a pas cette structure :
      // le décoder produirait des clés plausibles mais fausses.
      if (compte.owner !== PUMPSWAP_PROGRAM_ID) {
        etrangers++;
        return;
      }
      const brut = Buffer.from(compte.data[0], "base64");
      if (brut.length < TAILLE_MIN) {
        illisibles++;
        return;
      }
      const quote_mint = cle(brut, OFF_QUOTE_MINT);
      trouves.push({
        pool: lot[n],
        base_mint: cle(brut, OFF_BASE_MINT),
        quote_mint,
        coin_creator: cle(brut, OFF_COIN_CREATOR),
        est_sol: quote_mint === WSOL ? 1 : 0,
      });
    });

    if (trouves.length > 0) {
      await ch.insert({ table: "pumpswap_pools", values: trouves, format: "JSONEachRow" });
      ecrits += trouves.length;
    }
    if ((i / LOT) % 20 === 0) {
      console.log(`  ${Math.min(i + LOT, inconnus.length)}/${inconnus.length} — ${ecrits} identifiés`);
    }
  }

  console.log(`\n${ecrits} pools identifiés, ${illisibles} illisibles, ${etrangers} hors PumpSwap`);
  const bilan = await (
    await ch.query({
      query: `SELECT countIf(est_sol = 1) AS en_sol, countIf(est_sol = 0) AS hors_sol,
                     uniqExact(quote_mint) AS quotes_distincts
              FROM pumpswap_pools FINAL`,
      format: "JSONEachRow",
    })
  ).json<{ en_sol: string; hors_sol: string; quotes_distincts: string }>();
  console.log(
    `table : ${bilan[0].en_sol} pools en SOL, ${bilan[0].hors_sol} hors SOL, ` +
      `${bilan[0].quotes_distincts} quotes distincts`,
  );

  await ch.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
