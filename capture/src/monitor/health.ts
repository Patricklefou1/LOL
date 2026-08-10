import { Sink } from "../sink/clickhouse";
import { chNow } from "../util";

// Suivi de santé de la capture : compteurs de débit, détection de trous de slots,
// lag de réception approximatif (delta entre l'arrivée du slot et celle des tx du
// même slot). En commitment processed, l'ordre slot/tx n'est pas strict : le lag
// est un indicateur de santé, pas une mesure scientifique — la vraie horloge de
// la recherche reste le slot lui-même.
export class Health {
  private counters: Record<string, number> = {};
  private lastSlot = 0;
  private slotSeenAt = new Map<number, number>();
  private lags: number[] = [];
  private startedAt = Date.now();
  private timer: NodeJS.Timeout | null = null;

  constructor(private sink: Sink) {}

  note(kind: string, n = 1): void {
    this.counters[kind] = (this.counters[kind] ?? 0) + n;
  }

  onSlot(slot: number): void {
    const now = Date.now();
    if (this.lastSlot > 0 && slot > this.lastSlot + 1) {
      // Trou détecté (approximatif en processed : les forks peuvent sauter des
      // slots légitimement) — enregistré pour réconciliation RPC en phase 2.
      this.sink.push("capture_gaps", {
        from_slot: this.lastSlot + 1,
        to_slot: slot - 1,
        detected_at: chNow(now),
        reason: "slot_jump",
      });
      this.note("gaps");
    }
    if (slot > this.lastSlot) this.lastSlot = slot;
    this.slotSeenAt.set(slot, now);
    if (this.slotSeenAt.size > 1024) {
      const oldest = slot - 1024;
      for (const s of this.slotSeenAt.keys()) {
        if (s < oldest) this.slotSeenAt.delete(s);
      }
    }
  }

  onTransactionSlot(slot: number): void {
    const seen = this.slotSeenAt.get(slot);
    if (seen !== undefined) {
      this.lags.push(Math.max(0, Date.now() - seen));
      if (this.lags.length > 50_000) this.lags.splice(0, this.lags.length - 50_000);
    }
  }

  currentSlot(): number {
    return this.lastSlot;
  }

  startReporting(intervalMs = 30_000): void {
    let last = { ...this.counters, at: Date.now() };
    this.timer = setInterval(() => {
      const now = Date.now();
      const dt = (now - last.at) / 1000;
      const rate = (k: string) =>
        (((this.counters[k] ?? 0) - (Number(last[k as keyof typeof last]) || 0)) / dt).toFixed(1);
      const sorted = [...this.lags].sort((a, b) => a - b);
      const q = (p: number) => (sorted.length ? sorted[Math.floor(p * (sorted.length - 1))] : 0);
      console.log(
        JSON.stringify({
          t: new Date(now).toISOString(),
          uptime_s: Math.round((now - this.startedAt) / 1000),
          slot: this.lastSlot,
          tx_per_s: rate("tx"),
          trades_per_s: rate("trade"),
          creates_per_s: rate("create"),
          completes_total: this.counters.complete ?? 0,
          failed_per_s: rate("failed"),
          // Transactions qui référencent le compte du programme sans l'invoquer :
          // le filtre gRPC ne sait pas les exclure, ce n'est pas un défaut.
          foreign_per_s: rate("foreign"),
          transfers_per_s: rate("transfer"),
          pumpswap_per_s: rate("pumpswap"),
          gaps_total: this.counters.gaps ?? 0,
          reconnects_total: this.counters.reconnect ?? 0,
          decode_miss_total: this.counters.decode_miss ?? 0,
          lag_ms_p50: q(0.5),
          lag_ms_p99: q(0.99),
          sink_buffered: this.sink.bufferedRows(),
          sink_dropped: this.sink.dropped,
          sink_insert_errors: this.sink.insertErrors,
        }),
      );
      this.lags = [];
      last = { ...this.counters, at: now };
    }, intervalMs);
  }

  stopReporting(): void {
    if (this.timer) clearInterval(this.timer);
  }
}
