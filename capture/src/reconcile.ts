import bs58 from "bs58";
import { createClient, ClickHouseClient } from "@clickhouse/client";
import { config } from "./config";
import { decodePumpEvents, priceSol, PUMP_PROGRAM_ID } from "./decode/pumpfun";
import { chNow, jsonU64, normalizeForJson } from "./util";

// Phase 2 — réconciliation : rejoue par RPC getBlock les slots des trous
// enregistrés dans capture_gaps et insère ce qui manque (source='rpc_backfill').
// Mode --verify N : échantillonne N slots capturés des dernières 24 h et mesure
// le taux de transactions Pump.fun manquantes (le < 0,1 % de la DoD phase 1).
//
// Nécessite RPC_URL dans .env (endpoint HTTP JSON-RPC — celui du plan Triton
// convient, n'importe quel RPC mainnet aussi : getBlock est en commitment
// confirmed/finalized, la latence n'a aucune importance ici).

const RPC_URL = process.env.RPC_URL ?? "";
const MAX_GAP_SLOTS = 3000;
const CONCURRENCY = 3;

interface RpcTx {
  transaction: { signatures: string[]; message: { accountKeys: string[] } };
  meta: any;
}

async function rpcCall(method: string, params: unknown[]): Promise<any> {
  let delay = 500;
  for (let attempt = 1; ; attempt++) {
    try {
      const res = await fetch(RPC_URL, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
      });
      if (res.status === 429 || res.status >= 500) throw new Error(`HTTP ${res.status}`);
      const body: any = await res.json();
      if (body.error) {
        // slot sauté / bloc indisponible : pas une erreur réseau, on remonte tel quel
        return { error: body.error };
      }
      return { result: body.result };
    } catch (err) {
      if (attempt >= 4) throw err;
      await new Promise((r) => setTimeout(r, delay));
      delay *= 3;
    }
  }
}

async function getBlock(slot: number): Promise<{ txs: RpcTx[]; blockTimeMs: number } | null> {
  const { result, error } = await rpcCall("getBlock", [
    slot,
    {
      encoding: "json",
      transactionDetails: "full",
      rewards: false,
      maxSupportedTransactionVersion: 0,
      commitment: "finalized",
    },
  ]);
  if (error || !result) return null; // slot sauté par le cluster (fork) ou hors rétention
  return {
    txs: (result.transactions ?? []) as RpcTx[],
    blockTimeMs: (result.blockTime ?? Math.floor(Date.now() / 1000)) * 1000,
  };
}

function txAccountKeys(tx: RpcTx): string[] {
  return [
    ...(tx.transaction.message.accountKeys ?? []),
    ...(tx.meta?.loadedAddresses?.writable ?? []),
    ...(tx.meta?.loadedAddresses?.readonly ?? []),
  ];
}

function isPumpTx(tx: RpcTx): boolean {
  return txAccountKeys(tx).includes(PUMP_PROGRAM_ID);
}

// Adapte le format JSON du RPC (base58 partout) vers la forme attendue par le
// décodeur (la même que le protobuf gRPC : bytes).
function rpcTxToDecoderInfo(tx: RpcTx): any {
  return {
    signature: bs58.decode(tx.transaction.signatures[0]),
    transaction: {
      message: { accountKeys: (tx.transaction.message.accountKeys ?? []).map((k) => bs58.decode(k)) },
    },
    meta: {
      err: tx.meta?.err ?? null,
      logMessages: tx.meta?.logMessages ?? [],
      innerInstructions: (tx.meta?.innerInstructions ?? []).map((group: any) => ({
        index: group.index,
        instructions: (group.instructions ?? []).map((ix: any) => ({
          programIdIndex: ix.programIdIndex,
          data: typeof ix.data === "string" ? bs58.decode(ix.data) : Buffer.alloc(0),
        })),
      })),
      loadedWritableAddresses: (tx.meta?.loadedAddresses?.writable ?? []).map((k: string) => bs58.decode(k)),
      loadedReadonlyAddresses: (tx.meta?.loadedAddresses?.readonly ?? []).map((k: string) => bs58.decode(k)),
    },
  };
}

function fmtDt(ms: number): string {
  return new Date(ms).toISOString().replace("T", " ").replace("Z", "");
}

