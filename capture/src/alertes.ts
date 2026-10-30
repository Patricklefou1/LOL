import { ClickHouseClient } from "@clickhouse/client";
import { Annonce } from "./annonces";
import { evenementsSql, SOURCES } from "./listings";

// Alertes Telegram immédiates, en complément du mail du matin : chaque annonce
// de listing nouvelle, et chaque événement de rang 1 des 12 dernières heures,
// une seule fois.
//
// .env : TELEGRAM_BOT_TOKEN (créé avec @BotFather) et TELEGRAM_CHAT_ID. Sans
// eux, rien n'est envoyé ni marqué : la configuration ultérieure n'alertera que
// les 12 dernières heures.

function configure(): { token: string; chat: string } | null {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  const chat = process.env.TELEGRAM_CHAT_ID;
  return token && chat ? { token, chat } : null;
}

export async function envoyerTelegram(texte: string): Promise<void> {
  const cfg = configure();
  if (!cfg) return;
  const reponse = await fetch(`https://api.telegram.org/bot${cfg.token}/sendMessage`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: cfg.chat, text: texte, disable_web_page_preview: true }),
    signal: AbortSignal.timeout(20_000),
  });
  // Le jeton n'apparaît jamais dans l'erreur : seule la réponse de Telegram
  if (!reponse.ok) throw new Error(`Telegram HTTP ${reponse.status} : ${(await reponse.text()).slice(0, 200)}`);
}

async function dejaEnvoyees(ch: ClickHouseClient, cles: string[]): Promise<Set<string>> {
  if (cles.length === 0) return new Set();
  const lignes = await (
    await ch.query({
      query: "SELECT cle FROM alertes_envoyees WHERE cle IN {cles:Array(String)}",
      query_params: { cles },
      format: "JSONEachRow",
    })
  ).json<{ cle: string }>();
  return new Set(lignes.map((l) => l.cle));
}

const LIBELLES: Record<string, string> = {
  lancement: "Lancement",
  "premier perp": "Premier perp",
  "sortie pré-marché": "Sortie de pré-marché",
};

export async function alerter(ch: ClickHouseClient, annonces: Annonce[]): Promise<void> {
  if (!configure()) return;

  const rang1 = (marche: string) =>
    SOURCES.filter((s) => s.rang === 1 && s.marche === marche)
      .map((s) => `'${s.bourse}'`)
      .join(",");
  const evenements = await (
    await ch.query({
      query: `SELECT evenement, base, toString(le) AS quand, par_perp, premarche, bourses_spot, bourses_perp
              FROM (${evenementsSql("now() + INTERVAL 1 DAY")})
              WHERE le >= now() - INTERVAL 12 HOUR
                AND (hasAny(bourses_spot, [${rang1("spot")}]) OR hasAny(bourses_perp, [${rang1("perp")}]))`,
      query_params: { jours: 1 },
      format: "JSONEachRow",
    })
  ).json<{
    evenement: string;
    base: string;
    quand: string;
    par_perp: number;
    premarche: number;
    bourses_spot: string[];
    bourses_perp: string[];
  }>();

  const messages: { cle: string; texte: string }[] = [
    ...annonces.map((a) => ({
      cle: `annonce|${a.bourse}|${a.id}`,
      texte: `📣 Annonce ${a.bourse} : ${a.titre}\n${a.url}`,
    })),
    ...evenements.map((e) => ({
      cle: `${e.evenement}|${e.base}`,
      texte:
        `🚀 ${LIBELLES[e.evenement] ?? e.evenement} : ${e.base}` +
        (Number(e.premarche) && e.evenement !== "sortie pré-marché" ? " (pré-marché)" : "") +
        `\n${e.quand.slice(0, 16)} UTC` +
        `\nspot : ${e.bourses_spot.join(", ") || "—"}\nperp : ${e.bourses_perp.join(", ") || "—"}`,
    })),
  ];

  const envoyees = await dejaEnvoyees(
    ch,
    messages.map((m) => m.cle),
  );
  for (const m of messages) {
    if (envoyees.has(m.cle)) continue;
    try {
      await envoyerTelegram(m.texte);
      await ch.insert({ table: "alertes_envoyees", values: [{ cle: m.cle }], format: "JSONEachRow" });
    } catch (err) {
      // Non marquée : elle sera retentée au relevé suivant
      console.error(`[listings] alerte ${m.cle} : ${err}`);
    }
  }
}

export async function essaiTelegram(): Promise<void> {
  if (!configure()) {
    console.log("telegram       TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID absent de .env");
    return;
  }
  try {
    await envoyerTelegram("✅ Relevé des listings : test de l'alerte Telegram");
    console.log("telegram       message de test envoyé");
  } catch (err) {
    console.log(`telegram       ÉCHEC : ${err}`);
  }
}
