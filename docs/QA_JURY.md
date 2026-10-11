# Questions probables du jury — réponses courtes

Chaque réponse tient en quelques phrases que vous pouvez dire telles quelles, suivies du fichier qui la prouve.
Règle d'or : ne jamais annoncer un chiffre qui n'est pas dans le dépôt. Quand ce n'est pas mesuré, dites « non mesuré, c'est prévu dans le pilote ».
Pour tout ce qui concerne la V3 (Docker, TLS, AES, HMAC, FHIR, pseudonymisation, SADM) : les huit cases de `PROGRESS_V3.md` sont cochées, mais « fait » ne veut pas dire « testé en conditions réelles ». Avant de répondre, lisez le tableau « Vérifié / non vérifié » de `MORNING_REPORT.md` (section V3). Deux réponses à ne pas enjoliver : **Docker n'a jamais été lancé** (fichiers validés seulement), et **rien n'a tourné sur un vrai Raspberry Pi**.

---

## Ce qui est réel, ce qui est simulé

**1. Qu'est-ce qui est réel et qu'est-ce qui est simulé dans votre démo ?**
Réel : toute la chaîne logicielle — contrats de messages, ingestion, 13 agents, règles cliniques, boucle soignant, interface 3D, 15 workflows n8n, testés par la suite de tests et par des passages réels avec Claude et Telegram.
Simulé : les patients (données fictives), les appareils médicaux, les résultats de laboratoire, les pannes, les trajets d'ambulance, et les soignants virtuels en démo.
Aujourd'hui la démo tourne avec `LLM_PROVIDER=mock` et n8n désactivé, parce que notre crédit d'API Anthropic est épuisé : les textes d'IA sont des réponses déterministes. La détection n'en dépend pas.
→ `MORNING_REPORT.md` (V2.3, V2.4), `BLOCKERS.md`.

**2. Avez-vous testé sur un vrai Raspberry Pi ? Et le Vision Transformer ?**
Non. Le code edge est complet et tourne de bout en bout sur PC en mode `--fake`, mais aucun essai sur un vrai Pi n'est documenté ; caméra thermique, DHT22 et GPIO sont simulés automatiquement quand le matériel est absent.
Le Vision Transformer (DINOv2) d'Amal est intégré mais n'a jamais été exécuté chez nous : ni les poids ni PyTorch ne sont installés. Le repli sur le détecteur seul est automatique et testé.
→ `MORNING_REPORT.md` §3 et V2.3, `AMAL_SYNC.md` (écarts volontaires), `edge/vision/pipeline.py` (`build_pipeline`).

---

## Passage à l'échelle et pannes

**3. Combien de chambres par serveur ? Qu'est-ce qui casse en premier ?**
Nous ne l'avons pas mesuré. Aujourd'hui le prototype gère 4 chambres, codées en dur (`ROOMS` dans `ingest/handler.py`, 4 chambres dans la scène 3D).
Ce qui casserait en premier, dans l'ordre : SQLite, qui n'accepte qu'un écrivain à la fois ; puis l'état en mémoire dans un seul processus (`room_state`, compteurs des agents) ; puis le bus interne, dont les files bornées jettent les plus anciens messages.
Ce qui est déjà prévu : mesures sous-échantillonnées en base, diffusion WebSocket regroupée, `DATABASE_URL` pour un serveur SQL (non testé).
→ `dashboard/app/bus.py`, `dashboard/app/db.py`, `DECISIONS.md` (07:10, 07:12).

**4. Que se passe-t-il si le réseau tombe ?**
Dans la chambre, l'edge continue seul : chute ou appel → buzzer et veilleuse, climat régulé, sans serveur.
Il garde en file locale les messages importants (alarme, entrée ou sortie du personnel, appel) et les renvoie à la reconnexion ; les états périmés sont abandonnés.
Si le broker MQTT est absent, tout passe par le repli HTTP `POST /api/ingest`, avec le même traitement.
→ `edge/safety/local_rules.py`, `edge/transport/__init__.py` (`OfflineQueue`, `HttpTransport.flush`), `contracts/mqtt-topics.md`.

**5. Et si n8n ou le LLM tombe ?**
Trois niveaux, tous affichés dans l'interface. n8n injoignable (sonde `/healthz`, 3 tentatives) → l'agent exécute le même prompt lui-même. LLM en erreur, trop lent (45 s) ou JSON invalide → plan de secours prédéfini par type de risque, étiqueté « réponse de secours (LLM indisponible) ».
Le risque est toujours créé et notifié **avant** l'appel au LLM.
Nous l'avons vécu : crédit épuisé pendant un passage réel, la démo est allée au bout.
→ `dashboard/app/orchestration.py` (`ask`, `_run_local`), `dashboard/app/agents/risk.py` (`on_candidate`, `enrich`), `agents/plans.py` (`FALLBACK_PLANS`), `BLOCKERS.md`.

