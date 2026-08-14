# Mission de validation — stratégie « purge post-migration » (go / no-go)

> Ce fichier est une mission pour la session Claude Code qui tourne sur le VPS.
> Utilisateur : colle dans Claude la ligne de lancement donnée dans le README
> de la branche d'analyse, ou simplement :
> « Lis /opt/pumpfun/LOL-validation/MISSION-VALIDATION-PURGE.md et exécute la mission. »

## Contexte

- Machine : le VPS de capture. **Le service `pumpfun-capture` ne doit être ni
  arrêté, ni ralenti, ni reconfiguré par cette mission.**
- Le dépôt de production est `/opt/pumpfun/LOL` (branche
  `claude/pumpfun-trading-strategy-data-ga4oju`) : on n'y touche pas. La
  mission travaille dans un **worktree** séparé sur la branche d'analyse
  `claude/chartist-figures-pumpfun-tokens-u9odb6`.
- Objectif : produire la mesure go/no-go de la stratégie décrite dans
  `pumpfun-strategie-retenue.md` — rentabilité nette des figures **double
  creux** et **creux en V** sur les tokens gradués, chart post-migration.
- L'outil : `analyse/figures-chartistes/figures_chartistes.py` (Python
  standard, aucune dépendance à installer).

## Mission

0. **Worktree** (si pas déjà fait par la ligne de lancement) :
   `git -C /opt/pumpfun/LOL fetch origin claude/chartist-figures-pumpfun-tokens-u9odb6`
   puis `git -C /opt/pumpfun/LOL worktree add /opt/pumpfun/LOL-validation claude/chartist-figures-pumpfun-tokens-u9odb6`.
   Tout le reste de la mission se passe dans `/opt/pumpfun/LOL-validation`.
1. **Autotest** : `python3 analyse/figures-chartistes/figures_chartistes.py --autotest`
   → attendu `15/15 cas OK`. Sinon, stop et diagnostic.
2. **Profondeur d'historique** : lis le mot de passe ClickHouse depuis
   `/opt/pumpfun/LOL/capture/.env` **sans jamais l'afficher** (ni dans un log,
   ni dans une réponse), puis vérifie ce que couvre la capture :
   `SELECT min(received_at), max(received_at), count() FROM pumpfun.completions`.
   Décide des fenêtres exécutables en source ClickHouse parmi J-1 / J-7 / J-30
   (une fenêtre n'est valable que si la capture tournait ce jour-là, bornes UTC).
3. **Validation (fenêtres couvertes)** — depuis
   `/opt/pumpfun/LOL-validation/analyse/figures-chartistes` :
   ```bash
   mkdir -p resultats
   export CLICKHOUSE_PASSWORD=…   # depuis capture/.env, sans l'afficher
   python3 figures_chartistes.py --source clickhouse --bougies geckoterminal \
       --rentabilite --minutes-post 720 --fenetres <couvertes, ex. 1,7> \
       --echantillon 60 \
       --markdown resultats/validation-purge-$(date -u +%F).md \
       --json     resultats/validation-purge-$(date -u +%F).json
   ```
   Durée attendue : ~5–7 min par fenêtre (limite publique GeckoTerminal
   ~30 req/min, l'outil se throttle tout seul) — ne pas interrompre, ne pas
   paralléliser. En cas de 429 persistants, réduire `--echantillon` à 40.
4. **Fenêtres non couvertes par la capture** (si l'historique < 30 j) :
   relance en mode dégradé
   `--source pumpfun --bougies geckoterminal --fenetres <manquantes>` avec
   suffixe `-approx` dans les noms de fichiers. C'est un best-effort
   (cohorte approchée par jour de création ; l'API publique peut refuser —
   si 401/403, le noter dans le rapport et passer, ne pas insister).
5. **Verdict** — applique les critères de `pumpfun-strategie-retenue.md` § 3,
   sur `double_creux` et `creux_en_v` :
   - médiane **nette** > 0 aux horizons 60 **et** 240 min ;
   - effectif cumulé n ≥ 20 occurrences ;
   - taux de stop < 50 % ;
   - sur au moins deux fenêtres quand trois sont disponibles.
   Énonce explicitement **GO** ou **NO-GO** (ou « historique insuffisant »),
   avec les chiffres à l'appui. Un no-go est un résultat, pas un échec.
6. **Archivage** : dans le worktree, `git add analyse/figures-chartistes/resultats/`
   et committe (message : `Validation purge post-migration du <date> : <verdict>`),
   puis `git push -u origin claude/chartist-figures-pumpfun-tokens-u9odb6`.
   Vérifie avant commit qu'aucun fichier ne contient de secret.
7. **Résumé à l'utilisateur** : verdict, effectifs par figure et par fenêtre,
   taux de stop / d'objectif, fenêtres manquantes, et tout écart par rapport
   à cette mission.

## Règles de conduite

- Lecture seule sur ClickHouse ; aucun `ALTER`, aucun `DROP`, aucune écriture.
- Les secrets (`.env`, mots de passe, tokens) ne sortent jamais : ni stdout,
  ni logs, ni commits, ni réponses.
- Ne « fais pas passer » un critère : si les effectifs sont trop faibles,
  le verdict est « historique insuffisant, re-mesurer dans N jours » —
  c'est une conclusion valide.
- Le service de capture est intouchable ; si le disque est tendu
  (`df -h /`), signale-le, les sorties de cette mission pèsent < 1 Mo.
