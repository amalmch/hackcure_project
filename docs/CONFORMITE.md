# Conformité — Hospital Copilot (HackCure)

> **État réel à la fin de la nuit (11/10)** — les mécanismes V3 décrits ci-dessous sont tous dans le dépôt et couverts par des tests
> automatiques. Ce qui a été lancé en conditions réelles et ce qui ne l'a pas été est dans `MORNING_REPORT.md`, section V3
> (tableau « Vérifié / non vérifié »). En résumé : HTTPS TLS 1.3, chiffrement AES-256-GCM, HMAC des trames, FHIR, pseudonymisation et
> SADM ont tourné ensemble sur un serveur de test ; **Docker n'a pas pu être exécuté**, MQTT sur TLS et un vrai Raspberry Pi **n'ont pas été testés**.

*Rédaction initiale : en parallèle du développement ; les lignes « activable » décrivent des fonctions désormais présentes, à activer par `.env`.*

Les fonctions marquées « activable » sont celles de la V3, développées en parallèle de ce document. Elles sont décrites ici **telles que conçues**, pas telles que testées. Avant de répondre au jury sur l'une d'elles, ouvrez `PROGRESS_V3.md` et vérifiez que la case est cochée.

Avertissement à répéter : Hospital Copilot est un **prototype de hackathon avec des données fictives**. Ce n'est pas un dispositif médical certifié. Rien dans ce document ne vaut avis juridique ; les points de droit incertains sont marqués « à confirmer avec un juriste ».

Statuts utilisés :

| Statut | Sens |
|---|---|
| **en place** | présent dans le code et vérifié par des tests ou un passage réel (`MORNING_REPORT.md`) |
| **activable** | conçu pour la V3, mis en route par une variable de `.env` ; état réel dans `PROGRESS_V3.md` |
| **simulé** | le mécanisme existe, mais la donnée ou le matériel est simulé |
| **non couvert** | absent |

Note sur la numérotation : nous n'avons pas le texte officiel du cahier des charges dans le dépôt. Les sections 4, 5 et 6 sont reconstruites par thème à partir de `PROMPT.md` et de la liste des travaux V3. **La correspondance exacte des numéros est à vérifier** contre le document officiel avant le jury.

---

## 1. Tableau de conformité point par point

### Section 4 — Sécurité et confidentialité

