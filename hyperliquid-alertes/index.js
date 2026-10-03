// Ecoute les fills d'un wallet Hyperliquid (WebSocket userFills) et envoie un mail par ordre execute.
import 'dotenv/config';
import nodemailer from 'nodemailer';

const WALLET = (process.env.HL_WALLET || '').toLowerCase();
const GROUP_MS = Number(process.env.GROUP_MS || 3000);
const WS_URL = 'wss://api.hyperliquid.xyz/ws';

if (!/^0x[0-9a-f]{40}$/.test(WALLET)) throw new Error('HL_WALLET invalide');

const mailer = nodemailer.createTransport({
  host: process.env.SMTP_HOST,
  port: Number(process.env.SMTP_PORT || 465),
  secure: Number(process.env.SMTP_PORT || 465) === 465,
  auth: { user: process.env.SMTP_USER, pass: process.env.SMTP_PASS },
});

async function sendMail(subject, text) {
  await mailer.sendMail({ from: process.env.SMTP_USER, to: process.env.MAIL_TO, subject, text });
  console.log(new Date().toISOString(), 'mail envoye :', subject);
}

if (process.argv.includes('--test-mail')) {
  await sendMail('[Hyperliquid] Test alerte', `Le service d'alerte fonctionne pour ${WALLET}.`);
  process.exit(0);
}

// Un ordre peut etre execute en plusieurs fills : on les regroupe par oid.
const seen = new Set();
const pending = new Map();

function onFill(f) {
  if (seen.has(f.tid)) return;
  seen.add(f.tid);
  if (seen.size > 50000) seen.clear();
  let g = pending.get(f.oid);
  if (!g) {
    g = { fills: [] };
    pending.set(f.oid, g);
  }
  g.fills.push(f);
  clearTimeout(g.timer);
  g.timer = setTimeout(() => flush(f.oid), GROUP_MS);
}

async function flush(oid) {
  const { fills } = pending.get(oid);
  pending.delete(oid);
  const f0 = fills[0];
  const sz = fills.reduce((s, f) => s + Number(f.sz), 0);
  const notional = fills.reduce((s, f) => s + Number(f.sz) * Number(f.px), 0);
  const avgPx = notional / sz;
  const fee = fills.reduce((s, f) => s + Number(f.fee), 0);
  const pnl = fills.reduce((s, f) => s + Number(f.closedPnl), 0);
  const side = f0.side === 'B' ? 'ACHAT' : 'VENTE';
  const subject = `[Hyperliquid] ${f0.dir || side} ${sz} ${f0.coin} @ ${avgPx.toPrecision(6)}`;
  const text = [
    `Wallet     : ${WALLET}`,
    `Actif      : ${f0.coin}`,
    `Sens       : ${side} (${f0.dir})`,
    `Taille     : ${sz}`,
    `Prix moyen : ${avgPx}`,
    `Notionnel  : ${notional.toFixed(2)} USDC`,
    `Frais      : ${fee.toFixed(4)} ${f0.feeToken || ''}`,
    `PnL realise: ${pnl.toFixed(2)} USDC`,
    `Position avant : ${f0.startPosition}`,
    `Fills      : ${fills.length}`,
    `Heure      : ${new Date(f0.time).toISOString()}`,
    `Ordre (oid): ${oid}`,
    `Tx         : https://app.hyperliquid.xyz/explorer/tx/${f0.hash}`,
  ].join('\n');
  try {
    await sendMail(subject, text);
  } catch (e) {
    console.error('echec envoi mail', e);
  }
}

function connect() {
  const ws = new WebSocket(WS_URL);
  let ping;
  ws.onopen = () => {
    console.log(new Date().toISOString(), 'connecte, abonnement userFills', WALLET);
    ws.send(JSON.stringify({ method: 'subscribe', subscription: { type: 'userFills', user: WALLET } }));
    ping = setInterval(() => ws.send(JSON.stringify({ method: 'ping' })), 30000);
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.channel !== 'userFills') return;
    const { fills = [], isSnapshot } = msg.data;
    // Le snapshot initial contient l'historique : on le memorise sans alerter.
    if (isSnapshot) return fills.forEach((f) => seen.add(f.tid));
    fills.forEach(onFill);
  };
  ws.onclose = () => {
    clearInterval(ping);
    console.warn(new Date().toISOString(), 'deconnecte, reconnexion dans 5 s');
    setTimeout(connect, 5000);
  };
  ws.onerror = (e) => console.error('erreur ws', e.message || e);
}

connect();