async function existingSignatures(client: ClickHouseClient, fromSlot: number, toSlot: number): Promise<Set<string>> {
  const db = config.clickhouse.database;
  const rs = await client.query({
    query: `
      SELECT signature FROM ${db}.raw_transactions WHERE slot BETWEEN {a:UInt64} AND {b:UInt64}
      UNION DISTINCT SELECT signature FROM ${db}.trades WHERE slot BETWEEN {a:UInt64} AND {b:UInt64}
      UNION DISTINCT SELECT signature FROM ${db}.creations WHERE slot BETWEEN {a:UInt64} AND {b:UInt64}
      UNION DISTINCT SELECT signature FROM ${db}.completions WHERE slot BETWEEN {a:UInt64} AND {b:UInt64}`,
    query_params: { a: fromSlot, b: toSlot },
    format: "JSONEachRow",
  });
  const out = new Set<string>();
  for (const r of await rs.json<any>()) out.add(r.signature);
  return out;
}

// Insère les événements d'une transaction récupérée par RPC (mêmes tables que la capture)
function insertTx(
  rows: { raw: any[]; trades: any[]; creations: any[]; completions: any[] },
  tx: RpcTx,
  slot: number,
  blockTimeMs: number,
): number {
  const info = rpcTxToDecoderInfo(tx);
  const signature = tx.transaction.signatures[0];
  const receivedAt = fmtDt(blockTimeMs);
  const isFailed = tx.meta?.err ? 1 : 0;

  if (config.captureRaw) {
    rows.raw.push({
      slot,
      signature,
      received_at: receivedAt,
      is_failed: isFailed,
      payload: JSON.stringify(normalizeForJson(tx)),
      source: "rpc_backfill",
    });
  }
  if (isFailed) return 0;

  let n = 0;
  for (const ev of decodePumpEvents(info)) {
    n++;
    if (ev.kind === "trade") {
      rows.trades.push({
        slot,
        signature,
        received_at: receivedAt,
        mint: ev.mint,
        user: ev.user,
        is_buy: ev.isBuy ? 1 : 0,
        sol_amount: jsonU64(ev.solAmount),
        token_amount: jsonU64(ev.tokenAmount),
        event_timestamp: jsonU64(ev.timestamp),
        virtual_sol_reserves: jsonU64(ev.virtualSolReserves),
        virtual_token_reserves: jsonU64(ev.virtualTokenReserves),
        real_sol_reserves: jsonU64(ev.realSolReserves),
        real_token_reserves: jsonU64(ev.realTokenReserves),
        price_sol: priceSol(ev.virtualSolReserves, ev.virtualTokenReserves),
        source: "rpc_backfill",
      });
    } else if (ev.kind === "create") {
      rows.creations.push({
        slot,
        signature,
        received_at: receivedAt,
        mint: ev.mint,
        bonding_curve: ev.bondingCurve,
        user: ev.user,
        creator: ev.creator,
        name: ev.name,
        symbol: ev.symbol,
        source: "rpc_backfill",
      });
    } else {
      rows.completions.push({
        slot,
        signature,
        received_at: receivedAt,
        mint: ev.mint,
        user: ev.user,
        bonding_curve: ev.bondingCurve,
        event_timestamp: jsonU64(ev.timestamp),
        source: "rpc_backfill",
      });
    }
  }
  return n;
}

async function flushRows(
  client: ClickHouseClient,
  rows: { raw: any[]; trades: any[]; creations: any[]; completions: any[] },
): Promise<void> {
  const tables: Array<[string, any[]]> = [
    ["raw_transactions", rows.raw],
    ["trades", rows.trades],
    ["creations", rows.creations],
    ["completions", rows.completions],
  ];
  for (const [table, values] of tables) {
    if (values.length > 0) {
      await client.insert({ table, values, format: "JSONEachRow" });
      values.length = 0;
    }
  }
}

async function mapConcurrent<T, R>(items: T[], limit: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(items.length);
  let next = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const i = next++;
      out[i] = await fn(items[i]);
    }
  });
  await Promise.all(workers);
  return out;
}