| Exigence | Comment elle est couverte | Où | Statut |
|---|---|---|---|
| Authentification | Identifiant + mot de passe haché par bcrypt ; session par jeton JWT (HS256) dans un cookie HttpOnly ; durée `JWT_EXPIRE_MINUTES` | `dashboard/app/auth.py` (`hash_password`, `create_token`), `dashboard/app/api/auth.py` | en place |
| Contrôle d'accès par rôle | 7 rôles ; table `PERMISSIONS` ; chaque route protégée par une dépendance `require("permission")` côté serveur ; interface filtrée par `/api/auth/me` | `dashboard/app/auth.py` ; tests `dashboard/tests/test_auth.py` | en place |
| Accès restreint au dossier médical | Vue complète pour médecins et psychiatre, lecture pour infirmiers, identité et admissions pour la réception, allergies et traitements pour le pharmacien ; 403 hors périmètre | `dashboard/app/api/dossier.py` (`scope_of`) | en place |
| Réponses psychologiques protégées | Les infirmiers voient le niveau et les consignes, pas les réponses (`view_psych_answers`) | `dashboard/app/auth.py`, `dashboard/app/api/psych.py` | en place |
| Journalisation des modifications | `audit(session, user, action, entity, id, details)` sur toute création, modification, signature, commande, connexion | `dashboard/app/audit.py`, table `AuditLog` (`models.py`) | en place |
| Journalisation des consultations du dossier | Chaque lecture et chaque impression du dossier écrit une ligne d'audit | `dashboard/app/api/dossier.py` (`audit_read`), `dashboard/app/api/print.py` | en place |
| Non-répudiation (qui, quand, quoi, IP) | `AuditLog` enrichi de l'adresse IP pour : consultation du dossier, signature d'ordonnance, validation ou rejet d'une recommandation d'IA | `dashboard/app/models.py`, `dashboard/app/audit.py` | activable — au moment de la rédaction, `AuditLog` contient utilisateur, rôle, action, entité, détails, date, **pas encore l'IP** |
| Pseudonymisation (Privacy by Design) | Tout ce qui **sort** de la plateforme (prompts LLM, webhooks n8n, Telegram, journaux) n'utilise que le pseudonyme `PAT-0001`, la chambre, l'âge, le sexe et les données cliniques — jamais le nom, le prénom ni la date de naissance complète | interrupteur `PSEUDONYMIZE_OUTBOUND` (activé par défaut) ; le pseudonyme est le champ `Patient.code` (`models.py`) | activable — **attention** : dans le code V2, les notifications et le contexte LLM contiennent encore le nom complet (`agents/risk.py`, `notify_for` ; `agents/care.py`, `send`) |
| Identité visible selon le rôle | Dans l'interface, l'identité complète n'est visible que des rôles ayant `view_identity` (réceptionniste, infirmier, médecins, psychiatre, propriétaire) ; les autres voient le pseudonyme | `dashboard/app/auth.py` (permission déjà déclarée) | activable — la permission existe, son application dans les vues est à vérifier dans `PROGRESS_V3.md` |
| Chiffrement en transit — web | `HTTPS=true` démarre uvicorn en TLS, version minimale TLS 1.3, certificat auto-signé généré par `scripts/make-cert.ps1` / `.sh` | `dashboard/serve.py` ; `dashboard/healthcheck.py` gère déjà le cas HTTPS | activable |
| Chiffrement en transit — accès distant | Tunnel Cloudflare (`cloudflared tunnel --url http://localhost:8000`), déjà utilisé pour la page GPS de l'ambulance | `docs/ambulance.md` | en place (documenté) |
| Chiffrement en transit — IoT | MQTT sur TLS, port 8883, pour le Pi si configuré | `docker/mosquitto.conf` | activable — le fichier du dépôt n'ouvre que le port 1883, en anonyme : **à configurer** avant tout usage réel |
| Chiffrement au repos | Chiffrement applicatif AES-256-GCM (bibliothèque Python `cryptography`) des champs sensibles : identité du patient, contenu des documents du dossier, réponses aux questionnaires ; clé `DATA_ENCRYPTION_KEY` générée par un script | couche entre `models.py` et la base | activable — sans clé, la plateforme démarre **en clair avec un avertissement visible** (mode démo) |
| Secrets hors du code | `.env` non commité ; les JSON de `n8n/workflows/` ne contiennent aucun secret (jetons `__CRED_*__` remplacés à l'import) | `.env.example`, `n8n/setup_n8n.py` | en place |
| Échanges plateforme ↔ n8n authentifiés | Un secret par sens : `X-Hospital-Secret` vers n8n, `Authorization: Bearer PLATFORM_SERVICE_TOKEN` au retour | `dashboard/app/n8n.py` (`headers`), `dashboard/app/auth.py` (`service_user_from_token`) | en place |
| Journaux sans secret | `httpx` limité à WARNING pour ne pas écrire l'URL Telegram (jeton) | `dashboard/app/main.py` | en place |
| Vie privée de la caméra | Aucune image n'est envoyée ni stockée : l'edge publie des états JSON ; aperçu optionnel basse résolution **flouté**, relayé sans stockage, réservé aux rôles cliniques | `edge/main.py` (`MjpegServer`), `dashboard/app/api/camera.py` | en place côté code ; non testé sur un vrai Pi |
| Liens publics limités | Page tablette et page GPS protégées par un jeton aléatoire par questionnaire ou par mission ; le questionnaire est à usage unique et n'affiche que le prénom | `dashboard/app/api/psych.py`, `dashboard/app/api/ambulances.py` | en place |

Limites connues à reconnaître :

- `POST /api/ingest` n'exige une clé que si `INGEST_API_KEY` est défini (`dashboard/app/api/ingest.py`) ; par défaut il est ouvert. L'intégrité HMAC de la V3 répond à ce point.
- Les routes de démonstration d'origine (`/api/demo/trigger`, `/api/yolo/event`) restent ouvertes en mode démo (`PROMPT.md` §11).
- `JWT_SECRET` et `DEMO_PASSWORD` ont des valeurs de démonstration : à changer.
- Pas de double authentification, pas de verrouillage de compte après échecs, pas de politique de mot de passe : **non couvert**.

### Section 5 — Interopérabilité et aide à la décision clinique (SADM)

| Exigence | Comment elle est couverte | Où | Statut |
|---|---|---|---|
| API de lecture HL7 FHIR R4 | `/fhir/Patient/{id}`, `/fhir/Observation?patient=`, `/fhir/Condition`, `/fhir/AllergyIntolerance`, `/fhir/MedicationRequest`, `/fhir/Encounter`, `/fhir/Patient/{id}/$everything` (Bundle) | routeur `api/fhir` (déjà déclaré dans `dashboard/app/main.py`), `docs/interoperabilite.md` | activable (`FHIR_ENABLED`) |
| Codes standard | LOINC : fréquence cardiaque 8867-4, SpO2, pression artérielle 85354-9 avec composants 8480-6 / 8462-4, température 8310-5, fréquence respiratoire 9279-1, glycémie | idem | activable — codes SpO2 et glycémie à vérifier dans `docs/interoperabilite.md` |
| Identifiants pseudonymisés dans FHIR | Les ressources portent le pseudonyme, pas l'identité | idem | activable |
| Export | Bouton « Exporter en FHIR » | `dashboard/static/js/v3/fhir-export.js` | activable — fichier vide au moment de la rédaction |
| Écriture FHIR, HL7 v2, DICOM | — | — | non couvert (lecture seule) |
| Contrats de messages documentés | Un JSON Schema par message, validé à l'entrée | `contracts/mqtt-topics.md`, `contracts/schemas/`, `dashboard/app/contracts.py` | en place |
| Décision déterministe et explicable | Détection et sévérité par règles Python ; chaque risque garde les valeurs observées et la règle appliquée dans le journal des agents (entrée → raisonnement → sortie) | `dashboard/app/agents/plans.py` (`severity_for`), `agents/base.py` (`Agent.log`) | en place |
| Scores cliniques reconnus | NEWS2 (échelle 2 pour BPCO), qSOFA, PHQ-9, GAD-7 | `dashboard/app/clinical/news2.py`, `fever.py`, `psych.py` | en place (implémentation non validée cliniquement) |
| Indice de confiance mesurable, avec sa méthode | Chaque recommandation affiche un indice de confiance et la façon dont il est calculé | `dashboard/static/js/v3/sadm.js`, routeur `api/sadm` | activable — existant en V2 : confiance des prédictions = quantité de données (`clinical/prediction.py`, `_result`), probabilité qualitative des hypothèses (`clinical/diagnostics.py`, `probability`) |
| Paramètres cliniques déclencheurs affichés | Facteurs de chaque score listés par ordre de poids | `clinical/prediction.py`, `clinical/psych.py`, `clinical/diagnostics.py` | en place pour prédictions, psychologie, diagnostics ; généralisation à toutes les recommandations : activable |
| Humain dans la boucle | Boutons Valider / Rejeter tracés dans `AuditLog` ; bandeau permanent « Recommandation consultative — la décision et la signature restent celles du médecin » | V3 : `sadm.js` | activable — existant en V2 : validation du bilan biologique par le médecin, confirmation ou rejet des hypothèses (`api/care.py`, `decide`), signature des ordonnances et comptes rendus, mention « Aide à la décision — validation médicale requise » (`orchestration.py`, `DISCLAIMER`) |
| Le LLM ne décide pas | Il ne fixe pas la sévérité, ne clôt pas un risque seul, ne coche pas un examen, ne réécrit pas une dose | `DECISIONS.md` (14:20, 19:55, 21:58), `n8n/README.md` §4 | en place |
| Sécurité du médicament | Alerte d'allergie bloquante à la signature (sauf confirmation tracée), interactions simples | `dashboard/app/api/care.py` (`_check`, `sign_order`), `api/prescriptions.py` (`sign_prescription`) | en place (table d'interactions simplifiée) |
| Contrôle des biais | Note dans `docs/` | à vérifier dans `PROGRESS_V3.md` | activable — voir aussi `docs/QA_JURY.md`, question 7 |
| Validation clinique des règles | — | — | non couvert (prototype) |

