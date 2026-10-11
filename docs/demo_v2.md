# Démonstration V2 — `full_demo_v2` (8 min) et version jury (3 min)

Toutes les données sont **fictives**. Chaque résultat d'IA porte la mention « Aide à la décision — validation médicale requise ».

## Préparation (avant le jury)

```powershell
.\scripts\run-demo.ps1 -Reset            # http://localhost:8000 (-Port 8010 si le port 8000 est pris)
.\n8n\import.ps1 -Check                  # 15 workflows ACTIFS (n8n lancé par « npx n8n »)
```

- Onglet 1 : la plateforme, compte **`medecin_garde`** ou **`owner`** (mot de passe `hackcure2026`). Panneau **Agents** ouvert à droite.
- Onglet 2 : n8n (<http://localhost:5678>), page **Executions**. Telegram ouvert sur un téléphone.
- Le script règle les délais de démonstration : trajet d'ambulance × 6, résultats du bilan biologique en 30 s, revérification d'un risque 30 s après la sortie du soignant.
- Entre deux passages : **Lancer la démo → stop**, puis relancer `run-demo.ps1 -Reset` pour repartir d'une base propre.

## Ce que fait le pilote automatique

`full_demo_v2` enchaîne des actions du simulateur (constantes, postures, chute) et les **gestes des humains** : sortie d'une patiente, départ de
l'ambulance, réponses au questionnaire, bilan clinique du médecin, validation du bilan biologique, ordonnance, administration, « Je prends en charge ».
Ces gestes sont joués par `dashboard/app/demo_v2.py` **à travers l'API de la plateforme** (mêmes endpoints, mêmes permissions, mêmes agents que pour
un vrai utilisateur) et chacun est tracé dans le journal des agents : « Démo V2 — geste simulé (…) ». Le présentateur n'a qu'à ouvrir les vues ;
il peut aussi faire lui-même n'importe quel geste avant le pilote (le pilote constate alors que c'est déjà fait et passe).

Tout le reste est réel : détection et sévérité par les règles Python, raisonnement des agents par leurs workflows n8n (Claude), notifications
in-app et Telegram, revérification déterministe après le passage du soignant.

## Déroulé minuté — `Lancer la démo → full_demo_v2`

