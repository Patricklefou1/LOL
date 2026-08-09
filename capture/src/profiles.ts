import { createClient, ClickHouseClient } from "@clickhouse/client";
import { config } from "./config";
import { chNow } from "./util";

// Phase 3 — bases propriétaires : registre PnL par wallet, empreintes de devs,
// clusters de financement. Reconstruction complète à chaque exécution (ce sont
// des agrégats de toute l'histoire capturée, pas un flux incrémental).
//
// Les deux premières se calculent entièrement dans ClickHouse. La troisième
// demande un parcours de graphe (composantes connexes), que SQL ne fait pas :
// les arêtes sont ramenées côté Node et unies par union-find.

// Au-delà de ce nombre de contreparties distinctes, un wallet est traité comme
// de l'infrastructure (exchange, routeur, payeur de frais mutualisé) et retiré
// du graphe : un seul hub relierait sinon tout le réseau en une composante.
const DEFAULT_HUB_DEGREE = 200;

// Minimums d'exemption de loyer observés sur le flux : ces montants créent des
// comptes (ATA notamment), ils ne financent personne.
const RENT_LAMPORTS = [2074080, 2039280, 1844400];

function argValue(name: string): string | undefined {
  const pref = `--${name}`;
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === pref) return argv[i + 1];
    if (argv[i].startsWith(`${pref}=`)) return argv[i].slice(pref.length + 1);
  }
  return undefined;
}

async function rebuildWalletPnl(client: ClickHouseClient, db: string, now: string): Promise<void> {
  await client.command({ query: `TRUNCATE TABLE ${db}.wallet_pnl` });
  await client.command({
    query: `
      INSERT INTO ${db}.wallet_pnl
      WITH positions AS (
        SELECT
          user AS wallet,
          mint,
          sumIf(sol_amount, is_buy = 1) / 1e9   AS buy_sol,
          sumIf(sol_amount, is_buy = 0) / 1e9   AS sell_sol,
          sumIf(token_amount, is_buy = 1) / 1e6 AS buy_tok,
          sumIf(token_amount, is_buy = 0) / 1e6 AS sell_tok,
          min(received_at) AS first_at,
          max(received_at) AS last_at
        FROM ${db}.trades
        GROUP BY wallet, mint
      ),
      scored AS (
        SELECT
          *,
          buy_tok > 0 AND sell_tok >= buy_tok * 0.99 AS closed,
          if(buy_sol > 0, sell_sol / buy_sol, 0)     AS multiple
        FROM positions
      )
      SELECT
        wallet,
        toUInt32(count())                                            AS n_positions,
        toUInt32(countIf(closed))                                    AS n_closed,
        toUInt32(countIf(closed AND sell_sol > buy_sol))             AS n_win,
        toFloat32(if(countIf(closed) > 0,
                     countIf(closed AND sell_sol > buy_sol) / countIf(closed), 0)) AS win_rate,
        sum(buy_sol)                                                 AS buys_sol,
        sum(sell_sol)                                                AS sells_sol,
        sumIf(sell_sol - buy_sol, closed)                            AS realized_sol,
        sum(sell_sol) - sum(buy_sol)                                 AS net_sol,
        toFloat32(ifNotFinite(medianIf(multiple, closed), 0))        AS median_multiple,
        toDateTime(min(first_at))                                    AS first_seen,
        toDateTime(max(last_at))                                     AS last_seen,
        toDateTime({now:String})                                     AS computed_at
      FROM scored
      GROUP BY wallet`,
    query_params: { now },
  });
}