---

## Éthique, vie privée, biais

**6. Une caméra dans une chambre d'hôpital, ce n'est pas un problème de vie privée ?**
C'est le point le plus sensible, et l'architecture est faite autour de lui. L'image est analysée dans la chambre, sur le Pi ; seul un état sort (`posture`, `activity`, `zone`, nombre de personnes). Aucune image n'est envoyée ni stockée.
L'aperçu est optionnel, basse résolution, flouté, non enregistré, réservé aux rôles cliniques. La salle d'eau n'est pas filmée.
Avant un usage réel : information du patient, consentement, droit de refus, avis d'un comité d'éthique.
→ `edge/main.py` (en-tête, `MjpegServer`), `dashboard/app/api/camera.py`, `docs/CONFORMITE.md` §2.

**7. Quels biais dans vos modèles et vos scores ?**
Plusieurs, et nous ne les avons pas mesurés. Le modèle de vision est entraîné sur des jeux de données d'images de chutes (listés dans l'audit), pas sur des patients tunisiens dans de vraies chambres : âge, corpulence, vêtements, éclairage de nuit, couvertures ne sont pas représentés de façon contrôlée.
Les seuils et les poids des scores viennent de règles connues (NEWS2, qSOFA) et de choix de l'équipe, calibrés sur un simulateur. PHQ-9 et GAD-7 sont des échelles standard, mais leur version française et notre questionnaire de sommeil ne sont pas validés pour cette population.
Notre garde-fou : chaque score affiche ses facteurs, et un humain décide.
→ `computer_vision/reports/dataset_audit.md`, `dashboard/app/clinical/prediction.py` (en-tête), `DECISIONS.md` (22:20, 23:05).

**8. Où vont les données ? Sortent-elles de Tunisie ?**
La base, le broker et n8n tournent sur le serveur de la clinique. Deux services sont à l'étranger : l'API du LLM et Telegram.
Réponse prévue en V3 : tout ce qui sort est pseudonymisé (`PAT-0001`, chambre, âge, sexe, données cliniques ; jamais le nom ni la date de naissance) — interrupteur `PSEUDONYMIZE_OUTBOUND`. Et on peut ne rien envoyer du tout : `LLM_PROVIDER=mock`, n8n et Telegram coupés ; la détection continue.
Un transfert hors de Tunisie relève de la loi 2004-63 et de l'INPDP : formalités à faire avant tout usage réel.
→ `docs/CONFORMITE.md` §2.7 et §2.8, `dashboard/app/config.py`.

---

## Sécurité clinique

**9. Qui décide : l'IA ou le médecin ?**
Trois étages. Les **règles Python** détectent et fixent la sévérité (une chute est toujours critique). Le **LLM** explique et propose un plan de 3 à 6 étapes. L'**humain** valide : prise en charge, bilan biologique, ordonnance, compte rendu sont signés par un soignant identifié.
Le LLM ne peut ni changer une sévérité, ni clore un risque seul, ni cocher un examen, ni réécrire une dose.
→ `dashboard/app/agents/plans.py` (`severity_for`), `agents/followup.py` (`verify_risk`), `DECISIONS.md` (14:20, 19:55, 21:58), `n8n/README.md` §4.

**10. Et si le LLM hallucine ?**
Son influence est bornée. Sa sortie doit être un JSON avec les clés attendues, sinon elle est rejetée et remplacée par la réponse de secours (`specs.validate`, nœud « Valider le JSON » dans n8n).
Il reçoit un contexte déjà calculé par les règles, avec la consigne de ne jamais inventer de valeur.
Ce qu'il produit est du texte consultatif, étiqueté « Aide à la décision — validation médicale requise ». Pour clore un risque, son avis ne compte que si le contrôle déterministe sur l'état réel de la chambre est aussi satisfait.
Limite honnête : un texte faux mais plausible peut encore être lu par un soignant ; d'où la validation humaine obligatoire.
→ `dashboard/app/agents/specs.py`, `dashboard/app/orchestration.py` (`DISCLAIMER`), `dashboard/app/prompts/_system.md`.

**11. Comment évitez-vous les fausses alarmes et la fatigue d'alerte ?**
Par cinq mécanismes : trois lectures consécutives hors limite avant une alerte ; hystérésis sur la posture (sauf la chute, immédiate) ; un seul risque ouvert par chambre et par type ; seuils adaptés au patient (BPCO, fibrillation) ; un signal secondaire pendant un risque critique est rattaché, pas dupliqué.
Nous avons aussi distingué la fièvre vraie de la simple chambre chaude, qui ne déclenche aucune alerte.
Ce que nous n'avons pas : un taux de fausses alertes mesuré sur de vrais patients. C'est l'objectif numéro un du pilote.
→ `dashboard/app/agents/vitals.py` (`PERSIST`, `limits_for`), `agents/vision.py` (`HYSTERESIS_S`), `agents/risk.py` (déduplication), `clinical/fever.py`.