### Section 6 — Ergonomie, déploiement, intégrité IoT, conteneurisation

| Exigence | Comment elle est couverte | Où | Statut |
|---|---|---|---|
| Valider une alerte et signer une ordonnance en 3 actions au plus depuis la notification | Parcours décrit et compté | `docs/ergonomie.md` | activable — à vérifier dans `PROGRESS_V3.md` |
| Interface en français, par rôle | Navigation filtrée selon les permissions ; libellés français | `dashboard/static/js/nav.js`, `auth.js` | en place — quelques chaînes internes de `dashboard-ui.js` restent en anglais (`MORNING_REPORT.md` §3) |
| Lisibilité des alertes | Couleur de la chambre selon le risque maximal, cloche, toasts, bandeau KPI, journal des agents | `js/room-live.js`, `js/notifications.js`, `js/kpi-bar.js`, `js/agents-panel.js` | en place |
| Documents imprimables | Ordonnance, rapport médecin, rapport de garde, documents du dossier (A4) | `dashboard/app/api/print.py`, `dashboard/templates/print/` | en place |
| Intégrité des trames IoT | Chaque message edge ou simulateur porte `seq`, `ts` et `sig` = HMAC-SHA256 (clé partagée `EDGE_HMAC_KEY`) calculé sur `topic + "\n" + JSON canonique de la charge utile sans sig` | `docs/integrite-trames.md`, routeur `api/integrity` | activable |
| Rejet des trames invalides | Le backend rejette les trames à signature invalide, rejouées (séquence déjà vue) ou vieilles de plus de 30 s ; il les compte | idem | activable — sans clé : trames acceptées avec avertissement (mode démo) |
| Indicateur visible | « Intégrité des trames » sur la page Machines | `dashboard/static/js/v3/frame-integrity.js` | activable — fichier vide au moment de la rédaction |
| Validation de format des trames | JSON Schema, rejet 422, compteur `rejected` | `dashboard/app/contracts.py`, `ingest/handler.py`, `GET /api/ingest/stats` | en place |
| Continuité hors réseau | Règles locales sur l'edge (buzzer, veilleuse, climat), file hors ligne des messages importants, repli HTTP | `edge/safety/local_rules.py`, `edge/transport/__init__.py` | en place en `--fake` ; non testé sur un vrai Pi |
| Continuité si n8n ou le LLM tombe | Repli local, puis réponse de secours déterministe, affichés dans l'interface | `dashboard/app/orchestration.py`, `agents/risk.py` | en place (vécu : crédit d'API épuisé, `BLOCKERS.md`) |
| Environnement conteneurisé autonome | `Dockerfile` : Python 3.11 slim, utilisateur non-root, `HEALTHCHECK` sur `/health` | `Dockerfile`, `dashboard/healthcheck.py` | activable — **image non construite** : Docker Desktop n'était pas lancé sur la machine de développement |
| Composition des services | `docker-compose.yml` : services `platform` et `mosquitto`, profil `n8n`, profil `mssql` ; volumes `hackcure-data` (base SQLite) et `n8n-data` ; `.env` de l'hôte lu par `env_file` ; `restart: unless-stopped` | `docker-compose.yml`, `scripts/run-docker.ps1` / `.sh` | activable — validé par `docker compose config` seulement |
| Lancement en une commande hors Docker | `scripts/run-demo.ps1 -Reset` / `run-demo.sh --reset` | `scripts/`, `MORNING_REPORT.md` | en place |
| Supervision | `GET /health` : état LLM, MQTT, n8n, Telegram | `dashboard/app/main.py` (`health`) | en place |
| Étude de déploiement et modèle économique | Livrable L3 | `docs/DEPLOIEMENT.md` | en place (estimations) |
| Matériel réel | Raspberry Pi 5, caméra, MLX90640, DHT22, GPIO : pilotes écrits, simulation automatique si absents | `edge/` | simulé — aucun test sur matériel réel documenté |
| Appareils médicaux | Oxymètre, ECG, tensiomètre, thermomètre, glucomètre, pompes | `simulator/engine.py` | simulé |

