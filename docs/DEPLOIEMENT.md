# Déploiement — étude de faisabilité et modèle économique (livrable L3)

**Tous les chiffres de ce document sont des estimations** : des ordres de grandeur calculés à partir d'hypothèses écrites noir sur blanc. Ce ne sont ni des devis, ni des prix relevés chez un fournisseur, ni des mesures. Chaque montant doit être revérifié avant d'être présenté à un client.

Hypothèses de change utilisées partout (à actualiser) : **1 EUR ≈ 3,4 TND** et **1 USD ≈ 0,92 EUR**.

Rappel de l'état du prototype (`MORNING_REPORT.md`, `BLOCKERS.md`) : données fictives ; aucun essai sur un vrai Raspberry Pi documenté ; appareils médicaux simulés ; l'image Docker n'a pas été construite. Ce document décrit donc un déploiement **à faire**, pas un déploiement réalisé.

---

## 1. Faisabilité sur le terrain

### 1.1 Ce qu'on installe

| Élément | Quantité | Rôle | Référence dans le dépôt |
|---|---|---|---|
| Boîtier de chambre : Raspberry Pi 5, caméra, caméra thermique MLX90640, DHT22, bouton d'appel, contact de porte, buzzer, veilleuse, relais | 1 par chambre | Vision et capteurs traités sur place, règles locales | `edge/main.py`, `edge/config/room101.yaml`, câblage dans `MORNING_REPORT.md` §4 |
| Serveur de la clinique | 1 | Plateforme FastAPI, base de données, Mosquitto, n8n | `docker-compose.yml` |
| Postes et tablettes existants | — | Navigateur web : jumeau 3D, vues métier, questionnaire patient | `dashboard/static/` |

### 1.2 Réseau

- **Flux par chambre** : uniquement du JSON. `vision/state` à 2 Hz, `thermal` à 1 Hz, `env` toutes les 5 s (`contracts/mqtt-topics.md`, `edge/config/room101.yaml`). Estimation : quelques kilo-octets par seconde par chambre (hypothèse : messages de 200 à 400 octets) — **non mesuré**. Aucune vidéo ne circule, sauf l'aperçu flouté optionnel (`stream_port`).
- **Wi-Fi ou Ethernet** : le Pi fonctionne avec l'un ou l'autre. Recommandation : Ethernet (ou PoE avec un adaptateur) pour les chambres de soins critiques ; un réseau local séparé (VLAN) pour les boîtiers.
- **Coupure réseau** : l'edge continue d'appliquer ses règles locales (buzzer, veilleuse, climat — `edge/safety/local_rules.py`) et garde en file les messages importants (`OfflineQueue` dans `edge/transport/__init__.py`), renvoyés à la reconnexion.
- **Sans broker** : repli HTTP `POST /api/ingest` et commandes par `GET /api/edge/commands`.
- **Internet** : nécessaire seulement pour le LLM externe, Telegram, les tuiles de carte et, aujourd'hui, les bibliothèques JavaScript chargées depuis un CDN (`dashboard/static/index.html`). À corriger avant déploiement : servir ces bibliothèques localement.
- **À sécuriser** : MQTT authentifié et chiffré (port 8883), HMAC des trames (`EDGE_HMAC_KEY`), HTTPS (`HTTPS=true`) — voir `docs/CONFORMITE.md`.

### 1.3 Alimentation électrique

- Estimation de consommation d'un boîtier : 5 à 12 W selon la charge (hypothèse tirée des caractéristiques publiques du Pi 5 ; **non mesuré**).
- Alimentation officielle 27 W USB-C, ou PoE.
- Coupure de courant : sans onduleur le boîtier s'arrête. Recommandation : brancher les boîtiers sur le circuit secouru de l'établissement, ou prévoir un petit onduleur par aile. Le service systemd `edge/systemd/hackcure-edge.service` relance l'edge au redémarrage.
- Le serveur doit être sur onduleur.

### 1.4 Un Pi par chambre : pourquoi, et ce que cela implique