async function backfillGaps(client: ClickHouseClient, slotBudget: number): Promise<void> {
  const db = config.clickhouse.database;
  const gaps: Array<{ from: number; to: number }> = [];
  {
    const done = new Set<string>();
    const rsDone = await client.query({
      query: `SELECT DISTINCT from_slot, to_slot FROM ${db}.gap_backfills`,
      format: "JSONEachRow",
    });
    for (const r of await rsDone.json<any>()) done.add(`${r.from_slot}-${r.to_slot}`);
    const rsGaps = await client.query({
      query: `SELECT DISTINCT from_slot, to_slot FROM ${db}.capture_gaps ORDER BY from_slot`,
      format: "JSONEachRow",
    });
    for (const r of await rsGaps.json<any>()) {
      if (!done.has(`${r.from_slot}-${r.to_slot}`)) gaps.push({ from: Number(r.from_slot), to: Number(r.to_slot) });
    }
  }
  console.log(`[reconcile] ${gaps.length} trous à traiter`);

  let budget = slotBudget;
  for (const gap of gaps) {
    const size = gap.to - gap.from + 1;
    if (size > MAX_GAP_SLOTS) {
      console.warn(
        `[reconcile] trou ${gap.from}-${gap.to} (${size} slots) trop large pour le RPC — panne longue : traiter via backfill historique`,
      );
      continue;
    }
    if (size > budget) {
      console.log(`[reconcile] budget de slots épuisé, reprendre au prochain run`);
      break;
    }
    budget -= size;

    const known = await existingSignatures(client, gap.from, gap.to);
    const rows: { raw: any[]; trades: any[]; creations: any[]; completions: any[] } = {
      raw: [],
      trades: [],
      creations: [],
      completions: [],
    };
    let slotsOk = 0, slotsSkipped = 0, txsRecovered = 0, errors = 0;

    const slots = Array.from({ length: size }, (_, i) => gap.from + i);
    await mapConcurrent(slots, CONCURRENCY, async (slot) => {
      try {
        const block = await getBlock(slot);
        if (!block) {
          slotsSkipped++;
          return;
        }
        slotsOk++;
        for (const tx of block.txs) {
          if (!isPumpTx(tx)) continue;
          const sig = tx.transaction.signatures[0];
          if (known.has(sig)) continue;
          insertTx(rows, tx, slot, block.blockTimeMs);
          txsRecovered++;
        }
      } catch (err) {
        errors++;
        console.error(`[reconcile] slot ${slot} :`, err instanceof Error ? err.message : err);
      }
    });

    await flushRows(client, rows);
    await client.insert({
      table: "gap_backfills",
      values: [
        {
          from_slot: gap.from,
          to_slot: gap.to,
          backfilled_at: chNow(),
          slots_ok: slotsOk,
          slots_skipped: slotsSkipped,
          txs_recovered: txsRecovered,
          errors,
        },
      ],
      format: "JSONEachRow",
    });
    console.log(
      `[reconcile] trou ${gap.from}-${gap.to} : ${slotsOk} slots lus, ${slotsSkipped} sautés, ${txsRecovered} tx récupérées, ${errors} erreurs`,
    );
  }
}

async function verify(client: ClickHouseClient, sample: number): Promise<void> {
  const db = config.clickhouse.database;
  const rs = await client.query({
    query: `SELECT DISTINCT slot FROM ${db}.slots
            WHERE received_at > now() - INTERVAL 1 DAY ORDER BY rand() LIMIT {n:UInt32}`,
    query_params: { n: sample },
    format: "JSONEachRow",
  });
  const slots = (await rs.json<any>()).map((r: any) => Number(r.slot));
  console.log(`[verify] échantillon de ${slots.length} slots des dernières 24 h`);

  let onchain = 0, captured = 0, checked = 0, skipped = 0;
  const missing: string[] = [];

  await mapConcurrent(slots, CONCURRENCY, async (slot) => {
    const block = await getBlock(slot);
    if (!block) {
      skipped++;
      return;
    }
    checked++;
    const pumpSigs = block.txs.filter((tx) => isPumpTx(tx) && !tx.meta?.err).map((tx) => tx.transaction.signatures[0]);
    if (pumpSigs.length === 0) return;
    const known = await existingSignatures(client, slot, slot);
    for (const sig of pumpSigs) {
      onchain++;
      if (known.has(sig)) captured++;
      else if (missing.length < 10) missing.push(`${slot}:${sig}`);
    }
  });

  const missRate = onchain > 0 ? ((onchain - captured) / onchain) * 100 : 0;
  console.log(
    JSON.stringify(
      {
        slots_verifies: checked,
        slots_sautes: skipped,
        tx_pump_onchain: onchain,
        tx_capturees: captured,
        taux_manquant_pct: Number(missRate.toFixed(4)),
        dod_ok: missRate < 0.1,
        exemples_manquants: missing,
      },
      null,
      2,
    ),
  );
}

async function main(): Promise<void> {
  if (!RPC_URL) {
    throw new Error("RPC_URL manquant dans .env (endpoint HTTP JSON-RPC pour getBlock)");
  }
  const client = createClient({
    url: config.clickhouse.url,
    username: config.clickhouse.username,
    password: config.clickhouse.password,
    database: config.clickhouse.database,
    request_timeout: 300_000,
  });

  const verifyArg = process.argv.indexOf("--verify");
  if (verifyArg >= 0) {
    await verify(client, Number(process.argv[verifyArg + 1] ?? 200));
  } else {
    const budgetArg = process.argv.indexOf("--limit-slots");
    await backfillGaps(client, budgetArg >= 0 ? Number(process.argv[budgetArg + 1] ?? 5000) : 5000);
  }
  await client.close();
}

if (require.main === module) {
  main().catch((err) => {
    console.error("[reconcile] échec :", err);
    process.exit(1);
  });
}