---

## 2. Protection des données : RGPD et INPDP (Tunisie)

Cadre : en Tunisie, la **loi organique n° 2004-63 du 27 juillet 2004** sur la protection des données à caractère personnel, appliquée par l'**INPDP** (Instance Nationale de Protection des Données Personnelles). Les **données de santé sont des données sensibles**. Le RGPD européen sert ici de référence de bonnes pratiques ; il ne s'applique directement que si le traitement concerne des personnes dans l'Union européenne (à confirmer avec un juriste).

État réel aujourd'hui : **aucune donnée personnelle réelle n'est traitée**. Identités, historiques, biologie et imagerie sont générés par `dashboard/app/medical_history.py` et `dashboard/app/seed.py`. Ce qui suit décrit ce que le système prévoit et ce qu'il faudrait faire avant un usage réel.

### 2.1 Base légale et finalité

- Finalité : surveillance et sécurité des patients hospitalisés, coordination des soins, tenue du dossier.
- Base envisagée : la prise en charge médicale par un établissement de santé et ses professionnels soumis au secret médical. Le traitement de données de santé est soumis à un régime particulier dans la loi de 2004 (formalités auprès de l'INPDP, rôle du médecin) — **articles et procédure exacts à confirmer avec un juriste**.
- La caméra en chambre et le questionnaire psychologique demandent une **information claire du patient** et, très probablement, son **consentement** exprès — à confirmer avec un juriste. Dans le prototype, le questionnaire est facultatif et proposé sur tablette.

### 2.2 Minimisation

| Mesure | Où |
|---|---|
| Aucune image ne quitte la chambre ; seuls des états (`posture`, `activity`, `zone`) sont transmis | `edge/main.py`, `contracts/mqtt-topics.md` |
| Aucune image stockée côté serveur ; aperçu flouté relayé sans enregistrement | `dashboard/app/api/camera.py` |
| Mesures sous-échantillonnées en base (1 valeur toutes les 10 s), détail à la seconde gardé 15 min en mémoire | `dashboard/app/ingest/handler.py` (`_store_vitals_sampled`, `HISTORY_LEN`) |
| Le LLM ne reçoit pas tout le dossier : un extrait déterministe | `dashboard/app/api/dossier.py` (`summary_context`) |
| Chaque rôle ne voit que son périmètre | `dashboard/app/auth.py`, `api/dossier.py` (`scope_of`) |

### 2.3 Pseudonymisation et chiffrement

- Pseudonymisation des flux sortants : `PSEUDONYMIZE_OUTBOUND` (**activable**, activée par défaut dans la conception). Le pseudonyme `PAT-0001` existe déjà (`Patient.code`). Attention : une donnée pseudonymisée reste une donnée personnelle ; l'âge, le sexe et le tableau clinique peuvent permettre une ré-identification dans un petit service.
- Chiffrement en transit : TLS 1.3 (`HTTPS=true`), tunnel Cloudflare, MQTT sur TLS 8883 — **activable**.
- Chiffrement au repos : AES-256-GCM sur les champs sensibles (`DATA_ENCRYPTION_KEY`) — **activable**. À prévoir avant usage réel : stockage de la clé hors du serveur applicatif, rotation, sauvegardes chiffrées — **non couvert**.

### 2.4 Durées de conservation — PROPOSITIONS

Aucune durée n'est codée dans le prototype (pas de purge automatique : **non couvert**). Les valeurs ci-dessous sont des **propositions de l'équipe**, à valider avec la direction de l'établissement et un juriste ; la durée légale de conservation du dossier médical en Tunisie est **à confirmer**.

| Donnée | Proposition | Raison |
|---|---|---|
| Images de la caméra | 0 (jamais stockées) | minimisation |
| États de posture (`PatientStateSnapshot`) | 30 jours après la sortie | utiles au rapport de garde et à l'analyse d'un incident |
| Constantes sous-échantillonnées (`VitalReading`) | durée du séjour + 1 an, puis agrégation | suivi et réclamations |
| Journal des agents (`AgentLog`) | 1 an | explication d'une alerte |
| Journal d'audit (`AuditLog`) | 5 ans, en ajout seul | non-répudiation |
| Documents du dossier médical, ordonnances | durée légale du dossier médical (à confirmer) | obligation de l'établissement |
| Réponses aux questionnaires psychologiques | durée du séjour + 1 an, sauf versement au dossier | données très sensibles |
| Positions GPS d'une mission d'ambulance | 30 jours | trace de l'intervention |
| Messages Telegram | à purger côté messagerie ; contenu pseudonymisé | service externe |

### 2.5 Droits des patients

| Droit | Dans le prototype | Avant usage réel |
|---|---|---|
| Information | mention « données fictives » ; pas de notice patient | notice d'information en chambre et à l'admission, affichage de la présence d'une caméra |
| Accès | le dossier est imprimable par un soignant (`api/print.py`) ; export FHIR `$everything` (activable) | procédure de demande, délai de réponse |
| Rectification | les soignants habilités modifient la fiche et les documents, avec trace d'audit (`api/patients.py`, `api/dossier.py`) | circuit de demande du patient |
| Opposition | il suffit de ne pas lancer l'edge dans la chambre (la caméra thermique seule se coupe par `thermal.enabled: false` dans `edge/config/room101.yaml`) ; questionnaire facultatif | recueil et trace du refus ; mode de surveillance sans caméra |
| Effacement | `DELETE /api/patients/{id}` existe (`api/patients.py`) | **limite** : le dossier médical doit être conservé pendant la durée légale ; l'effacement ne peut porter que sur ce qui n'est pas soumis à cette obligation — à confirmer avec un juriste |
| Portabilité | export FHIR (activable) | — |

### 2.6 Journalisation

`AuditLog` trace qui (utilisateur, rôle), quand, quoi (action, entité, identifiant, détails) : connexions, modifications, signatures, commandes d'équipement, lectures et impressions du dossier. La V3 ajoute l'adresse IP et la trace de la validation ou du rejet des recommandations d'IA. Limite : le journal est dans la même base que les données ; il n'est ni signé ni exporté vers un stockage en ajout seul — **non couvert**.

### 2.7 Hébergement et sous-traitants

| Composant | Où il tourne | Données reçues |
|---|---|---|
| Plateforme, base de données, simulateur | serveur **de la clinique** (ou conteneur Docker sur ce serveur) | toutes |
| Raspberry Pi (edge) | dans la chambre | images traitées en mémoire, jamais envoyées |
| Mosquitto | serveur de la clinique | messages de capteurs |
| n8n | **auto-hébergé** sur le serveur de la clinique (`npx n8n` ou profil Docker `n8n`) | contexte des alertes — pseudonymisé si `PSEUDONYMIZE_OUTBOUND` |
| API du LLM (Anthropic) | **service externe, à l'étranger** | prompts — pseudonymisés si `PSEUDONYMIZE_OUTBOUND` |
| Telegram | **service externe, à l'étranger** | textes des notifications — pseudonymisés si `PSEUDONYMIZE_OUTBOUND` |
| CDN (Three.js, Chart.js, Leaflet) et tuiles OpenStreetMap | services externes | aucune donnée patient ; l'adresse IP du navigateur est visible par ces services |

Avant usage réel : l'hébergement de données de santé peut exiger un hébergeur agréé ou une autorisation — **à confirmer avec un juriste** ; contrats de sous-traitance avec chaque service externe ; remplacement de Telegram par une messagerie professionnelle maîtrisée ; bibliothèques JavaScript servies localement.

### 2.8 Transfert hors de Tunisie

L'API du LLM et Telegram sont hébergés à l'étranger : c'est un **transfert de données hors de Tunisie**, que la loi de 2004 encadre (autorisation de l'INPDP — à confirmer avec un juriste). Réponses du prototype :

