import { readFileSync } from "fs";
import { join } from "path";
import { createClient } from "@clickhouse/client";
import { config } from "./config";

// Applique sql/001_schema.sql (idempotent : CREATE ... IF NOT EXISTS partout).
// La connexion se fait sans base par défaut pour pouvoir créer la base elle-même.
async function migrate(): Promise<void> {
  const client = createClient({
    url: config.clickhouse.url,
    username: config.clickhouse.username,
    password: config.clickhouse.password,
  });

  const sql = readFileSync(join(__dirname, "..", "sql", "001_schema.sql"), "utf8").replaceAll(
    "__DB__",
    config.clickhouse.database,
  );

  const statements = sql
    .split(";")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);

  for (const statement of statements) {
    await client.command({ query: statement });
  }
  await client.close();
  console.log(
    `[migrate] ${statements.length} instructions appliquées sur ${config.clickhouse.url} (base ${config.clickhouse.database})`,
  );
}

migrate().catch((err) => {
  console.error("[migrate] échec :", err);
  process.exit(1);
});