- Pourquoi : le traitement de l'image se fait dans la chambre, donc aucune image ne sort (vie privée), et une panne ne touche qu'une chambre.
- Charge de calcul : le dépôt ne contient **aucune mesure sur Pi**. Les seuls chiffres sont ceux d'un PC avec carte graphique (`computer_vision/reports/benchmark_results.json`). L'edge ne traite qu'une image sur deux (`process_every: 2`) et publie à 2 Hz, ce qui laisse de la marge, mais la cadence réelle du modèle YOLO sur Pi 5 est **à mesurer** pendant le pilote.
- Maintenance : une carte SD par boîtier (prévoir une image système unique et un remplacement simple), mises à jour par `git pull` aujourd'hui — un outil de gestion de flotte est à prévoir au-delà de quelques dizaines de chambres.
- Chambres à plusieurs lits : le suivi actuel identifie **un** patient par chambre, celui qui est dans le polygone du lit (`edge/vision/persons.py`). Les chambres doubles ne sont **pas couvertes**.

### 1.5 Placement de la caméra et vie privée

- **Placement** : en hauteur, face au lit, avec le lit, la porte de la salle d'eau et la sortie dans le champ. Calibration par `python edge/calibrate_zones.py` : on dessine les polygones `bed`, `bathroom_door`, `exit`.
- **Jamais dans la salle d'eau** : seule sa porte est dans le champ ; l'absence est déduite de la dernière zone connue (`edge/vision/posture_map.py`).
- **Aucune image ne quitte la chambre** : le Pi publie `posture`, `activity`, `zone`, `persons`. Aucun enregistrement vidéo, ni sur le Pi ni sur le serveur.
- **Aperçu** : optionnel, basse résolution, flouté, relayé sans stockage et réservé aux rôles cliniques (`dashboard/app/api/camera.py`). Il peut être désactivé (`stream_port: 0`).
- **Information** : affichage en chambre et notice à l'admission ; possibilité de refuser la caméra (voir `docs/CONFORMITE.md` §2.5).
- **Caméra thermique** : 32 × 24 pixels, pas d'image reconnaissable ; elle donne une température cutanée indicative, **jamais** un diagnostic de fièvre (`dashboard/app/clinical/fever.py`).

### 1.6 Formation du personnel

Proposition (durées estimées) :

| Public | Durée | Contenu |
|---|---|---|
| Infirmiers | 2 h | Lire une alerte, « Je prends en charge », plan de soins, compte rendu d'intervention ; ce que le système ne fait pas |
| Médecins | 1 h 30 | Parcours fièvre, ordonnance de traitement, diagnostics live, prédictions et leurs limites, signature |
| Réception, pharmacie | 1 h | Admissions, ambulances ; stock et alertes |
| Référent technique | 1 journée | Installation d'un boîtier, calibration, `/health`, sauvegardes, procédure de panne |

Message central de la formation : **le système aide, il ne remplace ni la ronde ni le jugement clinique**. Une chambre verte ne veut pas dire « patient sans risque ».

### 1.7 Intégration au système d'information hospitalier existant

- **Lecture par le SIH** : API HL7 FHIR R4 en lecture (`/fhir/Patient`, `/fhir/Observation`, `/fhir/Condition`, `/fhir/AllergyIntolerance`, `/fhir/MedicationRequest`, `/fhir/Encounter`, `$everything`) avec codes LOINC — **activable** (`FHIR_ENABLED`, `docs/interoperabilite.md`, état dans `PROGRESS_V3.md`).
- **Ce qui manque** : l'écriture FHIR, la réception des admissions depuis le SIH (aujourd'hui saisies dans la plateforme), HL7 v2, la connexion aux vrais moniteurs. Chaque moniteur réel demandera un adaptateur qui publie le contrat `device.json` ; le reste de la plateforme ne change pas, puisque le simulateur utilise déjà ce contrat.
- **Base de données** : SQLite pour le prototype ; SQL Server possible par `DATABASE_URL`, **non testé**.

### 1.8 Verdict de faisabilité

| Point | Faisable ? | Condition |
|---|---|---|
| Installation en chambre | oui | essais matériels à faire ; boîtier adapté au milieu de soins |
| Réseau | oui | flux légers ; VLAN et chiffrement à mettre en place |
| Vie privée | oui | aucune image ne sort ; information et consentement à organiser |
| Passage à l'échelle | à démontrer | aujourd'hui 4 chambres codées en dur (`ingest/handler.py`, `ROOMS`) ; voir `docs/QA_JURY.md` question 1 |
| Usage clinique réel | non en l'état | validation clinique et démarche réglementaire (`docs/CONFORMITE.md` §3) |