1. pseudonymisation de tout ce qui sort (`PSEUDONYMIZE_OUTBOUND`) ;
2. possibilité de **ne rien envoyer** : `LLM_PROVIDER=mock` (réponses déterministes locales), `N8N_ENABLED=false`, Telegram désactivé si `TELEGRAM_BOT_TOKEN` est vide (`dashboard/app/config.py`). La détection, la sévérité et la vérification ne dépendent pas du LLM : le système reste utile sans aucun transfert ;
3. architecture prête pour un autre fournisseur : la classe `BaseLlm` (`dashboard/app/agents/llm.py`) isole le fournisseur ; un modèle hébergé localement demanderait une nouvelle sous-classe — **non fait**.

### 2.9 Analyse d'impact

Une analyse d'impact sur la protection des données est **à faire avant tout usage réel** : traitement à grande échelle de données de santé, vidéo-surveillance de personnes vulnérables, profilage (scores de risque, bien-être psychologique), transfert à l'étranger. Elle n'a **pas été réalisée** (prototype). Risques à y traiter en priorité : ré-identification malgré le pseudonyme, accès illégitime à l'aperçu caméra, fuite par les notifications, décision clinique influencée par un score non validé.

---

## 3. Ce qui est exigé avant un déploiement réel

Le prototype ne peut pas être utilisé sur de vrais patients en l'état. Liste minimale :

