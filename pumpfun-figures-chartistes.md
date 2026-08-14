# Figures chartistes haussières des tokens gradués Pump.fun

Ce document répond à la question : **« quelles figures chartistes haussières
sont les plus représentées parmi les tokens gradués sur Pump.fun — hier, il y a
7 jours, il y a 30 jours ? »** — et fournit l'outil qui produit la réponse
chiffrée : [analyse/figures-chartistes/](analyse/figures-chartistes/).

> ⚠️ Les fréquences réelles ne peuvent pas être « connues d'avance » : elles se
> mesurent sur les données du moment et changent avec les métas (voir
> [pumpfun-donnees-strategie.md](pumpfun-donnees-strategie.md), § 7). Tout
> chiffre qui ne sort pas d'une exécution datée de l'outil est une hypothèse,
> pas une mesure. Rien ici n'est un conseil financier.

---

## 1. Ce qu'on mesure exactement

- **Population** : les tokens **gradués** (bonding curve complétée, migration
  vers PumpSwap). Sur la base de capture du dépôt, c'est la table
  `completions` — la vérité on-chain, sans biais du survivant. Via API,
  c'est `graduatedAt` (Moralis) ou une approximation par jour de création
  (API publique Pump.fun, qui n'expose pas l'horodatage de graduation).
- **Fenêtres** (UTC) : mode `jours` = trois cohortes d'un jour — **hier
  (J-1)**, **il y a 7 jours (J-7)**, **il y a 30 jours (J-30)** ; mode
  `cumule` = derniers 1 / 7 / 30 jours glissants.
- **Chart analysé** : bougies 1 min (ré-échantillonnées en 5 min au-delà de
  ~12 h de série) :
  - source `clickhouse` : la **phase bonding curve**, c'est-à-dire le chart
    qui a *mené* à la graduation — le plus pertinent pour chercher des setups
    pré-graduation ;
  - sources `moralis` / `geckoterminal` : les premières heures
    **post-graduation** (12 h par défaut, `--minutes-post`).