| Temps | Ce qui se passe (automatique) | Vue à montrer | Ce que le jury voit |
|---|---|---|---|
| 0:00 | La patiente de la 104 sort (chambre libre). | **Jumeau 3D** | Lit de la 104 vide, étiquette « libre ». |
| 0:06 | **Départ de l'ambulance** : fiche d'intervention (traumatisme, gravité 2, constantes). La chambre adaptée est réservée aussitôt. | **Ambulances** | Carte Leaflet, ambulance qui avance, **ETA en continu**, « Chambre 104 réservée — arrivée dans X min », équipe prévenue avec la préparation (workflow `ambulance-dispatch`). |
| 0:30 | Arrivée (trajet court, accéléré × 6) : ambulance sur le parking, brancard jusqu'à la chambre, installation au lit, **admission créée**. | **Jumeau 3D** (104) | Gyrophare, brancard, patiente dans le lit ; les appareils de la 104 reprennent. |
| 1:30 | **Questionnaire d'admission** proposé sur la tablette, rempli (PHQ-9, GAD-7, sommeil). | **Psychologie** (104) | Scores, score de bien-être, facteurs, conduite à tenir (`psych-monitoring`). Montrer la page tablette `/patient/questionnaire/…`. |
| 1:40 | Chambre 101 : la **température centrale** monte à 39 °C (fièvre vraie, pas une chambre chaude). | **Centre de commande** | Risque « Fièvre », **médecin de garde demandé**, panneau **Parcours fièvre** : checklist d'examen clinique. Aucune action de confort avant le bilan. |
| 2:30 | Le médecin conclut le **bilan clinique** (checklist). | Parcours fièvre | Étape 2 : **bilan biologique proposé** avec le motif de chaque examen (`fever-pathway`). |
| 2:48 | Le médecin **valide le bilan biologique**. Le confort est alors seulement autorisé. | Parcours fièvre + 3D (101) | « Confort après bilan » : l'EnvironmentAgent agit sur la clim / la fenêtre ; 30 s plus tard, **résultats versés au dossier** et interprétés. |
| 3:00 | **Ordonnance de traitement** : paracétamol 1 g, signée → plan d'administration. | **Plan de soins** (101) | Prise « à faire maintenant », rappel du MedicationAgent (`medication-reminders`), notification à l'infirmier. |
| 3:36 | L'infirmier **administre** la prise (stock décrémenté). | Plan de soins | La prise passe dans « Administré », horodatée et signée. |
| 3:44 | « **Je prends en charge** » sur la fièvre : le médecin de garde entre en 101. | Jumeau 3D (101) | Avatar en blouse blanche près du lit, température qui redescend, puis revérification : risque **résolu et vérifié**. |
| 3:52 | Chambre 102 : la tension baisse, le pouls et la fréquence respiratoire montent. | **Prédictions** (102) | **Sepsis : risque 0–100 qui grimpe, fenêtre « crise estimée dans ~X–Y min »**, confiance, facteurs (qSOFA, NEWS2) ; alerte infirmiers puis médecin de garde (`crisis-prediction`). |
| 4:22 | Chambre 104 : **panne de machine** — le tensiomètre se met en défaut (brassard déconnecté). | **Jumeau 3D** (104) puis **Étage 1 → Équipements** | Bandeau orange « MACHINE FAILURE », carte patient orange, engrenage et étiquette « PANNE D'ÉQUIPEMENT » au-dessus de la potence ; dans la salle Équipements, le tableau du parc indique la chambre et le poste de l'appareil de remplacement. Risque « Panne d'équipement », infirmier notifié. |
| 5:00 | « Je prends en charge » en 104 : l'infirmier vérifie la patiente, remplace l'appareil, sort. | Paramètres des machines (104) | L'appareil passe de « PANNE » à « En marche » ; risque revérifié : résolu. |
| 5:18 | « Je prends en charge » en 102 : le médecin de garde intervient, les constantes se corrigent. | Diagnostics live (102) | Hypothèses avec éléments pour / contre ; fil médecin ↔ infirmier. |
| 5:26 | Chambre 103 : le patient se lève, marche, **chute** (5:42). | **Jumeau 3D** (103) | Avatar au sol, chambre violette, risque critique, plan d'action (`risk-triage`), Telegram. |
| 6:00 | « Je prends en charge » en 103 : l'infirmier entre, relève le patient, sort. | 3D puis Centre de commande | Revérification (`risk-verify`) : **résolu et vérifié**, chambre verte. **Compte rendu d'intervention** en brouillon, à signer. |
| 6:12 | « Je prends en charge » en 104 : le **psychiatre** passe voir la patiente (bien-être bas au questionnaire). | Psychologie (104) | Avatar du psychiatre ; le risque « bien-être psychologique bas » est pris en charge. |
| 7:15 | Tout est résolu et vérifié. | **Carte des agents**, n8n → Executions | 13 agents, 15 workflows, nombre d'appels passés par n8n. |
| 8:00 | Fin du scénario. | **Rapport de garde → Générer** | Le rapport reprend toute la séquence (`shift-report`). |