1. **Formalités INPDP** : déclaration ou autorisation du traitement de données de santé, autorisation de transfert à l'étranger si un LLM externe est conservé (à confirmer avec un juriste).
2. **Hébergement** : accord d'hébergement de données de santé conforme au droit tunisien ; sauvegardes chiffrées ; plan de reprise.
3. **Validation clinique** : les seuils, les scores de prédiction, le score de bien-être et le questionnaire de sommeil ne sont **pas validés** ; il faut une étude avec des cliniciens, sur des données réelles, avec mesure des faux positifs et des faux négatifs.
4. **Réglementation des dispositifs médicaux** : un logiciel qui alerte sur l'état d'un patient relève très probablement de la réglementation des dispositifs médicaux (en Tunisie, autorité compétente du ministère de la Santé ; marquage CE selon le règlement européen 2017/745 pour l'Europe) — classification et démarche **à confirmer** avec un spécialiste réglementaire. Normes habituellement attendues : gestion de la qualité (ISO 13485), gestion des risques (ISO 14971), cycle de vie du logiciel médical (IEC 62304).
5. **Sécurité** : test d'intrusion, secrets de production, MQTT authentifié et chiffré, double authentification, journal d'audit inaltérable, base de données serveur (PostgreSQL ou SQL Server) à la place de SQLite.
6. **Matériel** : essais sur de vrais Raspberry Pi, calibration de la caméra thermique, sécurité électrique des boîtiers en milieu de soins.
7. **Organisation** : formation des équipes, procédure en cas de panne, désignation d'un responsable de la protection des données, information et consentement des patients.
8. **Éthique** : avis du comité d'éthique de l'établissement sur la caméra en chambre et sur l'évaluation psychologique automatisée.