**12. Un risque peut-il disparaître tout seul parce qu'une valeur est redevenue normale ?**
Non pour un risque clinique. Si le signal revient dans les limites, le système l'écrit sur le risque (« à confirmer par un soignant ») et le laisse ouvert.
Il faut : prise en charge, présence d'un soignant dans la chambre, sortie, puis revérification automatique de l'état réel. Si le critère n'est pas satisfait, le risque est escaladé au médecin de garde.
Seuls les risques d'ambiance (inconfort thermique) se ferment seuls.
→ `dashboard/app/agents/risk.py` (`AUTO_CLEARABLE`, `on_clear`), `agents/followup.py` (`recheck`), `DECISIONS.md` (18:55).

**13. Vos prédictions de crise, sur quoi reposent-elles ?**
Sur des règles additives transparentes pour cinq situations, plus une extrapolation linéaire de la tendance sur 10 minutes pour estimer une fenêtre de temps, avec une marge de ± 40 %.
La « confiance » affichée mesure la quantité de données disponibles, pas une probabilité.
C'est écrit à l'écran : « Estimation de prototype, non validée cliniquement ». Nous ne revendiquons aucune performance prédictive.
→ `dashboard/app/clinical/prediction.py` (`predict`, `slope_per_min`, `window_to`, `_result`), `DECISIONS.md` (23:00, 23:05).

---

## Sécurité informatique et interopérabilité

**14. Comment protégez-vous l'accès et les données ?**
En place : mots de passe hachés (bcrypt), session JWT en cookie HttpOnly, 7 rôles avec permissions vérifiées côté serveur, journal d'audit de toutes les modifications et de chaque lecture du dossier médical, secrets hors du dépôt, échanges avec n8n authentifiés dans les deux sens.
Prévu en V3, activable par `.env` : HTTPS en TLS 1.3, chiffrement AES-256-GCM des champs sensibles en base, signature HMAC-SHA256 des trames des capteurs avec rejet des trames rejouées ou trop anciennes, adresse IP dans l'audit.
Limites : par défaut `/api/ingest` est ouvert et le broker MQTT de démo est anonyme ; pas de double authentification.
→ `dashboard/app/auth.py`, `dashboard/app/audit.py`, `dashboard/app/api/dossier.py` (`audit_read`), `docs/CONFORMITE.md` §1.

**15. Comment vous intégrez-vous à un système d'information hospitalier ?**
Par une API HL7 FHIR R4 en lecture : Patient, Observation (codes LOINC pour les constantes), Condition, AllergyIntolerance, MedicationRequest, Encounter et `$everything` — fonction V3, à confirmer dans `PROGRESS_V3.md`.
Dans l'autre sens, nos contrats de messages sont documentés : brancher un vrai moniteur revient à écrire un adaptateur qui publie le contrat `device.json`, déjà utilisé par le simulateur.
Ce qui manque : écriture FHIR, HL7 v2, réception des admissions depuis le SIH.
→ `docs/interoperabilite.md` (V3), `contracts/mqtt-topics.md`, `dashboard/app/contracts.py`.

---

## Choix techniques et coûts

**16. Pourquoi ces composants : Pi 5, YOLO, MQTT, n8n, SQLite, Claude ?**
Pi 5 : assez puissant pour traiter l'image sur place, donc aucune image ne sort. YOLO : détection temps réel légère, déjà entraînée par Amal. MQTT : standard IoT, avec un repli HTTP pour fonctionner sans broker. n8n : attentes, escalades et messages visibles et modifiables sans redéployer. SQLite : zéro installation pour la démo, serveur SQL possible. Claude : JSON structuré fiable et bon français, isolé derrière une interface interchangeable.
Chaque choix a un inconvénient que nous connaissons.
→ `docs/ARCHITECTURE.md` §6, `DECISIONS.md`.

**17. Quelles sont les performances de votre modèle de vision ?**
Les chiffres du dépôt concernent le modèle à deux classes (`falling` / `no_falling`) sur son jeu de test : précision 0,92, rappel 0,93, mAP@50 0,94. La latence mesurée, environ 6 à 7 ms par image, l'a été sur un PC avec carte graphique, **pas sur un Raspberry Pi**.
Ces résultats viennent des jeux de données d'entraînement, pas de chambres réelles ; les poids ne sont pas dans le dépôt et l'évaluation n'a pas été rejouée sur notre machine.
→ `computer_vision/reports/evaluation_report.md`, `computer_vision/reports/benchmark_results.json`, `MORNING_REPORT.md` §3.

