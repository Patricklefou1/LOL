import { createClient, ClickHouseClient } from "@clickhouse/client";

export interface SinkConfig {
  url: string;
  username: string;
  password: string;
  database: string;
}

// Écriture par lots : tampon par table, flush toutes les secondes ou à 5 000 lignes.
// En cas d'échec d'insertion, les lignes restent en tampon (plafonné : au-delà,
// les plus anciennes sont abandonnées et comptées dans `dropped` — perte visible,
// jamais silencieuse).
export class Sink {
  private client: ClickHouseClient;
  private buffers = new Map<string, Record<string, unknown>[]>();
  private timer: NodeJS.Timeout;
  private flushing = false;
  dropped = 0;
  insertErrors = 0;

  constructor(
    cfg: SinkConfig,
    private flushIntervalMs = 1000,
    private flushSize = 5000,
    private maxBufferPerTable = 100_000,
  ) {
    this.client = createClient({
      url: cfg.url,
      username: cfg.username,
      password: cfg.password,
      database: cfg.database,
      clickhouse_settings: {
        date_time_input_format: "best_effort",
      },
    });
    this.timer = setInterval(() => {
      void this.flushAll();
    }, this.flushIntervalMs);
  }

  push(table: string, row: Record<string, unknown>): void {
    let buf = this.buffers.get(table);
    if (!buf) {
      buf = [];
      this.buffers.set(table, buf);
    }
    if (buf.length >= this.maxBufferPerTable) {
      buf.shift();
      this.dropped++;
    }
    buf.push(row);
    if (buf.length >= this.flushSize) {
      void this.flushAll();
    }
  }

  bufferedRows(): number {
    let n = 0;
    for (const buf of this.buffers.values()) n += buf.length;
    return n;
  }

  async flushAll(): Promise<void> {
    if (this.flushing) return;
    this.flushing = true;
    try {
      for (const [table, buf] of this.buffers) {
        if (buf.length === 0) continue;
        const rows = buf.splice(0, buf.length);
        try {
          await this.client.insert({
            table,
            values: rows,
            format: "JSONEachRow",
          });
        } catch (err) {
          this.insertErrors++;
          // remise en tête de tampon pour retenter au prochain tick
          buf.unshift(...rows.slice(Math.max(0, rows.length - this.maxBufferPerTable)));
          console.error(
            `[sink] échec insertion ${table} (${rows.length} lignes), retenté au prochain flush :`,
            err instanceof Error ? err.message : err,
          );
        }
      }
    } finally {
      this.flushing = false;
    }
  }

  async close(): Promise<void> {
    clearInterval(this.timer);
    await this.flushAll();
    await this.client.close();
  }
}
