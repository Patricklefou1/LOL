import bs58 from "bs58";
import { config } from "./config";
import { extractExecution } from "./decode/execution";
import { decodePumpEvents, priceSol } from "./decode/pumpfun";
import { PUMPSWAP_PROGRAM_ID, extractRawEvents } from "./decode/pumpswap";
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

        if (isFailed) health.note("failed");

        const exec = config.captureExecution ? extractExecution(info) : null;

        // PumpSwap : on archive la charge utile brute des événements sans les
        // interpréter. Les structures Buy et Sell diffèrent et seront
        // rétro-conçues sur un échantillon large, puis rejouées depuis ici.
        if (config.capturePumpswap && !isFailed) {
          for (const ev of extractRawEvents(info, PUMPSWAP_PROGRAM_ID)) {
            health.note("pumpswap");
            sink.push("pumpswap_events", {
              slot,
              signature,
              received_at: receivedAt,
              event_name: ev.name,
              discriminator: ev.discriminator,
              payload: ev.payload.toString("base64"),
            });
          }
        }

        // L'archive brute n'existe que pour re-décoder plus tard. Deux familles
        // n'ont rien à re-décoder et pèsent pour un quart du poste disque n°1 :
        // les transactions échouées (aucun événement émis) et celles qui se
        // contentent de référencer le compte du programme sans l'invoquer.
        const rejouable = (!isFailed || config.captureRawFailed) && (exec === null || exec.invokedPump);
        if (config.captureRaw && rejouable) {
          sink.push("raw_transactions", {
            slot,
            signature,
            received_at: receivedAt,
            is_failed: isFailed,
            payload: JSON.stringify(normalizeForJson(info)),
          });
        }

        let decoded = 0;
        let mint = "";
        for (const ev of decodePumpEvents(info)) {
          decoded++;
          if (!mint) mint = ev.mint;
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
          } else if (ev.kind === "complete") {
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
          } else {
            // événement auxiliaire reconnu (frais créateur, extension de compte,
            // migration…) : compté pour le monitoring, contenu dans raw_transactions
            health.note("other_event");
          }
        }
        if (exec) {
          // `decode_miss` ne compte que les transactions qui invoquent vraiment
          // le programme : les autres n'ont, par construction, rien à décoder.
          if (decoded === 0 && !isFailed && exec.invokedPump) health.note("decode_miss");
          if (!exec.invokedPump) health.note("foreign");

          // Le trafic étranger est mesuré (foreign_per_s) mais pas stocké : il ne
          // dit rien de nos coûts et pèse un tiers du flux.
          if (exec.invokedPump || config.captureCostsForeign) {
          sink.push("tx_costs", {
            slot,
            signature,
            received_at: receivedAt,
            is_failed: isFailed,
            err: exec.err,
            err_raw: exec.errRaw,
            failed_program: exec.failedProgram,
            fee_payer: exec.feePayer,
            fee_lamports: jsonU64(exec.feeLamports),
            compute_units: exec.computeUnits,
            cu_limit: exec.cuLimit,
            cu_price_micro: jsonU64(exec.cuPriceMicro),
            priority_fee_lamports: jsonU64(exec.priorityFeeLamports),
            jito_tip_lamports: jsonU64(exec.jitoTipLamports),
            invoked_pump: exec.invokedPump ? 1 : 0,
            pump_instructions: exec.pumpInstructions,
            mint,
            n_instructions: exec.nInstructions,
          });
          }

          // Les transferts d'une transaction échouée n'ont pas eu lieu : les
          // enregistrer inventerait des arêtes dans le graphe de financement.
          // Les frais, eux, sont bien payés — ils restent dans tx_costs.
          // Restreint à la bonding curve : le graphe de financement porte sur les
          // devs et les snipers, pas sur la plomberie de l'AMM post-graduation.
          if (!isFailed && exec.invokedPump) {
            for (const t of exec.transfers) {
              health.note("transfer");
              sink.push("sol_transfers", {
                slot,
                signature,
                received_at: receivedAt,
                ix_index: t.ixIndex,
                from_wallet: t.from,
                to_wallet: t.to,
                lamports: jsonU64(t.lamports),
                kind: t.kind,
                is_jito_tip: t.isJitoTip ? 1 : 0,
              });
            }
          }
        } else if (decoded === 0 && !isFailed) {
          // Transaction du programme sans événement décodé : compté, pas perdu —
          // la table raw permet de re-décoder après correction du décodeur.
          health.note("decode_miss");
        }
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
