import bs58 from "bs58";
import { config } from "./config";
import { decodePumpEvents, priceSol } from "./decode/pumpfun";
import { PumpSubscriber } from "./grpc/subscriber";
import { Health } from "./monitor/health";
import { Sink } from "./sink/clickhouse";
import { chNow, jsonU64, normalizeForJson } from "./util";

async function main(): Promise<void> {
  const sink = new Sink(config.clickhouse);
  const health = new Health(sink);

  const subscriber = new PumpSubscriber(
    config.grpc.endpoint(),
    config.grpc.xToken(),
    config.grpc.commitment(),
    {
      onConnected() {
        console.log(`[grpc] connecté à ${config.grpc.endpoint()} (${config.grpc.commitment()})`);
      },
      onDisconnected(err) {
        health.note("reconnect");
        console.error("[grpc] déconnecté :", err instanceof Error ? err.message : err);
      },
      onSlot(slot, status) {
        health.onSlot(slot);
        sink.push("slots", { slot, status, received_at: chNow() });
      },
      onTransaction(update) {
        const receivedAt = chNow();
        const slot = Number(update.transaction.slot);
        const info = update.transaction.transaction;
        if (!info) return;

        health.note("tx");
        health.onTransactionSlot(slot);

        const signature = bs58.encode(Buffer.from(info.signature ?? []));
        const isFailed = info.meta?.err ? 1 : 0;

        if (config.captureRaw) {
          sink.push("raw_transactions", {
            slot,
            signature,
            received_at: receivedAt,
            is_failed: isFailed,
            payload: JSON.stringify(normalizeForJson(info)),
          });
        }

        let decoded = 0;
        for (const ev of decodePumpEvents(info)) {
          decoded++;
          if (ev.kind === "trade") {
            health.note("trade");
            sink.push("trades", {
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
            });
          } else if (ev.kind === "create") {
            health.note("create");
            sink.push("creations", {
              slot,
              signature,
              received_at: receivedAt,
              mint: ev.mint,
              bonding_curve: ev.bondingCurve,
              user: ev.user,
              creator: ev.creator,
              name: ev.name,
              symbol: ev.symbol,
              uri: ev.uri,
            });
          } else {
            health.note("complete");
            sink.push("completions", {
              slot,
              signature,
              received_at: receivedAt,
              mint: ev.mint,
              user: ev.user,
              bonding_curve: ev.bondingCurve,
              event_timestamp: jsonU64(ev.timestamp),
            });
          }
        }
        // Transaction du programme sans événement décodé : compté, pas perdu —
        // la table raw permet de re-décoder après correction du décodeur.
        if (decoded === 0 && !isFailed) health.note("decode_miss");
      },
    },
  );

  health.startReporting();

  let shuttingDown = false;
  const shutdown = async (signal: string) => {
    if (shuttingDown) return;
    shuttingDown = true;
    console.log(`[main] ${signal} reçu, flush du tampon puis arrêt…`);
    subscriber.stop();
    health.stopReporting();
    await sink.close();
    process.exit(0);
  };
  process.on("SIGINT", () => void shutdown("SIGINT"));
  process.on("SIGTERM", () => void shutdown("SIGTERM"));

  await subscriber.start();
  await sink.close();
}

main().catch((err) => {
  console.error("[main] erreur fatale :", err);
  process.exit(1);
});
