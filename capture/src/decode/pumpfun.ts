import { createHash } from "crypto";
import bs58 from "bs58";
import { resolveAccountKeys } from "./accounts";

export const PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P";

// Tag d'instruction des "event CPI" Anchor (self-CPI portant l'événement).
// Les logs "Program data:" existent aussi mais sont tronqués sous charge,
// donc le chemin CPI est la source primaire et les logs le fallback.
const EVENT_CPI_TAG = Buffer.from("e445a52e51cb9a1d", "hex");

// Discriminator d'événement Anchor : sha256("event:<Nom>")[0..8]
function eventDiscriminator(name: string): Buffer {
  return createHash("sha256").update(`event:${name}`).digest().subarray(0, 8);
}

const DISC_CREATE = eventDiscriminator("CreateEvent");
const DISC_TRADE = eventDiscriminator("TradeEvent");
const DISC_COMPLETE = eventDiscriminator("CompleteEvent");

// Événements auxiliaires du programme (frais créateur, extensions de comptes,
// migration PumpSwap, incentives…) : reconnus et comptés mais non stockés en
// tables dédiées — leur contenu reste disponible dans raw_transactions.
// Un nom erroné produit un discriminator qui ne matchera jamais : sans danger.
const OTHER_EVENT_NAMES = [
  "CollectCreatorFeeEvent",
  "SetCreatorEvent",
  "AdminSetCreatorEvent",
  "ExtendAccountEvent",
  "SetParamsEvent",
  "UpdateGlobalAuthorityEvent",
  "CompletePumpAmmMigrationEvent",
  "SetMetaplexCreatorEvent",
  "SyncUserVolumeAccumulatorEvent",
  "InitUserVolumeAccumulatorEvent",
  "ClaimTokenIncentivesEvent",
  "AdminUpdateTokenIncentivesEvent",
];
const OTHER_DISCS = new Map<string, string>(
  OTHER_EVENT_NAMES.map((n) => [eventDiscriminator(n).toString("hex"), n]),
);

class Reader {
  private off = 0;
  constructor(private buf: Buffer) {}
  remaining(): number {
    return this.buf.length - this.off;
  }
  u8(): number {
    const v = this.buf.readUInt8(this.off);
    this.off += 1;
    return v;
  }
  bool(): boolean {
    return this.u8() === 1;
  }
  u64(): bigint {
    const v = this.buf.readBigUInt64LE(this.off);
    this.off += 8;
    return v;
  }
  i64(): bigint {
    const v = this.buf.readBigInt64LE(this.off);
    this.off += 8;
    return v;
  }
  pubkey(): string {
    const v = bs58.encode(this.buf.subarray(this.off, this.off + 32));
    this.off += 32;
    return v;
  }
  str(): string {
    const len = this.buf.readUInt32LE(this.off);
    this.off += 4;
    const v = this.buf.subarray(this.off, this.off + len).toString("utf8");
    this.off += len;
    return v;
  }
}

export interface CreateEvent {
  kind: "create";
  name: string;
  symbol: string;
  uri: string;
  mint: string;
  bondingCurve: string;
  user: string;
  creator: string;
}

export interface TradeEvent {
  kind: "trade";
  mint: string;
  solAmount: bigint;
  tokenAmount: bigint;
  isBuy: boolean;
  user: string;
  timestamp: bigint;
  virtualSolReserves: bigint;
  virtualTokenReserves: bigint;
  realSolReserves: bigint;
  realTokenReserves: bigint;
}

export interface CompleteEvent {
  kind: "complete";
  user: string;
  mint: string;
  bondingCurve: string;
  timestamp: bigint;
}

export interface OtherEvent {
  kind: "other";
  name: string;
}

export type PumpEvent = CreateEvent | TradeEvent | CompleteEvent | OtherEvent;

// Le programme a ajouté des champs de fin de structure au fil des versions
// (creator, fees…) : on parse le préfixe stable et on tolère les octets restants.
function parseEvent(buf: Buffer): PumpEvent | null {
  if (buf.length < 8) return null;
  const disc = buf.subarray(0, 8);
  const r = new Reader(buf.subarray(8));
  try {
    if (disc.equals(DISC_TRADE)) {
      return {
        kind: "trade",
        mint: r.pubkey(),
        solAmount: r.u64(),
        tokenAmount: r.u64(),
        isBuy: r.bool(),
        user: r.pubkey(),
        timestamp: r.i64(),
        virtualSolReserves: r.u64(),
        virtualTokenReserves: r.u64(),
        realSolReserves: r.u64(),
        realTokenReserves: r.u64(),
      };
    }
    if (disc.equals(DISC_CREATE)) {
      const ev: CreateEvent = {
        kind: "create",
        name: r.str(),
        symbol: r.str(),
        uri: r.str(),
        mint: r.pubkey(),
        bondingCurve: r.pubkey(),
        user: r.pubkey(),
        creator: "",
      };
      if (r.remaining() >= 32) ev.creator = r.pubkey();
      return ev;
    }
    if (disc.equals(DISC_COMPLETE)) {
      return {
        kind: "complete",
        user: r.pubkey(),
        mint: r.pubkey(),
        bondingCurve: r.pubkey(),
        timestamp: r.remaining() >= 8 ? r.i64() : 0n,
      };
    }
    const otherName = OTHER_DISCS.get(disc.toString("hex"));
    if (otherName) {
      return { kind: "other", name: otherName };
    }
  } catch {
    return null;
  }
  return null;
}

// info = SubscribeUpdateTransactionInfo (typé any : la forme exacte varie selon
// la version du client gRPC ; les champs utilisés ici sont stables)
export function decodePumpEvents(info: any): PumpEvent[] {
  const buffers: Buffer[] = [];

  const msg = info?.transaction?.message;
  const meta = info?.meta;

  if (msg && meta) {
    const keys = resolveAccountKeys(info);

    for (const inner of meta.innerInstructions ?? []) {
      for (const ix of inner.instructions ?? []) {
        const idx = Number(ix.programIdIndex);
        if (keys[idx] !== PUMP_PROGRAM_ID) continue;
        const data = Buffer.from(ix.data ?? []);
        if (data.length >= 16 && data.subarray(0, 8).equals(EVENT_CPI_TAG)) {
          buffers.push(data.subarray(8));
        }
      }
    }
  }

  if (buffers.length === 0) {
    for (const line of meta?.logMessages ?? []) {
      if (typeof line === "string" && line.startsWith("Program data: ")) {
        try {
          buffers.push(Buffer.from(line.slice("Program data: ".length), "base64"));
        } catch {
          // ligne corrompue/tronquée : ignorée
        }
      }
    }
  }

  const events: PumpEvent[] = [];
  for (const buf of buffers) {
    const ev = parseEvent(buf);
    if (ev) events.push(ev);
  }
  return events;
}

// Prix spot en SOL par token : réserves virtuelles, décimales SOL=9, token=6
export function priceSol(virtualSolReserves: bigint, virtualTokenReserves: bigint): number {
  const vTok = Number(virtualTokenReserves);
  if (vTok <= 0) return 0;
  return Number(virtualSolReserves) / 1e9 / (vTok / 1e6);
}
