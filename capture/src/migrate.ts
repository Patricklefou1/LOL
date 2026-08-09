import { readFileSync, readdirSync } from "fs";
import { join } from "path";
import { createClient } from "@clickhouse/client";
import { config } from "./config";

// Découpe un fichier SQL en instructions. Un `;` ne coupe que s'il est du vrai SQL :
// ni dans un commentaire `--`, ni dans une chaîne. Les commentaires sont retirés au passage.
function splitStatements(sql: string): string[] {
  const statements: string[] = [];
  let current = "";
  let inString = false;

  for (let i = 0; i < sql.length; i++) {
    const c = sql[i];

    if (inString) {
      current += c;
      if (c === "\\") current += sql[++i] ?? "";
      else if (c === "'") inString = false;
      continue;
    }
    if (c === "'") {
      inString = true;
      current += c;
    } else if (c === "-" && sql[i + 1] === "-") {
      const nl = sql.indexOf("\n", i);
      i = nl === -1 ? sql.length : nl;
      current += "\n";
    } else if (c === ";") {
      statements.push(current);
      current = "";
    } else {
      current += c;
    }
  }
  statements.push(current);

  return statements.map((s) => s.trim()).filter((s) => s.length > 0);
}

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
    const statements = splitStatements(sql);
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
