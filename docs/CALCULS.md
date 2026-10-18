# Calculs de CarbonLedger AI

Toutes les formules vivent dans `app/calc/` : fonctions pures, sans accès à la base
de données ni au web, entièrement couvertes par `tests/`. Ce document décrit les
règles appliquées, avec des exemples chiffrés reproductibles.

---

## 1. Émissions (formule générale)

```
Émissions (kg CO₂e) = quantité d'activité × facteur d'émission (kg CO₂e / unité)
```

- La quantité est d'abord **convertie vers l'unité du facteur** (voir §5).
- Conversion en tonnes : `1 t = 1 000 kg`.
- Arrondi : 3 décimales sur les kg, 2 décimales sur les tonnes.
- Une quantité manquante, nulle ou négative **refuse** l'estimation (`compute_emissions_kg`).

Exemples (`app/calc/emissions.py`) :

| Quantité | Facteur | Émissions |
|---|---|---|
| 15 000 kWh | 0,700 kg/kWh | 10 500,000 kg = 10,500 t |
| 6 200 L de gazole | 2,652 kg/L | 16 442,400 kg = 16,442 t |
| 41 000 t.km de fret | 0,106 kg/t.km | 4 346,000 kg = 4,346 t |

### Statut de la donnée

Le statut est **toujours conservé** dans la chaîne :

| Statut | Signification | Origine typique |
|---|---|---|
| `mesure` | mesure directe | compteur, analyse, facture fournie en kg CO₂e |
| `calcule` | calcul à partir d'un facteur documenté | `quantité × facteur` |
| `estime` | estimation | facteur indicatif, **estimation monétaire** |

Une estimation monétaire (ratio DH → kg CO₂e) est **toujours** classée `estime`,
jamais `calcule` : le catalogue la marque comme approximative par nature.

---

## 2. Coût total d'une option (comparateur)

Sur une période commune de `H` années (1 à 30) :

```
coût d'acquisition   = coût d'achat + coût de transport
coûts annuels nets   = coûts de fonctionnement + maintenance − économies attendues
coût total           = coût d'acquisition + Σ(H années) coûts annuels nets

trésorerie année 1   = − coût d'acquisition
trésorerie année n   = trésorerie année (n−1) − coûts annuels nets
```

- Les économies attendues sont des **données saisies**, jamais estimées par
  l'application (elles apparaissent comme « à confirmer par le réalisé »).
- Aucune valeur résiduelle, aucun remplacement, aucun intérêt d'emprunt n'est
  ajouté automatiquement. Si la durée de vie est **inférieure** à l'horizon, un
  avertissement explicite l'indique (« aucun remplacement n'est chiffré »).

### Actualisation (facultative)

Si un taux est renseigné (0 = désactivé par défaut) :

```
coût actualisé net = coût d'acquisition + Σ(H années) coûts annuels nets / (1 + taux)^année
```

Exemple : 80 000 DH + 24 000 DH/an sur 5 ans au taux de 5 % →
**183 907,44 DH** (contre 200 000 DH sans actualisation).

---

## 3. Émissions cumulées et comparaison carbone

```
émissions annuelles (t) = émissions annuelles (kg) / 1 000
émissions cumulées (t)  = émissions annuelles × H
```

Aucune variation annuelle n'est inventée : les émissions sont supposées
constantes sur la période (hypothèse affichée dans les notes du comparateur).

### Coût par tonne de CO₂e évitée

```
coût par tonne évitée = (coût de l'option la moins émettrice − coût de l'option la plus émettrice)
                        ÷ (émissions de la plus émettrice − émissions de la moins émettrice)
```

- **Résultat négatif** → l'option la moins émettrice est **aussi la moins chère** :
  c'est un **double gain**. L'application écrit explicitement « N DH *économisés* par
  tonne évitée » et rappelle qu'il ne s'agit pas d'une recette comptable.
- **Résultat positif** → c'est le **surcoût** à payer pour éviter une tonne de
  CO₂e. L'application précise toujours « une réduction d'émissions n'est pas une
  économie financière automatique ».
- Si l'une des deux options n'a pas d'émissions, **aucun** coût par tonne n'est
  calculé : l'interface affiche « non disponible » avec la raison.

### Exemple de référence (cahier des charges)

| | Option A | Option B |
|---|---|---|
| Acquisition | 80 000 DH | 95 000 DH |
| Fonctionnement annuel | 24 000 DH | 17 000 DH |
| Coût total sur 5 ans | 200 000 DH | **180 000 DH** |
| Émissions annuelles | 12 t | 7 t |
| Émissions cumulées | 60 t | **35 t** |

- Économie : 200 000 − 180 000 = **20 000 DH**
- Émissions évitées : (60 − 35) = **25 t** (5 t/an × 5 ans)
- Coût par tonne évitée : (180 000 − 200 000) ÷ 25 = **−800 DH/t** → double gain
- Délai de rattrapage : le surcoût initial de B (15 000 DH) est compensé en
  15 000 ÷ 7 000 ≈ **2,1 ans** (7 000 DH = écart de coûts annuels nets)

Ce cas est chargé dans le jeu de démonstration (« Remplacement d'une presse
hydraulique ») et vérifié par `tests/test_decision_spec.py`.