async function rebuildDevProfiles(client: ClickHouseClient, db: string, now: string): Promise<void> {
  await client.command({ query: `TRUNCATE TABLE ${db}.dev_profiles` });
  await client.command({
    query: `
      INSERT INTO ${db}.dev_profiles
      WITH tokens AS (
        SELECT
          if(creator != '', creator, user) AS dev,
          mint,
          min(received_at) AS created_at
        FROM ${db}.creations
        GROUP BY dev, mint
      ),
      dev_flows AS (
        -- Ce que le dev a lui-même acheté et vendu sur SES tokens.
        SELECT
          t.dev AS dev,
          t.mint AS mint,
          sumIf(tr.sol_amount, tr.is_buy = 1) / 1e9   AS dev_buy_sol,
          sumIf(tr.sol_amount, tr.is_buy = 0) / 1e9   AS dev_sell_sol,
          sumIf(tr.token_amount, tr.is_buy = 1) / 1e6 AS dev_buy_tok,
          sumIf(tr.token_amount, tr.is_buy = 0) / 1e6 AS dev_sell_tok,
          minIf(tr.received_at, tr.is_buy = 0)        AS first_sell_at
        FROM tokens t
        INNER JOIN ${db}.trades tr ON tr.mint = t.mint AND tr.user = t.dev
        GROUP BY dev, mint
      ),
      per_token AS (
        SELECT
          t.dev AS dev,
          t.mint AS mint,
          t.created_at AS created_at,
          coalesce(f.dev_buy_sol, 0)  AS dev_buy_sol,
          coalesce(f.dev_sell_sol, 0) AS dev_sell_sol,
          -- rug_dump : le dev a revendu ≥ 80 % de ses tokens, première vente < 24 h
          coalesce(f.dev_buy_tok, 0) > 0
            AND coalesce(f.dev_sell_tok, 0) >= coalesce(f.dev_buy_tok, 0) * 0.8
            AND f.first_sell_at > toDateTime64(0, 3)
            AND dateDiff('hour', t.created_at, f.first_sell_at) < 24 AS rug_dump,
          if(f.first_sell_at > toDateTime64(0, 3),
             toInt32(dateDiff('second', t.created_at, f.first_sell_at)), -1) AS sec_first_sell,
          mint IN (SELECT mint FROM ${db}.completions) AS graduated
        FROM tokens t
        LEFT JOIN dev_flows f ON f.dev = t.dev AND f.mint = t.mint
      ),
      gaps_agg AS (
        -- Intervalle médian entre deux lancements consécutifs du même dev.
        SELECT dev, median(gap_min) AS med_gap
        FROM (
          SELECT dev, dateDiff('minute', prev, created_at) AS gap_min
          FROM (
            SELECT dev, created_at,
                   lagInFrame(created_at) OVER (PARTITION BY dev ORDER BY created_at) AS prev
            FROM per_token
          )
          WHERE prev > toDateTime64(0, 3)
        )
        GROUP BY dev
      )
      SELECT
        p.dev                                              AS dev,
        toUInt32(count())                                  AS n_tokens,
        toUInt32(countIf(graduated))                       AS n_graduated,
        toFloat32(countIf(graduated) / count())            AS graduation_rate,
        toUInt32(countIf(rug_dump))                        AS n_rug_dump,
        toFloat32(countIf(rug_dump) / count())             AS rug_rate,
        sum(dev_buy_sol)                                   AS dev_buy_sol,
        sum(dev_sell_sol)                                  AS dev_sell_sol,
        -- medianIf sur un ensemble vide renvoie NaN, que coalesce ne rattrape pas.
        toInt32(ifNotFinite(medianIf(sec_first_sell, sec_first_sell >= 0), -1)) AS median_sec_first_sell,
        toUInt8(topK(1)(toHour(created_at))[1])            AS modal_launch_hour,
        toFloat32(ifNotFinite(any(g.med_gap), 0))          AS median_min_between,
        toDateTime(min(created_at))                        AS first_seen,
        toDateTime(max(created_at))                        AS last_seen,
        toDateTime({now:String})                           AS computed_at
      FROM per_token p
      LEFT JOIN gaps_agg g ON g.dev = p.dev
      GROUP BY p.dev`,
    query_params: { now },
  });
}

interface Edge {
  from: string;
  to: string;
}

// Union-find avec compression de chemin et union par rang.
class UnionFind {
  private parent = new Map<string, string>();
  private rank = new Map<string, number>();

  find(x: string): string {
    let root = this.parent.get(x);
    if (root === undefined) {
      this.parent.set(x, x);
      this.rank.set(x, 0);
      return x;
    }
    while (root !== x) {
      x = root;
      root = this.parent.get(x) as string;
    }
    return root;
  }

  union(a: string, b: string): void {
    const ra = this.find(a);
    const rb = this.find(b);
    if (ra === rb) return;
    const ka = this.rank.get(ra) ?? 0;
    const kb = this.rank.get(rb) ?? 0;
    if (ka < kb) this.parent.set(ra, rb);
    else if (ka > kb) this.parent.set(rb, ra);
    else {
      this.parent.set(rb, ra);
      this.rank.set(ra, ka + 1);
    }
  }

  members(): string[] {
    return [...this.parent.keys()];
  }
}

