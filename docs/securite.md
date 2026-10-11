# Sécurité : chiffrement en transit, chiffrement au repos, non-répudiation

Chaque mécanisme a un **interrupteur dans `.env`**. Si la clé ou le certificat manque, **la plateforme démarre quand même** et le dit :
avertissement au démarrage (« SÉCURITÉ — … ») et dans `GET /health` (champ `security.warnings`).

| Mécanisme | Interrupteur | Par défaut | Sans configuration |
|---|---|---|---|
| HTTPS (TLS 1.3 minimum) | `HTTPS=true` | désactivé | HTTP en clair + avertissement |
| MQTT sur TLS (Pi → broker) | `MQTT_TLS=1`, port 8883 | désactivé | MQTT en clair (ou repli HTTP) |
| Chiffrement au repos AES-256-GCM | `DATA_ENCRYPTION_KEY` | absent | données en clair + avertissement |
| Intégrité des trames HMAC-SHA256 | `EDGE_HMAC_KEY` | absent | trames acceptées + avertissement (voir `integrite-trames.md`) |
| Pseudonymisation des sorties | `PSEUDONYMIZE_OUTBOUND` | **activé** | — |
| Journal d'audit avec IP | toujours actif | **activé** | — |

Tout activer pour la démonstration :

```powershell
.\scripts\make-key.ps1 --write        # écrit DATA_ENCRYPTION_KEY et EDGE_HMAC_KEY dans .env (ne remplace jamais une clé existante)
.\scripts\make-cert.ps1               # dashboard/certs/server.crt + server.key (auto-signé, 1 an)
# dans .env : HTTPS=true
.\scripts\run-demo.ps1                # → https://localhost:8000 (accepter l'avertissement du navigateur une fois)
```
Linux / macOS : `./scripts/make-key.sh --write`, `./scripts/make-cert.sh`.

## 1. Chiffrement en transit

### HTTPS avec TLS 1.3 minimum
- `HTTPS=true` : `dashboard/serve.py` lance uvicorn avec un contexte SSL dont `minimum_version = TLSv1_3` (`tls13_context`). Un client
  qui ne propose que TLS 1.2 est refusé à la poignée de main (testé par une vraie connexion dans `test_v3_security.py`).
- Certificat : `TLS_CERT_FILE` / `TLS_KEY_FILE`, sinon `dashboard/certs/server.crt` et `server.key`. S'ils manquent, ils sont
  générés automatiquement (auto-signés, courbe P-256, SHA-256, valables 1 an, pour `localhost`, `127.0.0.1`, le nom de la machine et
  les `--host` donnés à `scripts/make-cert`). Si la génération est impossible : démarrage en HTTP avec un avertissement.
- Le certificat est **auto-signé** : le navigateur affiche un avertissement. En production, utiliser un certificat d'une autorité
  reconnue, ou le tunnel ci-dessous.
- Dans Docker : `HTTPS=true` dans `.env` ; les certificats sont dans le volume (`TLS_CERT_DIR=/data/certs`) ; la sonde de santé
  interroge alors `https://127.0.0.1:8000/health`.
- n8n appelle la plateforme par `PLATFORM_URL` : avec HTTPS auto-signé, garder n8n sur le même hôte en HTTP interne, ou lui faire
  confiance au certificat. **Non testé avec n8n en HTTPS.**

### Tunnel Cloudflare (déjà utilisé pour le GPS de l'ambulance)
`cloudflared tunnel --url http://localhost:8000` donne une adresse `https://….trycloudflare.com` avec un certificat reconnu : le
trajet navigateur ↔ Cloudflare est en TLS, sans rien installer sur le poste client. C'est ce qui permet la géolocalisation du téléphone
de l'ambulancier (`docs/ambulance.md`). Le tronçon Cloudflare ↔ serveur est local à la machine. Derrière le tunnel, l'adresse d'origine
du client est lue dans l'en-tête `X-Forwarded-For` pour le journal d'audit.

### MQTT sur TLS (Raspberry Pi → broker)
- Broker : exemple `docker/mosquitto-tls.conf` (écoute 8883, `tls_version tlsv1.3`).
- Plateforme : `MQTT_TLS=1`, `MQTT_PORT=8883`, `MQTT_CA_FILE=dashboard/certs/server.crt`.
- Pi : dans `edge/config/room101.yaml`, `mqtt.tls: true`, `mqtt.port: 8883`, `mqtt.ca_file`.
- **Non testé** contre un broker réel (pas de broker sur la machine de développement) : le code de connexion est en place, à valider.
- Le repli HTTP de l'edge (`POST /api/ingest`) profite directement de `HTTPS=true`.

