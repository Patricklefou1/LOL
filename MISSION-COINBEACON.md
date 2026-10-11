# Mission CoinBeacon : à exécuter par Claude Code sur le VPS

> Ce fichier est la mission de la session Claude Code qui tourne sur le VPS OVH.
> Utilisateur : prépare le terminal comme indiqué ci-dessous, puis tape dans Claude « Lis MISSION-COINBEACON.md et exécute la mission étape par étape. »

## Avant de lancer Claude : à faire par l'utilisateur, dans tmux, une ligne à la fois

```bash
tmux new -s coinbeacon
read -rs COINBEACON_TOKEN          # coller le jeton puis Entrée : rien ne s'affiche
export COINBEACON_TOKEN
cd ~ && git clone --branch claude/dreamy-cori-p37gxz --single-branch https://github.com/Patricklefou1/LOL.git coinbeacon
cd ~/coinbeacon && claude
```

Le jeton ne vit que dans la variable d'environnement de ce terminal. Il ne doit jamais être collé dans la conversation avec Claude ni écrit dans un fichier.

## Contexte

- Machine : le VPS OVH de production de la capture Pump.fun. Les services `pumpfun-*` tournent depuis `/opt/pumpfun/LOL`, qui appartient à l'utilisateur `pumpfun`.
- **Ne touche jamais à `/opt/pumpfun/LOL`** : ni changement de branche, ni `chown`, ni `sudo git`. Tout le travail se fait dans la copie séparée `~/coinbeacon`.
- Script : `coinbeacon/analyse_setups.py`, avec sa méthode décrite dans `coinbeacon/README.md`.

## Mission

1. **Vérifications de départ** : `pwd` doit afficher `~/coinbeacon` et `git branch --show-current` doit afficher `claude/dreamy-cori-p37gxz`. Fais `git pull` pour être à jour. Vérifie que le jeton est chargé avec `test -n "$COINBEACON_TOKEN" && echo present`, sans jamais afficher sa valeur.
1bis. **Adresse de l'API** : si `COINBEACON_API_URL` est vide, trouve l'endpoint qui alimente `https://app.coinbeacon.io/setups?view=table`. Pour cela, télécharge la page publique et ses fichiers JavaScript **sans envoyer le jeton**, et cherche les URL d'API contenant `setup`, les `baseURL` et les `fetch(`. Note aussi comment le jeton est transmis : en-tête `Authorization: Bearer`, `X-API-Key`, paramètre d'URL ou cookie, pour choisir les options `--auth-*`. **Montre l'adresse trouvée à l'utilisateur et attends sa confirmation** avant d'y envoyer le jeton. Ensuite, passe-la à chaque lancement du script avec `--api-url '...'` : un `export` fait dans une commande ne serait pas gardé pour la suivante. Si tu ne trouves rien de fiable, arrête-toi et dis-le, sans deviner.
2. **Environnement Python**, dans `~/coinbeacon` : `sudo apt install -y python3-venv` si besoin, puis :
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
   git add coinbeacon/resultats/rapport.md coinbeacon/resultats/resume.json coinbeacon/resultats/instantanes
   # seulement si l'utilisateur accepte : git add coinbeacon/resultats/detections.csv
   git commit -m "Resultats de l'analyse CoinBeacon 4 h et 24 h" && git push origin claude/dreamy-cori-p37gxz
   ```
8. **Résumé** pour l'utilisateur : la période couverte, le nombre de détections, l'entonnoir d'exclusion, les champs de l'API, et le verdict à 4 h et 24 h pour les acheteurs et les vendeurs, sans doublons, en citant les biais signalés.

## Règles de conduite

- N'affiche jamais le jeton, n'en fais jamais un écho, ne le mets jamais dans une commande visible.
- Ne touche ni à `/opt/pumpfun/LOL`, ni aux services `pumpfun-*`, ni à ClickHouse.
- Pour pousser, si GitHub demande une authentification, demande à l'utilisateur comment il pousse d'habitude depuis ce VPS. Ne crée pas de jeton GitHub toi-même.
- Si quelque chose ne colle pas, arrête-toi et produis un diagnostic précis au lieu de contourner.
