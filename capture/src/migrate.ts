import { readFileSync, readdirSync } from "fs";
import { join } from "path";
import { createClient } from "@clickhouse/client";
import { config } from "./config";

// Applique tous les fichiers sql/*.sql dans l'ordre (idempotents : IF NOT EXISTS partout).
// La connexion se fait sans base par défaut pour pouvoir créer la base elle-même.
async function migrate(): Promise<void> {
  const client = createClient({
    url: config.clickhouse.url,
    username: config.clickhouse.username,
    password: config.clickhouse.password,
  });

  const sqlDir = join(__dirname, "..", "sql");
  const files = readdirSync(sqlDir)
    .filter((f) => f.endsWith(".sql"))
    .sort();

  let total = 0;
  for (const file of files) {
    const sql = readFileSync(join(sqlDir, file), "utf8").replaceAll("__DB__", config.clickhouse.database);
    const statements = sql
      .split(";")
      .map((s) => s.trim())
      .filter((s) => s.length > 0 && !s.startsWith("--"));
    for (const statement of statements) {
      await client.command({ query: statement });
      total++;
    }
    console.log(`[migrate] ${file} : ok`);
  }
  await client.close();
  console.log(
    `[migrate] ${total} instructions appliquées sur ${config.clickhouse.url} (base ${config.clickhouse.database})`,
  );
}

migrate().catch((err) => {
  console.error("[migrate] échec :", err);
  process.exit(1);
});
