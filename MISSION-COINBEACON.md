# Mission CoinBeacon : à exécuter par Claude Code sur le VPS

> Ce fichier est la mission de la session Claude Code qui tourne sur le VPS OVH.
> Utilisateur : prépare le terminal comme indiqué ci-dessous, lance `claude`, puis tape « Lis MISSION-COINBEACON.md et exécute la mission étape par étape. »

## Avant de lancer Claude : à faire par l'utilisateur, dans tmux

```bash
tmux new -s coinbeacon
read -rs COINBEACON_TOKEN && export COINBEACON_TOKEN     # coller le jeton puis Entrée : rien ne s'affiche
export COINBEACON_API_URL='https://...'                    # endpoint des setups
cd /opt/pumpfun/LOL && claude
```

Le jeton ne vit que dans la variable d'environnement de ce terminal. Il ne doit jamais être collé dans la conversation avec Claude ni écrit dans un fichier.

## Contexte

- Machine : le VPS OVH de production de la capture Pump.fun. Les services systemd `pumpfun-*` tournent depuis `/opt/pumpfun/LOL`, sur la branche `claude/pumpfun-trading-strategy-data-ga4oju`.
- **Ne jamais changer de branche dans `/opt/pumpfun/LOL`** : cela modifierait le code exécuté par les services. Le travail se fait dans un worktree séparé.
- Script : `coinbeacon/analyse_setups.py` sur la branche `claude/dreamy-cori-p37gxz`. Sa méthode est décrite dans `coinbeacon/README.md`.

## Mission

1. **Worktree séparé** :
   ```bash
   cd /opt/pumpfun/LOL && git fetch origin claude/dreamy-cori-p37gxz
   git worktree add /opt/pumpfun/coinbeacon origin/claude/dreamy-cori-p37gxz 2>/dev/null || (cd /opt/pumpfun/coinbeacon && git checkout --detach origin/claude/dreamy-cori-p37gxz)
   cd /opt/pumpfun/coinbeacon
   ```
   Vérifie ensuite que `git -C /opt/pumpfun/LOL branch --show-current` affiche toujours la branche de production.
2. **Environnement Python** : `sudo apt install -y python3-venv` si besoin, puis :
   ```bash
   python3 -m venv .venv && . .venv/bin/activate && pip install -r coinbeacon/requirements.txt
   python -m pytest coinbeacon/tests -q
   ```
   Critère : tous les tests passent.
3. **Disque** : `df -h /`. Le cache des bougies peut atteindre plusieurs centaines de Mo. S'il reste moins de 3 Go libres, arrête-toi et signale-le.
4. **Les trois contrôles** : `python coinbeacon/analyse_setups.py --check-only`. Si l'un échoue, **arrête-toi** et rapporte le message exact et le code de sortie (2 jeton, 3 API CoinBeacon, 4 Binance). N'invente rien et ne simule rien.
   Si le script ne reconnaît pas la pagination ou les champs, regarde la structure d'une réponse sans jamais afficher le jeton, puis ajuste avec les options décrites dans `coinbeacon/README.md`. Ne modifie pas la méthode de calcul.
5. **Analyse complète** : `python coinbeacon/analyse_setups.py 2>&1 | tee /tmp/coinbeacon.log`. Le premier passage peut durer longtemps à cause du téléchargement des bougies. Le cache rend les passages suivants rapides.
6. **Contrôle des sorties** : vérifie que le jeton n'apparaît nulle part.
   ```bash
   grep -rlF "$COINBEACON_TOKEN" coinbeacon/resultats coinbeacon/.cache /tmp/coinbeacon.log && echo FUITE || echo "aucune fuite"
   ```
   En cas de fuite, n'en commite rien et préviens l'utilisateur.
7. **Commit** : le dépôt est **public**. Demande à l'utilisateur s'il accepte de publier le CSV des détections, ou seulement le rapport.
   ```bash
   git switch -c claude/dreamy-cori-p37gxz --track origin/claude/dreamy-cori-p37gxz 2>/dev/null || git switch claude/dreamy-cori-p37gxz
   git add coinbeacon/resultats/rapport.md coinbeacon/resultats/resume.json coinbeacon/resultats/instantanes
   # seulement si l'utilisateur accepte : git add coinbeacon/resultats/detections.csv
   git commit -m "Resultats de l'analyse CoinBeacon 4 h et 24 h" && git push origin claude/dreamy-cori-p37gxz
   ```
8. **Résumé** pour l'utilisateur : la période couverte, le nombre de détections, l'entonnoir d'exclusion, les champs de l'API, et le verdict à 4 h et 24 h pour les acheteurs et les vendeurs, sans doublons, en citant les biais signalés.

## Règles de conduite

- N'affiche jamais le jeton, n'en fais jamais un écho, ne le mets jamais dans une commande visible.
- Ne touche ni aux services `pumpfun-*` ni à ClickHouse.
- Si quelque chose ne colle pas, arrête-toi et produis un diagnostic précis au lieu de contourner.