Les temps de la colonne de gauche sont ceux du scénario (`simulator/scenarios/full_demo_v2.yaml`) ; l'arrivée de l'ambulance et les réponses de
Claude peuvent varier de quelques secondes. Sur une machine très chargée le simulateur prend du retard (il ne saute jamais d'étape) :
le déroulé reste le même, simplement plus lent.

En bruit de fond, les patients simulés vivent leur vie (un patient qui s'assoit au fauteuil peut ouvrir un risque « sortie du lit » de
niveau faible ou moyen) : c'est voulu, et cela se prend en charge comme le reste.

## Version jury — 3 minutes

Lancer `full_demo_v2` **2 min 30 avant** de prendre la parole (le scénario tourne pendant l'introduction), puis :

| Temps de parole | Dire / montrer |
|---|---|
| 0:00 – 0:25 | **Jumeau 3D** : 2 étages, 4 chambres, constantes réelles sur les moniteurs. « Chaque agent observe, les règles décident, l'IA explique. » |
| 0:25 – 0:55 | **Ambulances** : la patiente est arrivée ; trajet, ETA, chambre réservée dès le départ, préparation transmise à l'équipe. Un mot sur le GPS réel par téléphone. |
| 0:55 – 1:35 | **Centre de commande → Parcours fièvre** (101) : fièvre vraie ≠ chambre chaude ; médecin de garde, bilan clinique, bilan biologique validé, **confort seulement après**, résultats au dossier. Ouvrir **Dossier médical** 5 s (15 ans d'historique). |
| 1:35 – 2:00 | **Plan de soins** : ordonnance → rappel → administration tracée. **Psychologie** (104) : questionnaire sur tablette, score de bien-être. |
| 2:00 – 2:30 | **Prédictions** (102) : sepsis estimé dans une fenêtre de temps, facteurs, mention « non validé cliniquement ». |
| 2:30 – 2:50 | **Jumeau 3D** (103) : la chute a lieu en direct (5:42 du scénario) ; l'infirmier prend en charge, le risque est revérifié. |
| 2:50 – 3:00 | **Carte des agents** + onglet n8n : un workflow par agent, repli local si n8n s'arrête. Conclusion. |

## Scénarios unitaires (menu « Lancer la démo »)

Le menu liste d'abord les scénarios, puis les **résolutions par un soignant** (lancées aussi automatiquement par « Je prends en charge » en simulation).

| Scénario | Chambre | Montre | Résolution |
|---|---|---|---|
| `full_demo_v2` | 104, 101, 102, 103 | Toute la V2 | automatiques |
| `full_demo` / `fall_demo` | 101 / 104 | Lever, chute (V1) | `nurse_resolves`, `fall_resolves`, `bed_exit_resolves` |
| `fever_101` | 101 | Fièvre vraie, parcours complet | `fever_resolves` |
| `room_overheat_102` | 102 | Simple hausse thermique : confort seul, aucune alerte clinique | automatique (ambiance) |
| `desaturation_103` | 103 | SpO2 graduée, oxymètre | `desaturation_resolves` |
| `sepsis_trend` | 102 | NEWS2, prédiction de sepsis | `sepsis_resolves` |
| `cardiac_event_102` | 102 | Sus-décalage ST, événement cardiaque | `cardiac_resolves` |
| `hypoglycemia_104` | 104 | Glucomètre, complication du diabète | `hypoglycemia_resolves` |
| `seizure_103` | 103 | Mouvements rythmiques, crise d'épilepsie | `seizure_resolves` |
| `deterioration_101` | 101 | Détérioration générale | `sepsis_resolves` |
| `machine_error_103` | 103 | **Panne de machine** : pompe à perfusion en défaut moteur (3D, salle Équipements, risque équipement) | `equipment_resolves` |
| `iv_empty` | 103 | Perfusion vide, occlusion | `iv_resolves` |

## Montrer une panne de machine (30 secondes)

Trois façons, même résultat (risque « Panne d'équipement » rattaché à l'appareil, 3D, notification de l'infirmier) :

1. **Lancer la démo → `machine_error_103`** : la pompe à perfusion de la 103 publie elle-même sa panne (défaut moteur).
2. Panneau **Contrôles de démo** (en bas à gauche) : choisir le patient et l'appareil, bouton **⚙️ Panne machine** (événement `machine_error` du pipeline d'Amal) ; **✅ Récupération** remet l'appareil en service.
3. Elle est aussi dans `full_demo_v2` (tensiomètre de la 104, à 4:22).

À montrer : la chambre (bandeau du moniteur, engrenage, étiquette), **Étage 1 → Équipements** (tableau du parc et repère vert sur le poste de
remplacement), **Paramètres des machines** (étiquette « PANNE »), **Centre de commande** (plan : voir le patient, vérifier l'appareil, le remplacer,
prévenir le biomédical). « Je prends en charge » fait entrer l'infirmier ; à sa sortie le risque est revérifié.
Une occlusion ou une poche vide ne sont pas des pannes : elles gardent leurs propres alertes (`iv_empty`).

## Si quelque chose ne va pas

- **Textes « Réponse de secours (LLM indisponible) »** : la clé Anthropic n'a plus de crédit (c'est arrivé pendant les répétitions, un passage complet
  fait environ 50 appels). Recharger le crédit avant la démo ; sans cela tout fonctionne, mais les explications de l'IA sont génériques.

- **Sans crédit d'API ni n8n** : `LLM_PROVIDER=mock` et `N8N_ENABLED=false` dans `.env` — toute la démo (dont `full_demo_v2` et la panne de machine) fonctionne, les textes d'IA sont des gabarits.
- **n8n arrêté** : rien à faire, les agents passent en repli local (badge « repli local »), la démo continue.
- **Pas de réseau** : la carte des ambulances n'a pas de fond, la liste des missions et l'ETA restent affichées ; le LLM passe en réponse de secours.
- **Port 8000 pris** : `.\scripts\run-demo.ps1 -Port 8010` et `.\n8n\import.ps1 -PlatformUrl http://127.0.0.1:8010`.
- **Base d'une ancienne version** : relancer avec `-Reset` (nouveaux patients, médicaments et historique).
