# Mission CoinBeacon : à exécuter par Claude Code sur le VPS

> Ce fichier est la mission de la session Claude Code qui tourne sur le VPS OVH.
> Utilisateur : prépare le terminal comme indiqué ci-dessous, puis tape dans Claude « Lis MISSION-COINBEACON.md et exécute la mission étape par étape. »

> **Mise à jour du 23/10 : ne pas lancer `collecteur.py`.** Une collecte équivalente tourne déjà par cron depuis le 11/10 sur le VPS, avec `coinbeacon/suivi_dry.py collecte`, en 1 h, 4 h et 1 j. Lancer `collecteur.py` en plus doublerait les crédits pour rien. La phase 1 ci-dessous est remplacée par le contrôle de cette collecte existante, et la phase 2 devra lire ses données.

## Ce qui a changé

CoinBeacon l'a confirmé : l'API n'a **aucun historique**. `GET https://api.coinbeacon.io/public/setups` renvoie le tableau du moment, 150 lignes au plus, sans pagination. Un setup qui échoue disparaît sans laisser de trace. Il faut donc **collecter** le tableau à chaque clôture de bougie pendant plusieurs semaines, puis analyser ce qui a été collecté.

Les faits donnés par CoinBeacon :
- La clé passe dans l'en-tête `X-API-Key`. Un paramètre d'URL n'est pas lu.
- `computedAt` est en millisecondes UTC. C'est la dernière milliseconde de la dernière bougie close du `tf` de la ligne, à lire ligne par ligne.
- La bougie de déclenchement s'est fermée à `computedAt − archetype.barsSinceTrigger × tf`. `barsSinceTrigger` vaut `null` pour les archétypes sans déclencheur.
- Un setup quitte le tableau s'il ne se qualifie plus, si son déclenchement a plus de 12 bougies, ou s'il sort des 150 lignes. Une réponse marquée `"truncated": true` signale que le serveur n'a lu que 800 candidats.
- `exchange=binance` désigne le comptant Binance. On mesure donc avec les bougies du comptant.
- Chaque appel coûte 5 crédits, sur 2000 par jour en bêta. Collecter en 1 h et en 4 h coûte 150 crédits par jour.
- La documentation complète est sur https://coinbeacon.io/docs/api#setups.

## Avant de lancer Claude : à faire par l'utilisateur, une ligne à la fois

```bash
tmux new -s coinbeacon
read -rs COINBEACON_TOKEN          # coller la clé puis Entrée : rien ne s'affiche
export COINBEACON_TOKEN
cd ~/coinbeacon 2>/dev/null || git clone --branch claude/dreamy-cori-p37gxz --single-branch https://github.com/Patricklefou1/LOL.git ~/coinbeacon
cd ~/coinbeacon && git pull && claude
```

La clé ne vit que dans la mémoire de ce terminal. Ne la colle jamais dans la conversation avec Claude et ne l'écris dans aucun fichier.

## Règles

- **Ne touche jamais à `/opt/pumpfun/LOL`** : ni changement de branche, ni `chown`, ni `sudo git`. Ne touche pas non plus aux services `pumpfun-*` ni à ClickHouse. Tout se fait dans `~/coinbeacon`.
- N'affiche jamais la clé et n'en fais jamais un écho. Vérifie sa présence seulement avec `test -n "$COINBEACON_TOKEN" && echo present`.
- Les données collectées restent hors du dépôt, dans `~/coinbeacon-donnees`. Le dépôt est public.
- Si quelque chose ne colle pas, arrête-toi et produis un diagnostic précis, sans contourner.

## Phase 1 : démarrer la collecte (aujourd'hui)

