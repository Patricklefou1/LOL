# hyperliquid-alertes

Envoie un mail à chaque ordre exécuté sur Hyperliquid pour un wallet (abonnement WebSocket `userFills`, fills regroupés par ordre).

## Installation (VPS)

```bash
cd /opt/pumpfun/LOL/hyperliquid-alertes
npm install
cp .env.example .env   # remplir SMTP_PASS (mot de passe d'application Gmail)
npm run test-mail      # vérifie l'envoi
sudo cp hyperliquid-alertes.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now hyperliquid-alertes
journalctl -u hyperliquid-alertes -f
```

Limites : les fills survenus pendant une coupure WebSocket sont rattrapés par le snapshot à la reconnexion, mais sans alerte (ils sont seulement marqués comme vus).
