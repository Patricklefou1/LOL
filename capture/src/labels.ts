import { createClient, ClickHouseClient } from "@clickhouse/client";
import { config } from "./config";
import { chNow } from "./util";

// Phase 2 — labellisation des issues : pour chaque token créé un jour J,
// produit token_summary (résumé de vie) et token_minute (matrice
// token × minute × horizon des rendements forward).
//
// Conventions documentées :
// - prix en carry-forward (dernier trade connu) ; avant le premier trade,
//   prix initial de la courbe (30 / 1.073e9 SOL par token, constante protocole) ;
// - les fwd_* dont l'horizon dépasse la fin de série utilisent le dernier
//   prix (plat) — l'illiquidité réelle est traitée par le modèle de coûts
//   des études, pas ici ;
// - le "dev" est le wallet `user` de l'événement Create ;
// - rug_dev_dump = le dev a revendu ≥ 80 % de ses tokens achetés sur la
//   courbe, première vente < 24 h (les ventes via wallets tiers relèvent
//   de l'analyse de clusters, phase 3) ;
// - vie plafonnée à 72 h après création (LIFE_CAP_MIN).

export const HORIZONS_MIN = [1, 5, 15, 60, 240] as const;
export const LIFE_CAP_MIN = 4320;
const CURVE_SELLABLE_TOKENS = 793_100_000;
const INITIAL_PRICE_SOL = 30 / 1_073_000_000;

export interface CreationLite {
  mint: string;
  createdAtMs: number;
  createdSlot: number;
  dev: string;
  name: string;
  symbol: string;
}

export interface TradeLite {
  tsMs: number;
  slot: number;
  isBuy: boolean;
  user: string;
  sol: number;
  tokens: number;
  price: number;
  realSol: number;
}

// Max glissant sur la fenêtre forward (t+1 .. t+h], en O(L) par horizon
// (deque monotone décroissante d'indices).
export function forwardWindowMax(price: number[], h: number): number[] {
  const L = price.length;
  const out = new Array<number>(L);
  const deq: number[] = [];
  const push = (i: number) => {
    while (deq.length && price[deq[deq.length - 1]] <= price[i]) deq.pop();
    deq.push(i);
  };
  for (let i = 1; i <= Math.min(h, L - 1); i++) push(i);
  for (let t = 0; t < L; t++) {
    if (t > 0) {
      if (deq.length && deq[0] === t) deq.shift();
      if (t + h < L) push(t + h);
    }
    out[t] = deq.length ? price[deq[0]] : price[t];
  }
  return out;
}

function fmtDt(ms: number): string {
  return new Date(ms).toISOString().replace("T", " ").replace("Z", "");
}

function fmtDtSec(ms: number): string {
  return new Date(ms).toISOString().slice(0, 19).replace("T", " ");
}