---

## 2. Modèle économique

### 2.1 Qui paie

| Payeur | Ce qu'il y gagne | Remarque |
|---|---|---|
| Cliniques privées | Sécurité des patients la nuit, argument de qualité, moins d'incidents non vus | premier marché visé : décision rapide, budget propre |
| Hôpitaux publics | Aide aux équipes en sous-effectif | achat par marché public : cycle long, plutôt via un projet pilote financé |
| Mutuelles et assureurs | Moins de complications coûteuses (chutes, sepsis vus tard) | hypothèse à démontrer par des données ; payeur indirect à moyen terme |

### 2.2 Offre

- **Abonnement par lit et par mois**, incluant logiciel, mises à jour et support.
- **Matériel** : vendu à l'installation, ou loué et inclus dans l'abonnement.
- **Frais d'installation** uniques : pose, calibration, formation.

Hypothèse de prix à tester (ce n'est pas un tarif) : **150 à 250 TND par lit et par mois** (≈ 44 à 74 EUR).

### 2.3 Coût du matériel par chambre — estimation

Hypothèse : prix publics européens arrondis, hors taxes et hors transport. En Tunisie, prévoir une majoration pour l'importation et la douane — **hypothèse : +30 %**, à vérifier auprès d'un importateur.

| Élément | Estimation EUR | Estimation TND (× 3,4) |
|---|---|---|
| Raspberry Pi 5 (8 Go) | 95 | 323 |
| Alimentation officielle 27 W | 14 | 48 |
| Carte microSD 64 Go (endurance) | 12 | 41 |
| Boîtier avec refroidissement actif | 18 | 61 |
| Caméra (module caméra Pi ou webcam USB) | 30 | 102 |
| Caméra thermique MLX90640 (carte) | 65 | 221 |
| Capteur DHT22 | 6 | 20 |
| Module relais 4 voies | 6 | 20 |
| Bouton d'appel + contact de porte | 8 | 27 |
| Buzzer, veilleuse LED, servo de fenêtre | 12 | 41 |
| Câblage, connecteurs, fixation murale | 15 | 51 |
| **Total par chambre** | **≈ 281** | **≈ 955** |
| Avec majoration d'importation de 30 % (hypothèse) | ≈ 365 | ≈ 1 240 |

Calcul : 95 + 14 + 12 + 18 + 30 + 65 + 6 + 6 + 8 + 12 + 15 = 281 EUR ; 281 × 3,4 ≈ 955 TND ; × 1,3 ≈ 1 240 TND.

Non compris : la pose (hypothèse : 1 à 2 heures de technicien par chambre), les actionneurs réels de climatisation, chauffage et fenêtre (le prototype pilote des LED et un servo de démonstration), la certification électrique du boîtier.

### 2.4 Coût du serveur — estimation

Hypothèses : une clinique de 30 lits ; un mini-serveur sur site (processeur 8 cœurs, 32 Go de mémoire, 1 To de SSD) avec onduleur.

| Poste | Estimation |
|---|---|
| Mini-serveur | 900 à 1 500 EUR (≈ 3 100 à 5 100 TND) |
| Onduleur | 150 à 250 EUR (≈ 510 à 850 TND) |
| Amortissement sur 4 ans, 30 lits | (1 500 + 250) / 48 mois / 30 lits ≈ **1,2 EUR par lit et par mois** (≈ 4 TND) |

Attention : la capacité réelle du serveur (nombre de chambres par machine) **n'a pas été mesurée**. Ce dimensionnement est une hypothèse à valider par un essai de charge.

### 2.5 Coût de l'API du LLM — estimation avec le calcul

Le LLM n'est appelé que pour rédiger (explication, plan, synthèse, compte rendu) ; il est limité par conception (une lecture de tendance par chambre toutes les 5 min, `agents/vitals.py`, `agents/vision.py`).

**Étape 1 — appels par risque.** D'après le code : 1 appel pour le plan (`risk-triage` ou `RiskAgent.enrich`), 1 pour la vérification quand elle passe par n8n (`risk-verify`), 1 pour le compte rendu (`intervention-report`), environ 1 lecture de tendance ou observation (`vitals-trend` / `vision-watch`). **Hypothèse : 4 appels par risque.**

**Étape 2 — risques par lit et par jour.** Non mesuré sur de vrais patients. **Hypothèse : 3 risques par lit et par jour.**

**Étape 3 — autres appels.** Rappels de médicaments (**hypothèse : 4 par jour**), synthèses de diagnostics (**hypothèse : 4 par jour**), part du rapport de garde et de la synthèse de dossier (**hypothèse : 2 par jour**).

**Total** : 3 × 4 + 4 + 4 + 2 = **22 appels par lit et par jour**.

**Étape 4 — taille d'un appel.** **Hypothèse : 2 000 tokens en entrée et 1 500 en sortie** (le code autorise jusqu'à 8 000 tokens en sortie, `agents/llm.py` ; la consommation réelle n'a pas été relevée).

- Entrée : 22 × 2 000 = 44 000 tokens par lit et par jour.
- Sortie : 22 × 1 500 = 33 000 tokens par lit et par jour.

**Étape 5 — prix.** **Hypothèse de prix : 3 USD par million de tokens en entrée et 15 USD par million en sortie.** Ce prix est une hypothèse de travail : **à relever sur la grille tarifaire officielle d'Anthropic** pour le modèle configuré (`LLM_MODEL`) le jour du calcul.

- Entrée : 0,044 × 3 = 0,13 USD.
- Sortie : 0,033 × 15 = 0,50 USD.
- **Total : ≈ 0,63 USD par lit et par jour**, soit ≈ 19 USD par lit et par mois ≈ **17 EUR ≈ 59 TND**.

Repère tiré du dépôt : un passage complet de la démo `full_demo_v2` déclenche **environ 50 appels** au LLM (`BLOCKERS.md`) — mais c'est une démo de 8 minutes qui concentre tous les scénarios sur 4 chambres, pas une journée normale.

**Lecture du résultat.** Avec ces hypothèses, le LLM serait le premier poste de coût récurrent (59 TND sur un abonnement de 150 à 250 TND). Leviers, par ordre d'effet attendu :

1. réserver le LLM aux risques `high` et `critical` (les plans de secours `FALLBACK_PLANS` couvrent déjà les autres) ;
2. utiliser un modèle moins cher pour les notes courtes (`LLM_MODEL` est une variable) ;
3. espacer davantage les lectures de tendance ;
4. à terme, un modèle hébergé sur place (coût fixe, plus aucun transfert de données).

Sans LLM (`LLM_PROVIDER=mock`), ce coût est **nul** et la détection fonctionne à l'identique : c'est le mode de la démo actuelle.

### 2.6 Synthèse par lit — estimation

Hypothèses : 30 lits, matériel amorti sur 4 ans, majoration d'importation incluse.

| Poste | Par lit et par mois |
|---|---|
| Matériel de chambre : 1 240 TND / 48 mois | ≈ 26 TND |
| Serveur et onduleur | ≈ 4 TND |
| API du LLM (hypothèses du §2.5) | ≈ 59 TND |
| Support, maintenance, remplacement de matériel (hypothèse) | ≈ 20 TND |
| **Coût estimé** | **≈ 109 TND** |
| Prix testé | 150 à 250 TND |
| **Marge brute estimée** | **≈ 41 à 141 TND** |

Ce tableau n'inclut ni les salaires de l'équipe, ni la certification réglementaire, ni le coût commercial. Il sert uniquement à montrer que le prix visé est du bon ordre de grandeur et que le LLM est le poste à maîtriser.

### 2.7 Bénéfice attendu pour l'établissement

Nous n'avons **aucune mesure** de réduction des chutes, des sepsis vus tard ou du temps infirmier. Ces bénéfices sont l'hypothèse que le pilote devra tester (section 4). Nous ne citons donc aucun pourcentage.

---

## 3. Freins à l'adoption et réponses

| Frein | Réponse |
|---|---|
| « Une caméra dans la chambre, c'est de la surveillance » | Aucune image ne sort ni n'est stockée ; aperçu flouté optionnel ; information, consentement, droit de refus ; avis du comité d'éthique |
| Fatigue d'alarme | Anti-bruit (3 lectures consécutives), déduplication par chambre et par type, seuils adaptés au patient, signaux secondaires rattachés au risque critique existant — mais le taux réel de fausses alertes est à mesurer en pilote |
| Méfiance envers l'IA | Les règles décident, le LLM rédige, l'humain valide ; chaque alerte montre les valeurs et la règle ; mention « aide à la décision » partout |
| Responsabilité médicale | Le système est consultatif ; toute signature et toute validation sont nominatives et tracées dans `AuditLog` |
| Coût | Abonnement par lit, matériel grand public peu cher, mode sans LLM |
| Réseau et électricité instables | Règles locales sur l'edge, file hors ligne, repli HTTP, repli local si n8n ou le LLM tombe |
| Intégration au SIH existant | API FHIR en lecture ; contrats de messages documentés pour brancher de vrais appareils |
| Données de santé envoyées à l'étranger | Pseudonymisation des flux sortants ; fonctionnement possible sans aucun service externe |
| Charge de travail supplémentaire | « Je prends en charge » en un clic, brouillons de comptes rendus et de rapports de garde rédigés automatiquement |
| Réglementation (dispositif médical, INPDP) | Démarche prévue dans la feuille de route ; d'ici là, usage limité à un pilote encadré, en complément des pratiques existantes |
| Dépendance à un fournisseur de LLM | Fournisseur isolé derrière une interface (`agents/llm.py`) ; mode `mock` ; modèle local envisagé |

---

## 4. Feuille de route

### À 3 mois — rendre le prototype prêt pour un pilote

| Objectif | Livrable vérifiable |
|---|---|
| Matériel réel | 2 à 4 boîtiers Raspberry Pi 5 assemblés et testés ; cadence et consommation **mesurées** ; calibration thermique |
| Vision | Poids YOLO entraînés versionnés et déployés sur Pi ; évaluation sur des vidéos tournées dans une chambre réelle avec des volontaires ; décision sur le Vision Transformer (jamais exécuté à ce jour) |
| Sécurité | TLS, HMAC des trames, AES-256-GCM et pseudonymisation activés et testés ; MQTT authentifié ; secrets de production ; test d'intrusion simple |
| Robustesse | Passage à PostgreSQL ou SQL Server ; chambres configurables (fin de la liste codée en dur) ; état des agents persistant ; essai de charge avec le simulateur |
| Conteneurs | Image Docker construite et testée ; sauvegarde et restauration documentées |
| Interopérabilité | API FHIR validée avec un validateur officiel ; premier adaptateur pour un moniteur réel |
| Conformité | Premier échange avec l'INPDP et un juriste ; analyse d'impact rédigée ; avis d'un comité d'éthique |
| Clinique | Revue de tous les seuils et scores par deux cliniciens ; protocole du pilote écrit |

### À 6 mois — pilote et preuve de valeur

| Objectif | Livrable vérifiable |
|---|---|
| Pilote | 5 à 10 lits dans une clinique partenaire, en **mode observation** : le système alerte en parallèle des pratiques habituelles, sans les remplacer |
| Mesures | Taux de fausses alertes et d'événements manqués par type de risque ; délai de prise en charge ; charge perçue par les soignants (questionnaire) |
| Biais | Analyse des performances par âge, sexe, corpulence, conditions d'éclairage ; correction des seuils |
| Coûts | Consommation réelle du LLM relevée ; essai d'un modèle moins cher ou local ; mise à jour du §2 avec des chiffres mesurés |
| Intégration | Admissions reçues du SIH ; servir les bibliothèques JavaScript localement ; remplacement de Telegram par une messagerie maîtrisée |
| Réglementaire | Classification du logiciel comme dispositif médical arrêtée avec un spécialiste ; plan de mise en conformité (qualité, gestion des risques, cycle de vie logiciel) chiffré |
| Produit | Gestion des chambres doubles ; outil de mise à jour de la flotte de boîtiers ; tableau de bord de supervision technique |
| Commercial | Deux lettres d'intention de cliniques ; prix validé par le pilote |

Critère d'arrêt honnête : si le pilote montre un taux de fausses alertes que les soignants jugent inacceptable, la priorité devient le réglage de la détection, pas l'extension commerciale.
