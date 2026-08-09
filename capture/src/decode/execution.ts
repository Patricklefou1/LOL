import { PUMP_PROGRAM_ID } from "./pumpfun";
import { parseLogInstructions, resolveAccountKeys } from "./accounts";

const SYSTEM_PROGRAM_ID = "11111111111111111111111111111111";
const COMPUTE_BUDGET_ID = "ComputeBudget111111111111111111111111111111";

// Comptes de pourboire Jito (constantes publiques du réseau). Un transfert vers
// l'un d'eux est un coût d'exécution, pas un flux économique entre acteurs :
// on le marque pour ne pas polluer le graphe de financement.
const JITO_TIP_ACCOUNTS = new Set([
  "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
  "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
  "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
  "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
  "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
  "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
  "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
  "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
]);

// Budget de calcul par défaut quand la transaction ne le déclare pas :
// 200 000 CU par instruction de premier niveau, plafonné à 1,4 M.
const DEFAULT_CU_PER_IX = 200_000;
const MAX_CU_LIMIT = 1_400_000;

export interface SolTransfer {
  ixIndex: number;
  from: string;
  to: string;
  lamports: bigint;
  kind: "transfer" | "create_account";
  isJitoTip: boolean;
}

export interface Execution {
  feePayer: string;
  feeLamports: bigint;
  computeUnits: number;
  cuLimit: number;
  cuPriceMicro: bigint;
  priorityFeeLamports: bigint;
  jitoTipLamports: bigint;
  invokedPump: boolean;
  pumpInstructions: string[];
  nInstructions: number;
  err: string;
  errRaw: string;
  failedProgram: string;
  transfers: SolTransfer[];
}

interface FlatInstruction {
  programIdIndex: number;
  accounts: number[];
  data: Buffer;
  topLevel: boolean;
}

function toIndices(v: unknown): number[] {
  if (!v) return [];
  if (v instanceof Uint8Array || Buffer.isBuffer(v)) return Array.from(v as Uint8Array);
  if (Array.isArray(v)) return v.map(Number);
  return [];
}

// Instructions de premier niveau puis instructions internes (CPI), à plat.
function flattenInstructions(info: any): FlatInstruction[] {
  const out: FlatInstruction[] = [];

  for (const ix of info?.transaction?.message?.instructions ?? []) {
    out.push({
      programIdIndex: Number(ix.programIdIndex),
      accounts: toIndices(ix.accounts),
      data: Buffer.from(ix.data ?? []),
      topLevel: true,
    });
  }
  for (const inner of info?.meta?.innerInstructions ?? []) {
    for (const ix of inner.instructions ?? []) {
      out.push({
        programIdIndex: Number(ix.programIdIndex),
        accounts: toIndices(ix.accounts),
        data: Buffer.from(ix.data ?? []),
        topLevel: false,
      });
    }
  }
  return out;
}

// `meta.err` est un TransactionError sérialisé en bincode : variante sur u32 LE,
// puis charge utile. La variante 8 (InstructionError) porte l'index d'instruction
// sur u8 puis une InstructionError, dont la variante 25 (Custom) porte le code
// d'erreur du programme sur u32 LE — c'est celle qui nous intéresse (slippage,
// garde de bot…). Les octets bruts sont conservés à côté : si cette table de
// variantes bouge côté Solana, l'historique reste re-décodable.
const TX_ERRORS = [
  "AccountInUse", "AccountLoadedTwice", "AccountNotFound", "ProgramAccountNotFound",
  "InsufficientFundsForFee", "InvalidAccountForFee", "AlreadyProcessed", "BlockhashNotFound",
  "InstructionError", "CallChainTooDeep", "MissingSignatureForFee", "InvalidAccountIndex",
  "SignatureFailure", "InvalidProgramForExecution", "SanitizeFailure", "ClusterMaintenance",
  "ResourceExhausted", "UnbalancedTransaction",
];

const IX_ERRORS = [
  "GenericError", "InvalidArgument", "InvalidInstructionData", "InvalidAccountData",
  "AccountDataTooSmall", "InsufficientFunds", "IncorrectProgramId", "MissingRequiredSignature",
  "AccountAlreadyInitialized", "UninitializedAccount", "UnbalancedInstruction",
  "ModifiedProgramId", "ExternalAccountLamportSpend", "ExternalAccountDataModified",
  "ReadonlyLamportChange", "ReadonlyDataModified", "DuplicateAccountIndex", "ExecutableModified",
  "RentEpochModified", "NotEnoughAccountKeys", "AccountDataSizeChanged", "AccountNotExecutable",
  "AccountBorrowFailed", "AccountBorrowOutstanding", "DuplicateAccountOutOfSync", "Custom",
];

