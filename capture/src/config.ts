import "dotenv/config";

function env(name: string, fallback?: string): string {
  const v = process.env[name] ?? fallback;
  if (v === undefined) {
    throw new Error(`Variable d'environnement manquante : ${name} (voir .env.example)`);
  }
  return v;
}

export const config = {
  grpc: {
    endpoint: () => env("GRPC_ENDPOINT"),
    xToken: () => process.env.GRPC_X_TOKEN,
    commitment: () => (process.env.COMMITMENT ?? "processed").toLowerCase(),
  },
  clickhouse: {
    url: env("CLICKHOUSE_URL", "http://localhost:8123"),
    username: env("CLICKHOUSE_USER", "default"),
    password: process.env.CLICKHOUSE_PASSWORD ?? "",
    database: env("CLICKHOUSE_DATABASE", "pumpfun"),
  },
  captureRaw: (process.env.CAPTURE_RAW ?? "1") !== "0",
  // Les transactions échouées comptent pour le modèle de coûts, mais n'ont aucun
  // événement à re-décoder : on les mesure sans payer leur archive brute.
  captureFailed: (process.env.CAPTURE_FAILED ?? "1") !== "0",
  captureRawFailed: (process.env.CAPTURE_RAW_FAILED ?? "0") !== "0",
  captureExecution: (process.env.CAPTURE_EXECUTION ?? "1") !== "0",
  captureCostsForeign: (process.env.CAPTURE_COSTS_FOREIGN ?? "0") !== "0",
};