---

## 4. Prix interne du carbone

Optionnel, en DH par tonne de CO₂e :

```
coût étendu = coût total + émissions cumulées (t) × prix interne du carbone
```

- Si le prix interne est nul (valeur par défaut), les émissions **ne sont pas**
  converties en dirhams : le classement financier reste strictement financier.
- S'il est renseigné, le classement et l'arbitrage utilisent le coût étendu, et la
  méthode est rappelée dans les notes et dans le rapport PDF.

---

## 5. Unités (conversions strictement encadrées)

Familles reconnues : énergie (`kWh`, `MWh`, `GJ`), volume (`L`, `m3`), masse (`kg`,
`g`, `t`), distance (`km`), fret (`t.km`), passagers (`passager.km`), surface
(`m2`), quantité (`unite`, `nuit`, `forfait`), montant (`MAD`).

- Conversion autorisée **à l'intérieur d'une même famille** uniquement.
- `kWh → MWh` (÷ 1 000), `m3 → L` (× 1 000), `t → kg` (× 1 000)…
- `kg ↔ kWh`, `MAD ↔ EUR` : **refusés** — l'application ne devine pas de taux.
- Alias usuels acceptés : `m³`, `DHS`, `tonnes`, `lt`, casse et espaces ignorés.

---

## 6. Conséquences des scénarios

Un scénario est un jeu d'écarts appliqués **aux hypothèses**, jamais aux données
saisies. Les options ne sont jamais modifiées en base.

| Hypothèse | Effet |
|---|---|
| Prix de l'énergie | S'applique à la **part d'énergie déclarée** des coûts de fonctionnement. Sans part déclarée, aucun effet : l'interface l'indique. |
| Volume d'activité | Module la part non-énergétique des coûts de fonctionnement et les économies attendues (maintenance maintenue constante). |
| Coûts de transport | S'applique au poste transport. |
| Économies attendues | Module les économies déclarées. |
| Facteurs d'émission | Module les émissions annuelles. |
| Durée d'utilisation | ± N années, pour comparer la sensibilité de l'horizon. |

Scénarios prédéfinis :

| Scénario | Hypothèses |
|---|---|
| **base** | hypothèses saisies, sans modification |
| **optimiste** | énergie −10 %, transport −10 %, économies +10 %, facteurs d'émission −5 % |
| **défavorable** | énergie +15 %, transport +15 %, économies −20 %, facteurs d'émission +10 % |

Chaque scénario affiche l'**écart** (coût et émissions) par rapport à la base et
signale si la conclusion change (« la conclusion change, à examiner avec
attention »).

---

## 7. Analyse de sensibilité

Six hypothèses sont perturbées (± 10 % par défaut, ± 1 an pour la durée) :

- prix de l'énergie, coûts de transport, économies attendues, volume d'activité,
  facteurs d'émission, durée d'utilisation.

Pour chacune, l'application affiche l'amplitude de l'écart de coût (et
d'émissions) entre les deux premières options, et signale si l'hypothèse **peut
inverser le classement**. Les hypothèses sans effet sont annotées (« Aucune option
ne précise la part d'énergie… »).

---

## 8. Frontière de compromis (Pareto)

Une option est **dominée** si une autre est à la fois moins chère et moins
émettrice (au moins strictement sur un critère). L'application affiche les options
**non dominées** comme « frontière de compromis » et refuse de désigner un gagnant
unique quand plusieurs options restent en frontière :

> « Plusieurs options restent en frontière de compromis… choisissez selon votre
> situation financière et vos engagements, plutôt que sur un score unique. »

---

## 9. Priorités d'arbitrage

| Priorité | Classement |
|---|---|
| `cout` | coût total croissant (ou coût étendu si un prix interne est défini) |
| `tresorerie` | mise de fonds initiale croissante, puis coût annuel net |
| `emissions` | émissions cumulées croissantes, puis coût (repli sur le coût si les émissions manquent, avec mention explicite) |
| `equilibre` | score combiné coût / émissions, **normalisation min-max 0-100, pondération égale**, affiché comme tel |

Chaque fiche d'option contient : avantages, inconvénients, faits (« mise de fonds
initiale : … », « confiance déclarée : … »), et les avertissements du moteur de
calcul. Toutes les phrases sont construites à partir des valeurs calculées : aucun
chiffre n'est rédigé à la main.

---

## 10. Périodes et agrégations du tableau de bord

Périodes disponibles : mois en cours, mois précédent, trimestre, année en cours,
12 derniers mois, tout l'historique, période personnalisée. Pour chaque période,
la période précédente comparable est calculée automatiquement (12 mois précédents,
année précédente, période équivalente) — sauf pour « tout l'historique », où
l'application indique qu'aucune comparaison n'est possible.

- Évolution : `(valeur − valeur précédente) ÷ valeur précédente × 100` ; si la base
  est nulle, l'application affiche « — » au lieu d'une progression fictive.
- Répartitions : part de chaque catégorie dans le total (0,1 % près).
- Carbone : total, part **mesurée / calculée / estimée**, part strictement
  **monétaire**, répartition par catégorie et par scope.