function decodeTxError(err: unknown): { label: string; raw: string } {
  if (!err) return { label: "", raw: "" };

  const payload = (err as { err?: unknown }).err ?? err;
  let buf: Buffer;
  if (Buffer.isBuffer(payload) || payload instanceof Uint8Array) {
    buf = Buffer.from(payload as Uint8Array);
  } else if (typeof payload === "string") {
    buf = Buffer.from(payload, "base64");
  } else {
    return { label: "err", raw: "" };
  }

  const raw = buf.toString("base64");
  if (buf.length < 4) return { label: "err", raw };

  const variant = buf.readUInt32LE(0);
  const name = TX_ERRORS[variant] ?? `tx_error_${variant}`;

  if (variant === 8 && buf.length >= 9) {
    const inner = buf.readUInt32LE(5);
    if (inner === 25 && buf.length >= 13) {
      return { label: `custom:${buf.readUInt32LE(9)}`, raw };
    }
    return { label: IX_ERRORS[inner] ?? `ix_error_${inner}`, raw };
  }
  return { label: name, raw };
}

// Le programme qui a effectivement échoué : c'est lui qu'il faut incriminer, pas
// Pump.fun, quand un bot tiers rate sa propre garde dans une tx qui le référence.
function failedProgram(logs: string[]): string {
  for (let i = logs.length - 1; i >= 0; i--) {
    const m = /^Program (\S+) failed:/.exec(String(logs[i]));
    if (m) return m[1];
  }
  return "";
}

// Extrait le contexte d'exécution d'une transaction : ce que ça a coûté, à qui,
// et quels SOL ont bougé. C'est la matière première du modèle de coûts (§ 6.1 de
// la méthode) et du graphe de financement (empreintes de devs, clusters).
export function extractExecution(info: any): Execution {
  const meta = info?.meta;
  const keys = resolveAccountKeys(info);
  const instructions = flattenInstructions(info);

  const key = (i: number): string => keys[i] ?? "";

  let cuLimit = 0;
  let cuPriceMicro = 0n;
  let jitoTipLamports = 0n;
  let invokedPump = false;
  const transfers: SolTransfer[] = [];

  instructions.forEach((ix, i) => {
    const program = key(ix.programIdIndex);

    if (program === PUMP_PROGRAM_ID) {
      invokedPump = true;
      return;
    }

    if (program === COMPUTE_BUDGET_ID && ix.data.length >= 1) {
      const kind = ix.data.readUInt8(0);
      if (kind === 2 && ix.data.length >= 5) {
        cuLimit = ix.data.readUInt32LE(1);
      } else if (kind === 3 && ix.data.length >= 9) {
        cuPriceMicro = ix.data.readBigUInt64LE(1);
      }
      return;
    }

    if (program === SYSTEM_PROGRAM_ID && ix.data.length >= 12) {
      const kind = ix.data.readUInt32LE(0);
      // 0 = CreateAccount, 2 = Transfer : les deux déplacent des lamports.
      if (kind !== 0 && kind !== 2) return;
      const from = key(ix.accounts[0] ?? -1);
      const to = key(ix.accounts[1] ?? -1);
      if (!from || !to) return;

      const lamports = ix.data.readBigUInt64LE(4);
      if (lamports === 0n) return;

      const isJitoTip = JITO_TIP_ACCOUNTS.has(to);
      if (isJitoTip) jitoTipLamports += lamports;

      transfers.push({
        ixIndex: i,
        from,
        to,
        lamports,
        kind: kind === 0 ? "create_account" : "transfer",
        isJitoTip,
      });
    }
  });

  const logs: string[] = meta?.logMessages ?? [];
  const pumpInstructions = parseLogInstructions(logs)
    .filter((l) => l.program === PUMP_PROGRAM_ID)
    .map((l) => l.name);
  if (pumpInstructions.length > 0) invokedPump = true;

  const error = decodeTxError(meta?.err);
  const topLevelCount = instructions.filter((ix) => ix.topLevel).length;
  const effectiveLimit =
    cuLimit > 0 ? cuLimit : Math.min(topLevelCount * DEFAULT_CU_PER_IX, MAX_CU_LIMIT);
  // Le priority fee facturé porte sur le budget *demandé*, pas sur le consommé.
  const priorityFeeLamports =
    cuPriceMicro > 0n ? (cuPriceMicro * BigInt(effectiveLimit) + 999_999n) / 1_000_000n : 0n;

  return {
    feePayer: key(0),
    feeLamports: BigInt(meta?.fee ?? 0),
    computeUnits: Number(meta?.computeUnitsConsumed ?? 0),
    cuLimit,
    cuPriceMicro,
    priorityFeeLamports,
    jitoTipLamports,
    invokedPump,
    pumpInstructions,
    nInstructions: topLevelCount,
    err: error.label,
    errRaw: error.raw,
    failedProgram: error.label ? failedProgram(logs) : "",
    transfers,
  };
}