- **Comptage** : un token « présente » une figure si le détecteur trouve au
  moins une occurrence complète (cassure comprise quand la figure l'exige).
  Une série peut présenter plusieurs figures ; les % sont rapportés aux tokens
  analysés et ne somment pas à 100 %.

## 2. Les 12 figures haussières détectées

| Figure | Type | Structure détectée | Validation |
|---|---|---|---|
| **Canal ascendant** | continuation | ≥ 2 sommets croissants ET ≥ 2 creux croissants (+3 % chacun) | la structure suffit |
| **Drapeau haussier** | continuation | mât ≥ +30 % en ≤ 20 barres, consolidation plate/descendante ≥ 3 barres, retracement < 50 % du mât | clôture au-dessus du sommet du mât |
| **Fanion haussier** | continuation | même mât, consolidation **convergente** (sommets baissants, creux montants) | clôture au-dessus du sommet du mât |
| **Triangle ascendant** | continuation | résistance plate (sommets dans une bande de 6 %), creux croissants | cassure de la résistance |
| **Rectangle haussier** | continuation | sommets et creux dans des bandes de ±4 %, profondeur 5–35 % | cassure du haut du range |
| **Biseau descendant** | renversement | sommets et creux baissants, pente des sommets plus raide (convergence) | cassure de la ligne des sommets |
| **Double creux (« W »)** | renversement | 2 creux égaux à 6 % près, pic intermédiaire ≥ +8 % | cassure de la ligne de cou |
| **Triple creux** | renversement | 3 creux dans une bande de 8 % | cassure du plus haut des 2 pics |
| **ETE inversée** | renversement | tête ≥ 5 % sous des épaules égales à 12 % près | cassure de la ligne de cou (pente incluse) |
| **Tasse avec anse** | continuation | fond en U (ajustement parabolique, R² ≥ 0,55), profondeur 12–65 %, anse ≤ ½ profondeur | cassure du bord |
| **Fond arrondi** | renversement | même U sans exigence d'anse | retour au bord (97 %) |
| **Creux en V** | renversement | chute ≥ 25 % en ≤ 12 barres | reprise de 80 % de la chute en ≤ 12 barres |

Déduplication des figures emboîtées : un triple creux absorbe le double creux
qu'il contient ; une tasse avec anse absorbe le fond arrondi.

Détection : pivots ZigZag à seuil **adaptatif** (3,5 × l'amplitude médiane des
bougies, borné à 5–25 %) — indispensable sur des memecoins où une bougie
« normale » fait plusieurs pourcents ; tous les seuils sont relatifs, jamais en
valeur absolue. Le volume n'est pas utilisé comme critère de confirmation
(extension possible : voir le net flow de
[pumpfun-donnees-strategie.md](pumpfun-donnees-strategie.md), § 2).

## 3. Obtenir la réponse chiffrée

```bash
# Sur le VPS de capture (recommandé) :
cd analyse/figures-chartistes
python3 figures_chartistes.py --source clickhouse \
    --markdown resultats.md --json resultats.json

# Sans la base : MORALIS_API_KEY=... python3 figures_chartistes.py --source moralis
# Vérifier les détecteurs sans réseau : python3 figures_chartistes.py --autotest
```

La sortie classe, pour chaque fenêtre (hier, J-7, J-30), les figures par
nombre de tokens et % des séries analysées. Coller `resultats.md` ci-dessous
pour archiver chaque exécution datée.

### Résultats archivés

*(à remplir par les exécutions de l'outil — aucun chiffre tant que la commande
n'a pas tourné sur une machine ayant accès aux données)*

## 4. À quoi s'attendre — hypothèses mécaniques, à valider par la mesure

La mécanique de Pump.fun **déforme** les fréquences des figures par rapport à
un marché classique ; c'est le biais structurel à garder en tête en lisant les
résultats :

1. **La phase courbe favorise mécaniquement les figures de continuation.** Un
   token qui gradue a, par définition, monté (~30 SOL virtuels → ~85 SOL
   réels). Son chart pré-graduation contient donc presque toujours des jambes
   de hausse entrecoupées de pauses : attendez-vous à voir dominer **canal
   ascendant, drapeau haussier et consolidation-cassure (rectangle/triangle
   ascendant)** — non parce qu'ils « marchent », mais parce que la population
   est conditionnée sur la hausse (biais de sélection assumé de la question).
2. **Les figures lentes sont rares en courbe.** Tasse avec anse, fond arrondi
   et ETEi demandent du temps et des allers-retours ; la majorité des
   graduations se jouent en minutes/heures. Leur fréquence devrait monter sur
   les tokens qui graduent lentement et en post-graduation.
3. **Le post-graduation est le royaume du double creux et du creux en V.** Le
   schéma classique est un dump de prise de profits à la migration, puis, pour
   la minorité qui survit, une reprise — soit en V, soit en W (« second
   pump », cf. la métrique « distance à l'ATH » du référentiel de données).
4. **Les fréquences dérivent avec les métas et le régime de marché.** Comparer
   hier / J-7 / J-30, c'est précisément mesurer cette dérive : un écart
   important entre les trois fenêtres est un signal de changement de régime,
   pas un artefact.

Corollaire pour la recherche d'edge (cf.
[pumpfun-trouver-un-edge.md](pumpfun-trouver-un-edge.md)) : « la figure la
plus représentée » n'est pas « la figure la plus rentable ». La fréquence est
une statistique descriptive ; l'edge se teste en étude d'événement — c'est le
mode `--rentabilite` du § 4 bis.

## 4 bis. Quelle figure est la plus rentable ? — entrée, invalidation, mesure

### Les règles de trade codées dans l'outil

Chaque occurrence détectée porte trois niveaux : **entrée** (clôture de la
barre de confirmation), **invalidation** (le stop : si le prix y revient, la
figure est annulée — on sort), **objectif** (la « mesure » classique de la
figure). Ce sont les définitions standard de l'analyse technique, appliquées
mécaniquement :

| Figure | Entrée (confirmation) | Invalidation (stop) | Objectif classique |
|---|---|---|---|
| **Drapeau / fanion haussier** | cassure du sommet du mât | clôture sous le **bas de la consolidation** (invalidation anticipée : retracement > 50 % du mât) | mât reporté depuis la cassure |
| **Canal ascendant** | barre suivant le dernier pivot du canal | clôture sous le **dernier creux montant** (la cassure du bas du canal tue la structure) | largeur du canal |
| **Triangle ascendant** | cassure de la résistance plate | clôture sous le **dernier creux montant** | hauteur du triangle |
| **Rectangle haussier** | cassure du haut du range | retour sous le **support du range** (un simple retour sous la résistance cassée est déjà un avertissement de fausse cassure) | hauteur du range |
| **Biseau descendant** | cassure de la ligne des sommets | clôture sous le **dernier creux du biseau** | retour au sommet du biseau |
| **Double / triple creux** | cassure de la ligne de cou | clôture sous le **plus bas des creux** | hauteur creux → cou |
| **ETE inversée** | cassure de la ligne de cou (pente incluse) | clôture sous l'**épaule droite** (sous la tête = invalidation « dure », plus lointaine) | hauteur tête → cou |
| **Tasse avec anse** | cassure du bord de la tasse | clôture sous le **creux de l'anse** (anse > 50 % de la profondeur = figure déjà invalide) | profondeur de la tasse |
| **Fond arrondi** | retour sur le bord du U | clôture sous le **fond du U** | profondeur du U |
| **Creux en V** | reprise de 80 % de la chute | clôture sous le **creux du V** | retour au sommet d'origine |

Deux invalidations transversales propres à Pump.fun, prioritaires sur tout
niveau graphique (cf. [pumpfun-donnees-strategie.md](pumpfun-donnees-strategie.md),
§ 3.1) : **vente du dev** et bascule du net flow 30 s en négatif avec pic de
vendeurs uniques — on ne « laisse pas travailler » une figure contre ces
signaux.

### La mesure

```bash
python3 figures_chartistes.py --source clickhouse --rentabilite \
    --couts 0.03 --horizons 15,60,240 --markdown resultats.md
```

Pour chaque occurrence : achat à la confirmation, sortie au stop si
l'invalidation est touchée avant l'horizon, sinon à l'horizon ; rendement
**net** des coûts (`--couts`, défaut 3 % l'aller-retour : ~1 % de frais
protocole × 2 + slippage/priorité). Le classement par fenêtre se fait sur la
**médiane nette à l'horizon clé** (défaut 60 min, `--horizon-cle`), avec
n ≥ 5 occurrences exigées pour le verdict ; sont aussi affichés le taux de
stop, le taux d'objectif atteint et le % de trades gagnants. La médiane est
préférée à la moyenne : sur ce marché en loi de puissance, la moyenne est
dominée par 2–3 trades extrêmes (§ 7 du référentiel de données).

Limites spécifiques : remplissage au niveau exact du stop (optimiste sur un
memecoin illiquide — durcir `--couts` pour compenser), horizons au-delà de la
fin de série portés à plat, et sur la phase courbe les horizons longs sont
tronqués à la graduation.

### Ce que dit la littérature (priors, pas des mesures Pump.fun)

Sur les marchés actions (statistiques de Bulkowski, *Encyclopedia of Chart
Patterns*), les figures haussières les mieux classées en performance
post-cassure sont le **drapeau serré après très forte hausse** (« high & tight
flag », historiquement la meilleure), l'**ETE inversée** et la **tasse avec
anse** — avec des taux d'échec qui doublent quand la cassure n'est pas
confirmée ou que le retracement dépasse les seuils d'invalidation ci-dessus.
Transposé à la mécanique Pump.fun : le candidat structurel n°1 en phase courbe
est précisément le **drapeau haussier post-mât** (c'est la forme canonique
d'une courbe qui gradue : jambe, pause peu profonde, cassure), et en
post-graduation le **double creux** sur le dump de migration. À confirmer ou
infirmer par la commande ci-dessus — et un même classement doit être re-mesuré
régulièrement : la demi-vie d'un edge ici se compte en semaines.

## 5. Limites connues

- **Subjectivité codifiée** : une figure chartiste n'a pas de définition
  canonique ; les seuils du § 2 sont un choix (documenté, versionné,
  ajustable en tête de script). Comparer des exécutions = garder les mêmes
  seuils.
- **Biais du survivant côté API** : les tokens morts sortent des API
  publiques ; seule la capture locale donne la population complète (raison
  d'être de [capture/](capture/)).
- **Granularité** : 1 min lisse les graduations éclair (< 20 bougies →
  série écartée et comptée « trop courte ») ; le taux d'écartement est
  affiché par fenêtre.
- **Co-occurrences** : les détecteurs sont indépendants ; une même jambe de
  hausse peut compter dans deux figures voisines (canal + drapeau). Les
  emboîtements triviaux sont dédupliqués, pas les chevauchements partiels.
- **Cohortes `pumpfun`** : sans horodatage de graduation public, la cohorte
  est approchée par le jour de création — préférer `clickhouse` ou `moralis`.
