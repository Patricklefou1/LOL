export function asNumber(v: unknown): number {
  if (typeof v === "number") return v;
  if (typeof v === "bigint") return Number(v);
  if (typeof v === "string") return Number(v);
  if (v && typeof v === "object" && "low" in (v as Record<string, unknown>)) {
    // Long.js : {low, high, unsigned}
    const o = v as { low: number; high: number };
    return Number(o.high ?? 0) * 4294967296 + (Number(o.low ?? 0) >>> 0);
  }
  return Number(v);
}

// bigint -> valeur insérable en JSON : Number si représentable exactement, sinon String
// (ClickHouse accepte les deux pour UInt64/Int64)
export function jsonU64(v: bigint): number | string {
  return v <= BigInt(Number.MAX_SAFE_INTEGER) && v >= -BigInt(Number.MAX_SAFE_INTEGER)
    ? Number(v)
    : v.toString();
}

// DateTime64(3) : "YYYY-MM-DD HH:MM:SS.mmm" en UTC
export function chNow(ms = Date.now()): string {
  return new Date(ms).toISOString().replace("T", " ").replace("Z", "");
}

// Payload protobuf -> JSON rejouable (bytes en base64, bigint en string)
export function normalizeForJson(v: unknown): unknown {
  if (v === null || v === undefined) return v;
  if (Buffer.isBuffer(v) || v instanceof Uint8Array) return Buffer.from(v).toString("base64");
  if (typeof v === "bigint") return v.toString();
  if (Array.isArray(v)) return v.map(normalizeForJson);
  if (typeof v === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, x] of Object.entries(v as Record<string, unknown>)) out[k] = normalizeForJson(x);
    return out;
  }
  return v;
}

export function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}