1. **Départ** : `pwd` doit afficher `~/coinbeacon` et la branche doit être `claude/dreamy-cori-p37gxz`. Vérifie que la clé est présente.
2. **Python** : `sudo apt install -y python3-venv` si besoin, puis `python3 -m venv .venv && . .venv/bin/activate && pip install -r coinbeacon/requirements.txt && python -m pytest coinbeacon/tests -q`. Critère : tous les tests passent.
3. **Lire la documentation** sur https://coinbeacon.io/docs/api#setups. Relève le nom exact du champ de la paire, du champ de sens (achat ou vente) et du type d'archétype, et la clé de premier niveau qui contient les lignes. Compare avec ce qu'attend `coinbeacon/collecteur.py` dans `describe_row` et `CANDIDATES` de `analyse_setups.py`.
4. **Un appel d'essai** : `python coinbeacon/collecteur.py --timeframes 1h`. Puis inspecte la première ligne de `~/coinbeacon-donnees/observations.jsonl` sans afficher la clé :
   ```bash
   head -c 1500 ~/coinbeacon-donnees/observations.jsonl; echo; tail -1 ~/coinbeacon-donnees/appels.jsonl
   ```
   Critères :
   - `http` vaut 200 et `lignes` est supérieur à 0.
   - `symbole` est une paire du type `BTCUSDT` ou `BTC/USDT`.
   - `declenchement_cloture_ms` est rempli pour les archétypes déclenchés.
   - La ligne brute contient un champ de sens.

   Si la paire est mal détectée, relance avec `--champ-paire NOM`. Si le sens n'existe pas, signale-le : l'analyse ne pourra pas séparer acheteurs et vendeurs.
5. **Lancer la collecte en continu**, en arrière-plan, pour qu'elle survive à la fin de la session Claude et à la déconnexion SSH. Elle hérite de la clé de ce terminal, sans que celle-ci passe dans une ligne de commande ni dans un fichier :
   ```bash
   cd ~/coinbeacon && setsid nohup .venv/bin/python coinbeacon/collecteur.py --boucle >> ~/coinbeacon-donnees/collecte.log 2>&1 < /dev/null &
   ```
   N'utilise pas une nouvelle fenêtre tmux : elle n'hériterait pas de la clé. Vérifie au bout de 2 minutes, avec `pgrep -af "collecteur.py --boucle"` et `tail -3 ~/coinbeacon-donnees/collecte.log`, que le processus tourne et qu'une ligne de collecte s'affiche sans erreur. Pour l'arrêter : `pkill -f "collecteur.py --boucle"`.
6. **Résumé pour l'utilisateur** :
   - les champs réellement fournis par l'API ;
   - le nombre de setups vus au premier appel, et le nombre de nouveaux setups par heure si tu as pu l'observer ;
   - les crédits restants ;
   - le rappel suivant : après un redémarrage du serveur, il faudra relancer la collecte en recollant la clé, sinon les clôtures manquées feront des trous dans l'échantillon.

## Phase 2 : analyser (dans 3 à 4 semaines, ou plus tôt pour un point d'étape)

La clé n'est pas nécessaire pour cette phase. Le script lit les setups collectés et les bougies Binance.

```bash
cd ~/coinbeacon && . .venv/bin/activate && git pull
python coinbeacon/analyse_setups.py --observations ~/coinbeacon-donnees/observations.jsonl 2>&1 | tee /tmp/coinbeacon-analyse.log
python coinbeacon/analyse_setups.py --observations ~/coinbeacon-donnees/observations.jsonl --heure-detection declenchement --out-dir coinbeacon/resultats-declenchement
```

- La première commande donne la version **réaliste** : l'entrée se fait à la première bougie après le moment où le collecteur a vu le setup.
- La seconde donne la version **théorique** : l'entrée se fait à la clôture de la bougie de déclenchement. Elle est un peu optimiste, de 90 secondes environ.
- Par défaut, les setups vus plus d'une bougie après leur déclenchement sont écartés et comptés, car ils avaient déjà survécu. C'est le cas de tout le tableau présent au premier appel.

Commit du rapport seulement, après avoir demandé l'accord de l'utilisateur. Ne commite **pas** les données collectées : le dépôt est public.

```bash
git add coinbeacon/resultats/rapport.md coinbeacon/resultats/resume.json coinbeacon/resultats-declenchement/rapport.md
git commit -m "Resultats CoinBeacon : point d'etape" && git push origin claude/dreamy-cori-p37gxz
```