## 2. Chiffrement au repos (AES-256-GCM)

- **Quoi** : `Patient.first_name`, `Patient.last_name` (identité), `MedicalRecordEntry.content` (documents du dossier médical),
  `PsychQuestionnaire.answers_json` (réponses aux questionnaires). Module `dashboard/app/crypto.py`.
- **Comment** : chiffrement applicatif avec la bibliothèque `cryptography` (AES-GCM, clé de 256 bits, nonce aléatoire de 96 bits par
  valeur, étiquette d'authentification de 128 bits). Valeur stockée : `enc:v1:` + base64(nonce + chiffré + étiquette). Le type de
  colonne `EncryptedStr` chiffre à l'écriture et déchiffre à la lecture : le reste du code ne voit que du texte clair.
- **Clé** : `DATA_ENCRYPTION_KEY` dans `.env` (32 octets en base64), générée par `scripts/make-key`. Jamais commitée.
  **La sauvegarder hors du serveur : sans elle, les champs chiffrés sont perdus.**
- **Migration transparente** : au démarrage avec une clé, les valeurs encore en clair (données de démonstration, base antérieure)
  sont chiffrées (`crypto.migrate`). L'opération est idempotente.
- **Sans clé** : fonctionnement en clair, avertissement. **Base chiffrée + clé absente ou fausse** : les champs s'affichent
  « 🔒 chiffré », rien n'est écrasé ; remettre la bonne clé suffit.
- **Intégrité** : une valeur modifiée directement en base est détectée (étiquette GCM invalide) et affichée « 🔒 chiffré ».
- **Recherche** : le contenu chiffré ne peut plus être filtré en SQL ; la recherche plein texte du dossier déchiffre en mémoire les
  documents du patient (une centaine) puis filtre.

Limites assumées :
- la **date de naissance** n'est pas chiffrée (colonne de type date, utilisée pour l'âge) ; les titres et résumés des documents, les
  allergies, les antécédents et les constantes non plus (ils servent aux règles et aux recherches) ;
- pas de rotation de clé automatique ; la clé est dans `.env`, pas dans un coffre-fort matériel ;
- pour chiffrer **tout** le fichier de base : chiffrement du disque (BitLocker, LUKS) ou SQLCipher — complémentaire, non fourni ;
- revenir en arrière (enlever la clé) ne déchiffre pas la base : il faut la clé pour relire.

## 3. Non-répudiation : journal d'audit

`AuditLog` (`dashboard/app/models.py`) : **qui** (`user`, `role`), **quand** (`ts`), **quoi** (`action`, `entity`, `entity_id`,
`details`), **d'où** (`ip`, ajoutée en V3 — renseignée automatiquement par `ClientIpMiddleware`, sans modifier les appelants).

| Événement | `action` / `entity` |
|---|---|
| Consultation du dossier médical (liste, document, profil, biologie) | lecture tracée par `audit_read` dans `api/dossier.py` |
| Lecture par l'API FHIR | `fhir_read` (refus : `fhir_denied`) |
| Création, modification, signature d'une ordonnance | `create` / `update` / `sign` sur `prescription` |
| Signature d'une ordonnance de traitement, administration d'une prise | `api/care.py` |
| Validation ou rejet d'une recommandation de l'IA | `ai_validate` / `ai_reject` sur `recommendation:<type>` (motif, indice de confiance, déclencheurs) |
| Décision sur une hypothèse diagnostique, validation du bilan biologique | `api/care.py`, `api/fever.py` |
| Commandes d'équipement, résolutions de risque, connexions | déjà tracés en V1 / V2 |

Limites : le journal est dans la même base que les données (un administrateur de la base peut le modifier) ; il n'est ni signé ni
chaîné, ni exporté vers un système externe. Avec un compte partagé, « qui » désigne le compte, pas la personne. Pour une vraie
non-répudiation : comptes nominatifs, authentification forte, journal en ajout seul exporté hors du serveur.

## 4. Ce qui a été vérifié

`dashboard/tests/test_v3_security.py` (7 tests) : aller-retour AES-256-GCM, détection d'une donnée altérée, démarrage sans clé ou avec
une clé invalide, contenu réellement chiffré dans le fichier SQLite, migration d'une base en clair, recherche dans un contenu chiffré,
certificat auto-signé, poignée de main TLS 1.3 acceptée et TLS 1.2 refusée, démarrage quand le certificat ne peut pas être créé,
journal d'audit avec IP (consultation du dossier, signature d'ordonnance, `X-Forwarded-For`).

Voir le rapport (`MORNING_REPORT.md`, section V3) pour ce qui a été lancé en conditions réelles et ce qui ne l'a pas été.