async function rebuildClusters(
  client: ClickHouseClient,
  db: string,
  now: string,
  hubDegree: number,
): Promise<void> {
  // Degré = nombre de contreparties distinctes, tous sens confondus.
  const degRs = await client.query({
    query: `
      SELECT wallet, uniqExact(peer) AS degree FROM (
        SELECT from_wallet AS wallet, to_wallet AS peer FROM ${db}.sol_transfers WHERE is_jito_tip = 0
        UNION ALL
        SELECT to_wallet AS wallet, from_wallet AS peer FROM ${db}.sol_transfers WHERE is_jito_tip = 0
      )
      GROUP BY wallet`,
    format: "JSONEachRow",
  });
  const degree = new Map<string, number>();
  for (const r of await degRs.json<{ wallet: string; degree: string }>()) {
    degree.set(r.wallet, Number(r.degree));
  }

  const hubs = new Set([...degree].filter(([, d]) => d > hubDegree).map(([w]) => w));

  // Une arête ne vaut que si elle dit "A a financé B" :
  //  - `create_account` et les montants d'exemption de loyer sont de la
  //    plomberie de compte (ATA, PDA), pas du financement ;
  //  - les deux extrémités doivent être des acteurs réels (un wallet qui a
  //    tradé ou créé un token), sinon on relie des comptes techniques que
  //    des milliers d'inconnus touchent en commun — c'est ce qui produisait
  //    une composante géante de 90 % des wallets.
  const edgeRs = await client.query({
    query: `
      WITH acteurs AS (
        SELECT user AS w FROM ${db}.trades
        UNION DISTINCT SELECT if(creator != '', creator, user) FROM ${db}.creations
      )
      SELECT DISTINCT from_wallet, to_wallet
      FROM ${db}.sol_transfers
      WHERE is_jito_tip = 0
        AND kind = 'transfer'
        AND from_wallet != to_wallet
        AND lamports NOT IN (${RENT_LAMPORTS.join(", ")})
        AND from_wallet IN (SELECT w FROM acteurs)
        AND to_wallet IN (SELECT w FROM acteurs)`,
    format: "JSONEachRow",
  });
  const edges = (await edgeRs.json<Edge & { from_wallet: string; to_wallet: string }>()).map(
    (r) => ({ from: r.from_wallet, to: r.to_wallet }),
  );

  const uf = new UnionFind();
  let kept = 0;
  for (const e of edges) {
    if (hubs.has(e.from) || hubs.has(e.to)) continue;
    uf.union(e.from, e.to);
    kept++;
  }

  // Le représentant affiché est le wallet vu en premier dans la composante.
  const firstSeenRs = await client.query({
    query: `
      SELECT wallet, min(received_at) AS t FROM (
        SELECT from_wallet AS wallet, received_at FROM ${db}.sol_transfers WHERE is_jito_tip = 0
        UNION ALL
        SELECT to_wallet AS wallet, received_at FROM ${db}.sol_transfers WHERE is_jito_tip = 0
      )
      GROUP BY wallet`,
    format: "JSONEachRow",
  });
  const firstSeen = new Map<string, string>();
  for (const r of await firstSeenRs.json<{ wallet: string; t: string }>()) {
    firstSeen.set(r.wallet, r.t);
  }

  const groups = new Map<string, string[]>();
  for (const w of uf.members()) {
    const root = uf.find(w);
    const g = groups.get(root);
    if (g) g.push(w);
    else groups.set(root, [w]);
  }

  const rows: Record<string, unknown>[] = [];
  for (const members of groups.values()) {
    if (members.length < 2) continue;
    const clusterId = members.reduce((a, b) =>
      (firstSeen.get(a) ?? "9") <= (firstSeen.get(b) ?? "9") ? a : b,
    );
    for (const w of members) {
      rows.push({
        wallet: w,
        cluster_id: clusterId,
        cluster_size: members.length,
        degree: degree.get(w) ?? 0,
        computed_at: now,
      });
    }
  }

  await client.command({ query: `TRUNCATE TABLE ${db}.wallet_clusters` });
  for (let i = 0; i < rows.length; i += 50_000) {
    await client.insert({
      table: `${db}.wallet_clusters`,
      values: rows.slice(i, i + 50_000),
      format: "JSONEachRow",
    });
  }
  console.log(
    `[profiles] clusters : ${groups.size} composantes, ${rows.length} wallets classés ` +
      `(${kept}/${edges.length} arêtes retenues, ${hubs.size} hubs écartés au-delà de ${hubDegree} contreparties)`,
  );
}

async function main(): Promise<void> {
  const hubDegree = Number(argValue("hub-degree") ?? DEFAULT_HUB_DEGREE);
  const db = config.clickhouse.database;
  const now = chNow().slice(0, 19);

  const client = createClient({
    url: config.clickhouse.url,
    username: config.clickhouse.username,
    password: config.clickhouse.password,
    database: db,
    request_timeout: 600_000,
  });

  console.log("[profiles] registre PnL par wallet…");
  await rebuildWalletPnl(client, db, now);

  console.log("[profiles] empreintes de devs…");
  await rebuildDevProfiles(client, db, now);

  console.log("[profiles] clusters de financement…");
  await rebuildClusters(client, db, now, hubDegree);

  console.log("[profiles] terminé");
  await client.close();
}

if (require.main === module) {
  main().catch((err) => {
    console.error("[profiles] échec :", err);
    process.exit(1);
  });
}
