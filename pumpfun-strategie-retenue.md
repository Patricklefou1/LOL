# La stratégie retenue — achat de la purge post-migration des gradués filtrés

Réponse à la question : « si on ne devait construire qu'**une** stratégie avec
les données dont on dispose *aujourd'hui*, ce serait laquelle ? »

**Celle-ci : acheter le premier creux post-migration des tokens gradués qui
passent les filtres de structure — le « W » sur le dump de migration — avec
invalidation sous les creux.** C'est la stratégie § 2.4 du
[comparatif](pumpfun-choix-strategie.md), rendue **falsifiable** par l'outil
[analyse/figures-chartistes/](analyse/figures-chartistes/) (le setup est un
double creux / creux en V, deux figures que l'outil détecte, simule et classe
avec leurs stops).

> Elle n'est pas « la meilleure stratégie de Pump.fun dans l'absolu » — c'est
> la meilleure **au regard des données et de l'infra réellement disponibles
> maintenant**, et elle se convertit en dataset pour la suivante. La cible de
> long terme du dépôt reste le milieu de courbe (§ 5).

---

## 1. Pourquoi celle-là, avec les données actuelles

1. **Elle est exécutable avec ce qui existe déjà.** Univers = les gradués
   (dizaines/jour, pas des milliers) : la table `completions` et
   `token_summary` (labels `graduated`, `rug_dev_dump`, `dev_sold_fraction`,
   `snipe_slot0_share`) donnent la population et les filtres. Pas besoin des
   bases devs/smart-money des phases 3–4 (pas encore construites), pas de
   guerre de latence : le rythme est humain, un bot n'est même pas requis au
   début.
2. **C'est le seul point du cycle où le chart a le droit de parler.** En
   courbe, la bougie de 5 min est disqualifiante et tout se joue en
   événements ; post-migration, la discipline de clôture a du sens
   ([comparatif § 3.1](pumpfun-choix-strategie.md)). Le setup dominant y est
   documenté : **flush post-migration → stabilisation → seconde jambe si la
   rétention tient** — en vocabulaire chartiste : creux en V ou double creux
   avec ligne de cou, exactement ce que mesure le mode `--rentabilite`.
3. **Le risque y est borné et lisible.** LP verrouillée, plus de rug
   instantané par la courbe ; le pire cas (−80 % sur dump de dev/cluster) est
   couvert par une invalidation *définie avant l'entrée* (sous les creux) et
   par les vetos événementiels (vente du dev).
4. **Chaque trade nourrit la suite.** Journalisé avec ses features à
   l'entrée, il devient le dataset d'entraînement du bot milieu de courbe —
   la progression recommandée du comparatif (§ 5) est respectée, pas
   contournée.

Ce que ce choix écarte, et pourquoi : le **sniping bloc 0** (guerre de latence,
aucune donnée à l'entrée — éliminé tant qu'il n'y a pas de liste de devs
d'élite), le **pré-graduation seul** (edge documenté comme comprimé, jamais en
stratégie unique), les **seuils de holders** (farmés), la **copie smart money**
(filtre, pas stratégie). Le **milieu de courbe** n'est pas écarté : il est
*après* (phases 3–4 du [plan](pumpfun-plan-execution.md)).

## 2. Les règles (falsifiables, pas d'improvisation en séance)

### Univers et filtres éliminatoires (avant tout regard sur le chart)

- Tokens **gradués depuis < 24 h** uniquement.
- Éliminé si : `rug_dev_dump = 1` ou dev encore > 5 % de supply avec
  transferts sortants vers wallets frais ; top 10 holders (hors LP) > 30 % ;
  `snipe_slot0_share` > 30 % ; volume 5 min qui s'évapore (token déjà mort) ;
  image/nom recyclés d'un rug (checklist § 3.8 du
  [référentiel](pumpfun-donnees-strategie.md)).

### Setup et déclencheur

1. **Attendre le flush** : chute ≥ 25–40 % sous le prix de migration dans les
   premières dizaines de minutes. *Ne jamais acheter la migration elle-même*
   (c'est la sortie des cohortes de courbe).
2. **Attendre la structure** : un deuxième creux qui tient le premier (double
   creux, tolérance ±6 %) — ou, pour les reprises violentes, un creux en V
   qui a déjà regagné 80 % de sa chute.
3. **Entrer à la confirmation seulement** : clôture 1–5 min au-dessus de la
   ligne de cou (le pic entre les deux creux). Pas d'entrée « au couteau qui
   tombe » dans le flush.

### Invalidation (sortie stop) — trois niveaux, le premier atteint gagne

- **Graphique** : clôture sous le plus bas des creux → la figure est morte.
- **Événementiel, prioritaire sur tout niveau** : vente du dev / du cluster
  créateur → sortie immédiate ; net flow 30 s qui rebascule négatif avec pic
  de vendeurs uniques → sortie.
- **Temporel** : pas de seconde jambe après quelques heures → on rend la
  position (le garde-fou anti sur-hold du comparatif § 3.2).

### Sorties en profit

Take-profits échelonnés : premier tiers vers +30–50 %, deuxième au retest du
prix de migration ou de l'ATH de courbe, dernier tiers en suiveur sous les
creux 15 min. La rétention de cohorte qui s'effondre = sortie, même en profit.

### Taille et budget d'erreur

Taille minuscule et **fixe** au départ ; risque par trade (distance au stop ×
taille) plafonné à ~1 % du capital d'essai ; kill switch journalier ; coûts
modélisés à 2–3 % l'aller-retour (AMM + priorité + impact) — un setup qui ne
survit pas à 3 % de coûts n'existe pas.

## 3. La valider AVANT de la risquer

La thèse est mesurable à une commande, sur la population post-migration :

```bash
cd analyse/figures-chartistes
MORALIS_API_KEY=... python3 figures_chartistes.py --source moralis \
    --bougies moralis --rentabilite --minutes-post 720 \
    --fenetres 1,7,30 --markdown validation-purge.md
```

**Go** si `double_creux` / `creux_en_v` affichent une médiane nette > 0 à
60 et 240 min avec un effectif décent (n ≥ 20 cumulé) sur au moins deux des
trois fenêtres, et un taux de stop < 50 %. **No-go** sinon : on reste en
observation et on re-mesure la semaine suivante — aucun chiffre n'est supposé
connu tant que la commande n'a pas tourné, et un « go » a une demi-vie de
quelques semaines.

## 4. Trajectoire : cette stratégie n'est pas la destination

| Étape | Condition de passage |
|---|---|
| **Maintenant** : purge post-migration, manuelle puis semi-auto | validation § 3 en « go » |
| **Ensuite** : bot **milieu de courbe** (5–40 %), score composite, sorties événementielles — le cœur visé par le dépôt | phases 3–4 du [plan](pumpfun-plan-execution.md) faites (empreintes devs, smart money) et études fondatrices « go » |
| La purge post-migration redevient un **module d'appoint** | quand le cœur tourne |
| Sniping filtré par liste de devs | seulement si tout le reste est rentable |

Un edge médiocre bien exécuté sur une phase bat cinq edges théoriques mal
exécutés sur toutes — c'est la règle de conduite du comparatif, elle s'applique
d'abord à ce document.