export function computeLabels(
  c: CreationLite,
  tradesIn: TradeLite[],
  graduatedAtMs: number | null,
  createdDay: string,
): { summary: Record<string, unknown>; minutes: Record<string, unknown>[] } {
  const trades = [...tradesIn].sort((a, b) => a.tsMs - b.tsMs || a.slot - b.slot);
  const labeledAt = chNow();

  const base = {
    mint: c.mint,
    created_day: createdDay,
    created_at: fmtDt(c.createdAtMs),
    created_slot: c.createdSlot,
    dev: c.dev,
    name: c.name,
    symbol: c.symbol,
    labeled_at: labeledAt,
  };

  if (trades.length === 0) {
    return {
      summary: {
        ...base,
        n_trades: 0, n_buys: 0, n_sells: 0, uniq_traders: 0, uniq_buyers: 0,
        vol_sol: 0, first_price: 0, max_price: 0, max_mult: 0, minutes_to_max: 0,
        last_trade_at: fmtDt(c.createdAtMs), lifespan_min: 0,
        graduated: graduatedAtMs ? 1 : 0,
        minutes_to_graduation: graduatedAtMs ? (graduatedAtMs - c.createdAtMs) / 60000 : null,
        dev_buy_sol: 0, dev_tokens_bought: 0, dev_tokens_sold: 0, dev_sold_fraction: 0,
        dev_first_sell_minutes: null, rug_dev_dump: 0,
        snipe_slot0_sol: 0, snipe_slot0_share: 0, snipe_slot0_buyers: 0,
      },
      minutes: [],
    };
  }

  let nBuys = 0, nSells = 0, volSol = 0;
  let maxPrice = 0, maxPriceTs = c.createdAtMs;
  let devBuySol = 0, devTokensBought = 0, devTokensSold = 0;
  let devFirstSellTs: number | null = null;
  let snipeSol = 0, snipeTokens = 0;
  const snipeBuyers = new Set<string>();
  const traders = new Set<string>();
  const buyers = new Set<string>();

  for (const t of trades) {
    traders.add(t.user);
    volSol += t.sol;
    if (t.isBuy) {
      nBuys++;
      buyers.add(t.user);
    } else {
      nSells++;
    }
    if (t.price > maxPrice) {
      maxPrice = t.price;
      maxPriceTs = t.tsMs;
    }
    if (t.user === c.dev) {
      if (t.isBuy) {
        devBuySol += t.sol;
        devTokensBought += t.tokens;
      } else {
        devTokensSold += t.tokens;
        if (devFirstSellTs === null) devFirstSellTs = t.tsMs;
      }
    } else if (t.isBuy && t.slot === c.createdSlot) {
      snipeSol += t.sol;
      snipeTokens += t.tokens;
      snipeBuyers.add(t.user);
    }
  }

  const firstPrice = trades.find((t) => t.price > 0)?.price ?? INITIAL_PRICE_SOL;
  const lastTradeMs = trades[trades.length - 1].tsMs;
  const devSoldFraction =
    devTokensBought > 0 ? Math.min(1, devTokensSold / devTokensBought) : devTokensSold > 0 ? 1 : 0;
  const devFirstSellMin = devFirstSellTs !== null ? (devFirstSellTs - c.createdAtMs) / 60000 : null;

  // ----- série minute -----
  const lastMin = Math.max(0, Math.floor((lastTradeMs - c.createdAtMs) / 60000));
  const L = Math.min(lastMin, LIFE_CAP_MIN) + 1;
  const price = new Array<number>(L).fill(0);
  const realSol = new Array<number>(L).fill(0);
  const agg = Array.from({ length: L }, () => ({
    nBuys: 0, nSells: 0, volBuy: 0, volSell: 0,
    buyers: null as Set<string> | null, sellers: null as Set<string> | null,
  }));

  for (const t of trades) {
    const idx = Math.min(Math.max(0, Math.floor((t.tsMs - c.createdAtMs) / 60000)), L - 1);
    price[idx] = t.price > 0 ? t.price : price[idx];
    realSol[idx] = t.realSol;
    const a = agg[idx];
    if (t.isBuy) {
      a.nBuys++;
      a.volBuy += t.sol;
      (a.buyers ??= new Set()).add(t.user);
    } else {
      a.nSells++;
      a.volSell += t.sol;
      (a.sellers ??= new Set()).add(t.user);
    }
  }

  let lastPrice = INITIAL_PRICE_SOL;
  let lastReal = 0;
  for (let i = 0; i < L; i++) {
    if (price[i] > 0) lastPrice = price[i];
    else price[i] = lastPrice;
    if (realSol[i] > 0) lastReal = realSol[i];
    else realSol[i] = lastReal;
  }

  const fwdMax = new Map<number, number[]>();
  for (const h of HORIZONS_MIN) fwdMax.set(h, forwardWindowMax(price, h));

  const minutes: Record<string, unknown>[] = [];
  for (let t = 0; t < L; t++) {
    const a = agg[t];
    const row: Record<string, unknown> = {
      mint: c.mint,
      created_day: createdDay,
      minute_idx: t,
      ts: fmtDtSec(c.createdAtMs + t * 60000),
      price: price[t],
      n_buys: Math.min(a.nBuys, 65535),
      n_sells: Math.min(a.nSells, 65535),
      uniq_buyers: Math.min(a.buyers?.size ?? 0, 65535),
      uniq_sellers: Math.min(a.sellers?.size ?? 0, 65535),
      vol_buy_sol: a.volBuy,
      vol_sell_sol: a.volSell,
      net_flow_sol: a.volBuy - a.volSell,
      real_sol_curve: realSol[t],
    };
    for (const h of HORIZONS_MIN) {
      const end = Math.min(t + h, L - 1);
      row[`fwd_ret_${h}m`] = price[t] > 0 ? price[end] / price[t] - 1 : 0;
      if (h !== 1) {
        const m = fwdMax.get(h)![t];
        row[`fwd_max_ret_${h}m`] = price[t] > 0 ? m / price[t] - 1 : 0;
      }
    }
    minutes.push(row);
  }

  const summary = {
    ...base,
    n_trades: trades.length,
    n_buys: nBuys,
    n_sells: nSells,
    uniq_traders: traders.size,
    uniq_buyers: buyers.size,
    vol_sol: volSol,
    first_price: firstPrice,
    max_price: maxPrice,
    max_mult: firstPrice > 0 ? maxPrice / firstPrice : 0,
    minutes_to_max: (maxPriceTs - c.createdAtMs) / 60000,
    last_trade_at: fmtDt(lastTradeMs),
    lifespan_min: (lastTradeMs - c.createdAtMs) / 60000,
    graduated: graduatedAtMs ? 1 : 0,
    minutes_to_graduation: graduatedAtMs ? (graduatedAtMs - c.createdAtMs) / 60000 : null,
    dev_buy_sol: devBuySol,
    dev_tokens_bought: devTokensBought,
    dev_tokens_sold: devTokensSold,
    dev_sold_fraction: devSoldFraction,
    dev_first_sell_minutes: devFirstSellMin,
    rug_dev_dump: devSoldFraction >= 0.8 && devFirstSellMin !== null && devFirstSellMin <= 1440 ? 1 : 0,
    snipe_slot0_sol: snipeSol,
    snipe_slot0_share: snipeTokens / CURVE_SELLABLE_TOKENS,
    snipe_slot0_buyers: Math.min(snipeBuyers.size, 65535),
  };

  return { summary, minutes };
}