**18. Combien ça coûte ?**
Ce sont des estimations, pas des devis. Matériel par chambre : environ 280 EUR, soit un peu moins de 1 000 TND hors importation. Serveur : de l'ordre d'un euro par lit et par mois une fois amorti.
Le poste à surveiller est l'API du LLM : avec nos hypothèses (22 appels par lit et par jour), une soixantaine de dinars par lit et par mois — réductible, et nul en mode sans LLM.
Prix visé à tester : 150 à 250 TND par lit et par mois.
→ `docs/DEPLOIEMENT.md` §2 (hypothèses et calculs détaillés).

---

## Positionnement, réglementation, bilan

**19. En quoi êtes-vous différents des systèmes de surveillance existants ?**
Nous ne prétendons pas remplacer un moniteur certifié. Un moniteur classique alerte sur une constante. Nous ajoutons trois choses : le **contexte** (posture, sortie du lit, présence d'un soignant, ambiance, dossier) ; la **boucle fermée** (une alerte n'est close qu'après passage d'un soignant et revérification de l'état réel) ; et la **rédaction** (plan, compte rendu, rapport de garde).
Le tout avec du matériel grand public et sans sortir d'image de la chambre.
Nous n'avons pas fait de comparaison chiffrée avec des produits du marché.
→ `docs/ARCHITECTURE.md` §2 (a), `dashboard/app/agents/followup.py`.

**20. Quel est le chemin réglementaire avant de l'utiliser sur de vrais patients ?**
Aujourd'hui c'est un prototype avec des données fictives, pas un dispositif médical.
Avant un usage réel : formalités auprès de l'INPDP pour des données de santé et pour le transfert à l'étranger ; accord d'hébergement ; analyse d'impact ; validation clinique des seuils et des scores ; et la démarche de dispositif médical, dont la classification est à arrêter avec un spécialiste.
Notre feuille de route commence par un pilote en mode observation, en parallèle des pratiques habituelles.
→ `docs/CONFORMITE.md` §3, `docs/DEPLOIEMENT.md` §4.

---

## Deux questions bonus

**Qu'est-ce qui a été le plus difficile ?**
Trois choses, toutes dans `DECISIONS.md`. Faire tenir la démo sans dépendre de rien : chaque brique a son repli (broker, n8n, LLM, matériel). Un blocage de 55 secondes au premier risque, causé par l'import du SDK du LLM dans la boucle asyncio (13:30). Et les fausses alertes : dès qu'un risque clinique ne se ferme plus seul, le moindre bruit du simulateur reste affiché — il a fallu ramener le bruit à des valeurs de moniteur réel sans toucher aux seuils cliniques (00:55).
Sans oublier l'intégration continue du travail d'Amal sans casser sa 3D (`AMAL_SYNC.md`).

**Quelle est la suite ?**
À 3 mois : essais sur de vrais Pi avec mesures, sécurité activée et testée, base de données serveur, chambres configurables, premier échange avec l'INPDP et revue des seuils par des cliniciens.
À 6 mois : pilote de 5 à 10 lits en mode observation, mesure des fausses alertes et des biais, coût réel du LLM, classification réglementaire.
→ `docs/DEPLOIEMENT.md` §4.

---

## Aide-mémoire : les chiffres que vous avez le droit de citer

| Chiffre | Source |
|---|---|
| 13 agents | `dashboard/app/agents/manager.py` (`AGENT_CLASSES`) |
| 15 workflows n8n | `n8n/workflows/` |
| 7 rôles | `dashboard/app/auth.py` (`ROLES`) |
| 4 chambres | `dashboard/app/ingest/handler.py` (`ROOMS`) |
| 32 fichiers de scénario, dont 17 de résolution | `simulator/scenarios/` |
| 263 tests verts à la fin de la V3 (LLM en mock, n8n coupé) | `MORNING_REPORT.md`, section V3 |
| Escalade sans visite : 2 min (critique), 10 min (élevé), 30 min (moyen) | `dashboard/app/config.py` |
| Environ 50 appels au LLM pour un passage complet de `full_demo_v2` | `BLOCKERS.md` |
| Vision, modèle à deux classes, jeu de test : précision 0,92, rappel 0,93 | `computer_vision/reports/evaluation_report.md` |

Chiffres à **ne pas** citer comme des faits : nombre de chambres par serveur, cadence sur Raspberry Pi, taux de fausses alertes, réduction des chutes, consommation réelle du LLM — rien de tout cela n'a été mesuré.
