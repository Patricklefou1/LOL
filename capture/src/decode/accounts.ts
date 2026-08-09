import bs58 from "bs58";

// Clés de comptes résolues dans l'ordre exact où les `programIdIndex` des
// instructions les référencent : statiques d'abord, puis celles chargées par
// address lookup table (writable avant readonly).
export function resolveAccountKeys(info: any): string[] {
  const msg = info?.transaction?.message;
  const meta = info?.meta;
  return [
    ...(msg?.accountKeys ?? []),
    ...(meta?.loadedWritableAddresses ?? []),
    ...(meta?.loadedReadonlyAddresses ?? []),
  ].map((k: Uint8Array) => bs58.encode(Buffer.from(k)));
}

export interface LoggedInstruction {
  program: string;
  name: string;
}

// Rejoue la pile d'invocations pour attribuer chaque "Instruction: X" au
// programme réellement en haut de pile. Un simple "dernier invoke vu" se
// trompe dès qu'un programme en appelle un autre puis reprend la main.
export function parseLogInstructions(logs: string[]): LoggedInstruction[] {
  const stack: string[] = [];
  const out: LoggedInstruction[] = [];

  for (const line of logs) {
    if (typeof line !== "string") continue;

    const invoke = /^Program (\S+) invoke \[\d+\]$/.exec(line);
    if (invoke) {
      stack.push(invoke[1]);
      continue;
    }
    if (/^Program \S+ (?:success|failed)/.test(line)) {
      stack.pop();
      continue;
    }
    const ix = /^Program log: Instruction: (.+)$/.exec(line);
    if (ix && stack.length > 0) {
      out.push({ program: stack[stack.length - 1], name: ix[1].trim() });
    }
  }
  return out;
}