// ---------- pipeline ----------

function parseChTs(s: string): number {
  return Date.parse(s.replace(" ", "T") + "Z");
}

function argValue(name: string): string | undefined {
  const eq = process.argv.find((a) => a.startsWith(`--${name}=`));
  if (eq) return eq.slice(name.length + 3);
  const i = process.argv.indexOf(`--${name}`);
  if (i >= 0 && process.argv[i + 1] && !process.argv[i + 1].startsWith("--")) return process.argv[i + 1];
  return undefined;
}

function dayString(d: Date): string {
  return d.toISOString().slice(0, 10);
}

async function insertBatch(
  client: ClickHouseClient,
  table: string,
  rows: Record<string, unknown>[],
): Promise<void> {
  if (rows.length === 0) return;
  await client.insert({ table, values: rows, format: "JSONEachRow" });
}

async function labelDay(client: ClickHouseClient, day: string): Promise<void> {
  const db = config.clickhouse.database;
  const from = `${day} 00:00:00.000`;
  const toExclusive = `${dayString(new Date(Date.parse(day + "T00:00:00Z") + 4 * 86400_000))} 00:00:00.000`;
  const creationsSub = `SELECT mint FROM ${db}.creations WHERE toDate(received_at) = {day:Date}`;

  const creations = new Map<string, CreationLite>();
  {
    const rs = await client.query({
      query: `SELECT mint, min(received_at) AS created_at, min(slot) AS created_slot,
                     any(user) AS dev, any(name) AS name, any(symbol) AS symbol
              FROM ${db}.creations WHERE toDate(received_at) = {day:Date} GROUP BY mint`,
      query_params: { day },
      format: "JSONEachRow",
    });
    for (const r of await rs.json<any>()) {
      creations.set(r.mint, {
        mint: r.mint,
        createdAtMs: parseChTs(r.created_at),
        createdSlot: Number(r.created_slot),
        dev: r.dev,
        name: r.name,
        symbol: r.symbol,
      });
    }
  }
  console.log(`[labels] ${day} : ${creations.size} tokens créés`);
  if (creations.size === 0) return;

  const graduations = new Map<string, number>();
  {
    const rs = await client.query({
      query: `SELECT mint, min(received_at) AS at FROM ${db}.completions
              WHERE mint IN (${creationsSub}) GROUP BY mint`,
      query_params: { day },
      format: "JSONEachRow",
    });
    for (const r of await rs.json<any>()) graduations.set(r.mint, parseChTs(r.at));
  }

  // idempotence : on remplace la partition du jour (clé de partition = Date)
  for (const table of ["token_summary", "token_minute"]) {
    try {
      await client.command({ query: `ALTER TABLE ${db}.${table} DROP PARTITION '${day}'` });
    } catch {
      // partition absente : premier passage
    }
  }

  const rs = await client.query({
    query: `SELECT mint, slot, received_at, is_buy, user, sol_amount, token_amount, price_sol, real_sol_reserves
            FROM ${db}.trades
            WHERE mint IN (${creationsSub})
              AND received_at >= {from:String} AND received_at < {to:String}
            ORDER BY mint, slot, signature`,
    query_params: { day, from, to: toExclusive },
    format: "JSONEachRow",
  });

  let summaries: Record<string, unknown>[] = [];
  let minutes: Record<string, unknown>[] = [];
  let currentMint = "";
  let buffer: TradeLite[] = [];
  let tokensDone = 0;
  const labeledMints = new Set<string>();

  const flushToken = async () => {
    const c = creations.get(currentMint);
    if (c) {
      const out = computeLabels(c, buffer, graduations.get(currentMint) ?? null, day);
      summaries.push(out.summary);
      minutes.push(...out.minutes);
      labeledMints.add(currentMint);
      tokensDone++;
      if (summaries.length >= 500) {
        await insertBatch(client, "token_summary", summaries);
        summaries = [];
      }
      if (minutes.length >= 20_000) {
        await insertBatch(client, "token_minute", minutes);
        minutes = [];
      }
      if (tokensDone % 2000 === 0) console.log(`[labels] ${day} : ${tokensDone} tokens labellisés…`);
    }
    buffer = [];
  };

  const stream = rs.stream();
  for await (const rows of stream) {
    for (const row of rows as Array<{ json<T>(): T }>) {
      const r = row.json<any>();
      if (r.mint !== currentMint) {
        if (currentMint) await flushToken();
        currentMint = r.mint;
      }
      buffer.push({
        tsMs: parseChTs(r.received_at),
        slot: Number(r.slot),
        isBuy: Number(r.is_buy) === 1,
        user: r.user,
        sol: Number(r.sol_amount) / 1e9,
        tokens: Number(r.token_amount) / 1e6,
        price: Number(r.price_sol),
        realSol: Number(r.real_sol_reserves) / 1e9,
      });
    }
  }
  if (currentMint) await flushToken();

  // tokens créés sans aucun trade dans la fenêtre
  for (const [mint, c] of creations) {
    if (!labeledMints.has(mint)) {
      const out = computeLabels(c, [], graduations.get(mint) ?? null, day);
      summaries.push(out.summary);
      tokensDone++;
    }
  }

  await insertBatch(client, "token_summary", summaries);
  await insertBatch(client, "token_minute", minutes);
  console.log(`[labels] ${day} : terminé, ${tokensDone} tokens labellisés`);
}

async function main(): Promise<void> {
  // par défaut : J-4 (vie de 72 h + horizons clos au moment du calcul)
  const defaultDay = dayString(new Date(Date.now() - 4 * 86400_000));
  const from = argValue("from") ?? argValue("day") ?? defaultDay;
  const to = argValue("to") ?? argValue("day") ?? defaultDay;

  const client = createClient({
    url: config.clickhouse.url,
    username: config.clickhouse.username,
    password: config.clickhouse.password,
    database: config.clickhouse.database,
    request_timeout: 300_000,
  });

  for (let t = Date.parse(from + "T00:00:00Z"); t <= Date.parse(to + "T00:00:00Z"); t += 86400_000) {
    await labelDay(client, dayString(new Date(t)));
  }
  await client.close();
}

if (require.main === module) {
  main().catch((err) => {
    console.error("[labels] échec :", err);
    process.exit(1);
  });
}
