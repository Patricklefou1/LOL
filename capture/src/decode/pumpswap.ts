import { createHash } from "crypto";
import { resolveAccountKeys } from "./accounts";

// PumpSwap : l'AMM où migrent les tokens qui graduent. Toute l'activité
// post-graduation s'y déroule — invisible pour la capture de la bonding curve.
export const PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA";

const EVENT_CPI_TAG = Buffer.from("e445a52e51cb9a1d", "hex");

function eventDiscriminator(name: string): string {
  return createHash("sha256").update(`event:${name}`).digest().subarray(0, 8).toString("hex");
}

// Nom d'événement par discriminator. Les inconnus sont archivés tels quels sous
// leur discriminator brut : on ne jette jamais un événement qu'on ne sait pas
// encore nommer.
const NOMS: Record<string, string> = Object.fromEntries(
  [
    "BuyEvent",
    "SellEvent",
    "CreatePoolEvent",
    "DepositEvent",
    "WithdrawEvent",
    "CollectCoinCreatorFeeEvent",
    "SyncUserVolumeAccumulatorEvent",
  ].map((n) => [eventDiscriminator(n), n]),
);

export interface RawEvent {
  name: string;
  discriminator: string;
  payload: Buffer;
}

// Extrait les charges utiles brutes des event-CPI d'un programme donné, sans
// tenter de les interpréter. Le décodeur des champs viendra ensuite et rejouera
// l'historique : les structures Buy et Sell diffèrent et méritent d'être
// rétro-conçues sur un échantillon large, pas devinées à la volée.
export function extractRawEvents(info: any, programId: string): RawEvent[] {
  const keys = resolveAccountKeys(info);
  const out: RawEvent[] = [];

  for (const inner of info?.meta?.innerInstructions ?? []) {
    for (const ix of inner.instructions ?? []) {
      if (keys[Number(ix.programIdIndex)] !== programId) continue;
      const data = Buffer.from(ix.data ?? []);
      if (data.length < 16 || !data.subarray(0, 8).equals(EVENT_CPI_TAG)) continue;

      const disc = data.subarray(8, 16).toString("hex");
      out.push({
        name: NOMS[disc] ?? "",
        discriminator: disc,
        payload: data.subarray(16),
      });
    }
  }
  return out;
}
