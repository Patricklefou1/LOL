import Client, { CommitmentLevel } from "@triton-one/yellowstone-grpc";
import { config } from "../config";
import { PUMP_PROGRAM_ID } from "../decode/pumpfun";
import { PUMPSWAP_PROGRAM_ID } from "../decode/pumpswap";
import { sleep } from "../util";

const arrayFilter = (a: string[]): string[] => a.filter((x) => x !== "");

export interface SubscriberCallbacks {
  onTransaction(update: any): void;
  onSlot(slot: number, status: number): void;
  onConnected(): void;
  onDisconnected(err: unknown): void;
}

function commitmentFromString(s: string): CommitmentLevel {
  switch (s) {
    case "confirmed":
      return CommitmentLevel.CONFIRMED;
    case "finalized":
      return CommitmentLevel.FINALIZED;
    default:
      return CommitmentLevel.PROCESSED;
  }
}

function emptyRequest(commitment: CommitmentLevel): any {
  return {
    accounts: {},
    slots: {},
    transactions: {},
    transactionsStatus: {},
    blocks: {},
    blocksMeta: {},
    entry: {},
    accountsDataSlice: [],
    commitment,
  };
}

export class PumpSubscriber {
  private stopped = false;
  private commitment: CommitmentLevel;

  constructor(
    private endpoint: string,
    private xToken: string | undefined,
    commitment: string,
    private cb: SubscriberCallbacks,
  ) {
    this.commitment = commitmentFromString(commitment);
  }

  stop(): void {
    this.stopped = true;
  }

  // Boucle de connexion : reconnexion avec backoff exponentiel, jamais d'abandon.
  async start(): Promise<void> {
    let backoffMs = 1000;
    while (!this.stopped) {
      const connectedAt = Date.now();
      try {
        await this.runOnce();
      } catch (err) {
        this.cb.onDisconnected(err);
      }
      if (this.stopped) break;
      // une connexion qui a tenu > 60 s réarme le backoff
      if (Date.now() - connectedAt > 60_000) backoffMs = 1000;
      await sleep(backoffMs);
      backoffMs = Math.min(backoffMs * 2, 30_000);
    }
  }

  private async runOnce(): Promise<void> {
    const client = new Client(this.endpoint, this.xToken, {
      "grpc.max_receive_message_length": 64 * 1024 * 1024,
    });
    const stream = await client.subscribe();

    const request = {
      ...emptyRequest(this.commitment),
      slots: { capture: { filterByCommitment: true } },
      transactions: {
        pump: {
          vote: false,
          // `undefined` = pas de filtre : on prend aussi les transactions
          // échouées. Leur taux et leur coût sont une entrée du modèle de coûts
          // (courses de slippage perdues), invisible si on les jette ici.
          failed: config.captureFailed ? undefined : false,
          // Bonding curve + AMM de destination : sans PumpSwap, tout ce qui
          // arrive à un token après sa graduation est invisible.
          accountInclude: arrayFilter([
            config.capturePumpfun ? PUMP_PROGRAM_ID : "",
            config.capturePumpswap ? PUMPSWAP_PROGRAM_ID : "",
          ]),
          accountExclude: [],
          accountRequired: [],
        },
      },
    };

    await new Promise<void>((resolve, reject) => {
      stream.write(request, (err: unknown) => (err ? reject(err) : resolve()));
    });
    this.cb.onConnected();

    // Ping périodique côté client : maintient la connexion ouverte à travers
    // les proxys/load-balancers ; le serveur répond par un pong.
    const pingTimer = setInterval(() => {
      try {
        stream.write({ ...emptyRequest(this.commitment), ping: { id: 1 } });
      } catch {
        // le stream mourant sera détecté par 'error'/'end'
      }
    }, 10_000);

    try {
      await new Promise<void>((_resolve, reject) => {
        stream.on("data", (update: any) => {
          if (this.stopped) return;
          if (update.transaction) {
            this.cb.onTransaction(update);
          } else if (update.slot) {
            this.cb.onSlot(Number(update.slot.slot), Number(update.slot.status ?? -1));
          } else if (update.ping) {
            try {
              stream.write({ ...emptyRequest(this.commitment), ping: { id: 1 } });
            } catch {
              // idem : la mort du stream est gérée par les événements du stream
            }
          }
        });
        stream.on("error", reject);
        stream.on("end", () => reject(new Error("stream terminé par le serveur")));
        stream.on("close", () => reject(new Error("stream fermé")));
      });
    } finally {
      clearInterval(pingTimer);
      try {
        stream.end();
      } catch {
        // déjà fermé
      }
    }
  }
}
