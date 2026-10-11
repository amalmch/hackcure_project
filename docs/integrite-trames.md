# Intégrité des trames IoT (V3, étape 5)

Chaque message envoyé par l'edge (Raspberry Pi), par le simulateur et par `camera_loop.py` peut porter un **numéro de séquence**,
un **horodatage** et une **signature HMAC-SHA256**. Le serveur rejette les trames falsifiées, rejouées ou trop anciennes, les compte,
et affiche le résultat dans l'indicateur « Intégrité des trames » de la page **Paramètres des machines**.

> **Par défaut, aucune clé n'est configurée : c'est le mode démo.** Les trames sont acceptées sans vérification, exactement comme
> avant, et l'indicateur affiche l'avertissement « Mode démo — clé non configurée, trames acceptées sans vérification ».

## 1. Format

Trois champs dans le payload JSON de chaque message (les schémas `contracts/schemas/*.json` acceptent les champs supplémentaires) :

| Champ | Type | Rôle |
|---|---|---|
| `seq` | entier | strictement croissant par émetteur (émetteur = `source` du payload + chambre du topic, ex. `edge-yolo@101`) |
| `ts` | chaîne ISO 8601 UTC | déjà présent sur tous les messages ; c'est l'horodatage signé |
| `sig` | chaîne hexadécimale minuscule (64 caractères) | HMAC-SHA256 du message avec la clé partagée |

Calcul de la signature :

```
sig = HMAC_SHA256( clé, UTF-8( topic + "\n" + canonical_json(payload sans "sig") ) )   → hexadécimal minuscule
canonical_json(obj) = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```

Le topic fait partie de ce qui est signé : une trame valide de la chambre 101 ne peut pas être rejouée vers la 103.

Exemple :

```json
{ "topic": "hackcure/room/101/env",
  "payload": { "ts": "2026-10-11T20:15:02.412345+00:00", "source": "edge-yolo", "tempC": 22.4, "humidity": 45.0,
               "motion": false, "doorOpen": false, "seq": 1791749702413, "sig": "9f2c…(64 caractères hexadécimaux)" } }
```

Les primitives sont dans **`contracts/integrity.py`** (bibliothèque standard uniquement : `canonical`, `signature`, `sign`, `verify`,
`parse_ts`, classe `Signer`). Le même fichier est utilisé par le serveur, l'edge, le simulateur et `camera_loop.py`.

## 2. Règles du serveur

Le contrôle (`dashboard/app/ingest/integrity.py`, fonction `check`) est appelé par `handler.handle()` juste après la validation du
contrat, donc pour **tous les canaux** : MQTT, repli HTTP `POST /api/ingest`, simulateur embarqué.

Avec une clé (`EDGE_HMAC_KEY` non vide — mode `enforced`), dans cet ordre :

| Contrôle | Raison de rejet | Libellé dans l'interface |
|---|---|---|
| `sig` ou `seq` absent ou mal formé | `unsigned` | non signée |
| signature différente de celle attendue (comparaison en temps constant, `hmac.compare_digest`) | `bad_signature` | signature invalide |
| `ts` plus vieux que `FRAME_MAX_AGE_S` (30 s), en avance de plus de `FRAME_MAX_FUTURE_S` (5 s), ou illisible | `stale` | trop ancienne |
| `seq` inférieur ou égal à la dernière séquence acceptée de cet émetteur | `replay` | rejeu |

Sinon la trame est acceptée et comptée comme vérifiée.

**Redémarrage d'un émetteur.** Une séquence plus basse que la dernière acceptée est admise seulement si la trame est fraîche
(contrôle `stale` passé) **et** si rien n'a été accepté de cet émetteur depuis plus de `FRAME_MAX_AGE_S` secondes. Ce n'est pas une
faille : une trame rejouée après un tel silence a forcément plus de 30 s, elle est donc déjà rejetée comme trop ancienne. En
pratique nos émetteurs n'ont même pas besoin de cette règle : leur compteur démarre à l'heure courante en millisecondes, donc un
edge relancé repart au-dessus de sa séquence précédente, sans trou.

**Ce qui se passe lors d'un rejet.**
- HTTP `POST /api/ingest` : si aucun message du lot n'est accepté et qu'au moins un a été refusé par ce contrôle → **`401`**, avec
  le détail `[{topic, error, reason}]`. Dans un lot mixte, la réponse reste `202` et les trames refusées sont listées dans
  `rejected` avec leur `reason`. Un message qui ne respecte pas son schéma reste un `422`, comme avant.
- MQTT et simulateur embarqué : la trame est ignorée (comptée, journalisée au plus une fois toutes les 5 s par raison).
- Dans tous les cas : compteur `rejected` de `/api/ingest/stats` incrémenté, rejet visible dans `/api/integrity`.

**Exemptés** (émis par le serveur lui-même) : les commandes `…/cmd/{équipement}`, `hackcure/sim/scenario`, et l'acquittement de
l'edge virtuel interne (`via="virtual"`). L'acquittement `…/cmd/ack` d'un vrai edge, lui, doit être signé.

**Sans clé (mode `demo`)** : tout est accepté et compté « non vérifié », un avertissement est écrit une fois dans les journaux, et
l'interface l'affiche en permanence. Les champs `seq` / `sig` éventuellement présents sont ignorés.

## 3. API et interface

`GET /api/integrity` (authentifié, permission `view_clinical`, comme `/api/devices`) :

```json
{ "mode": "enforced", "keyConfigured": true, "algorithm": "HMAC-SHA256", "maxAgeS": 30.0, "maxFutureS": 5.0, "warning": null,
  "counters": { "accepted": 1240, "verified": 1240, "unverified": 0, "exempt": 3, "rejected": 2,
                "byReason": { "bad_signature": 1, "replay": 1, "stale": 0, "unsigned": 0 } },
  "senders": [ { "sender": "sim@102", "lastSeq": 1791749702413, "accepted": 310, "lastAcceptedAt": "…" } ],
  "lastRejection": { "reason": "replay", "label": "rejeu (séquence déjà vue)", "topic": "hackcure/room/102/env", "sender": "sim@102", "seq": 12, "via": "http", "at": "…" },
  "recentRejections": [ "… les 20 plus récents, le dernier d'abord …" ] }
```

En mode démo : `"mode": "demo"`, `"keyConfigured": false`, `"warning": "Mode démo — clé EDGE_HMAC_KEY non configurée, …"`.
Les compteurs sont en mémoire : ils repartent de zéro au redémarrage du serveur.

L'indicateur de la page Machines (`dashboard/static/js/v3/frame-integrity.js`) interroge cette route toutes les 5 s tant que la
page est affichée : mode, trames acceptées, trames rejetées par raison, dernier rejet.

## 4. Générer et installer la clé

Générer une clé aléatoire de 256 bits (une seule fois) :

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Serveur** — dans le fichier `.env` à la racine du projet, puis redémarrer le serveur :

```ini
EDGE_HMAC_KEY=la-clé-générée
# optionnel
FRAME_MAX_AGE_S=30
FRAME_MAX_FUTURE_S=5
```

Le simulateur embarqué (`EMBEDDED_SIM=1`) tourne dans le serveur : il lit la même variable et signe ses trames tout seul, ce qui
alimente l'indicateur en trames vérifiées pendant la démonstration.

**Raspberry Pi (edge)** — la même clé, au choix :
- variable d'environnement (prioritaire, recommandé) : `export EDGE_HMAC_KEY=la-clé-générée` avant `python edge/main.py …`, ou
  `Environment=EDGE_HMAC_KEY=la-clé-générée` dans l'unité systemd (`edge/systemd/`) ;
- ou dans `edge/config/room101.yaml`, en décommentant :
  ```yaml
  security:
    hmac_key: "la-clé-générée"
  ```
Au démarrage, l'edge écrit « Intégrité des trames : signature HMAC-SHA256 active » (ou « aucune clé »). Le dossier `contracts/` du
dépôt doit être présent sur le Pi (il contient `integrity.py`).

**Simulateur autonome et caméra PC** — ces processus ne lisent pas `.env` : exporter la variable dans le terminal
(`export EDGE_HMAC_KEY=…`, ou `$env:EDGE_HMAC_KEY="…"` sous PowerShell) avant `python simulator/sim.py …` (ou option
`--hmac-key`) et avant `python dashboard/camera_loop.py …`.

**Vérifier** : page Machines → l'indicateur passe à « Vérification HMAC-SHA256 active » et le compteur des trames acceptées monte.
Pour montrer un rejet, renvoyer deux fois la même trame signée, ou une trame sans signature, sur `POST /api/ingest` : réponse `401`
et le compteur correspondant augmente.

**Revenir au mode démo** : vider `EDGE_HMAC_KEY` dans `.env` et redémarrer le serveur. Les émetteurs peuvent continuer à signer : le
serveur ignore alors les signatures.

## 5. File hors ligne de l'edge

Quand le serveur est injoignable, l'edge garde les messages importants (alarmes, visites du personnel, appels) dans une file
locale et les renvoie à la reconnexion — souvent plus de 30 s après la mesure. Règle retenue (`edge/transport/__init__.py`) :

- la file contient les messages **d'origine, non signés** ;
- la signature est calculée **au moment de l'envoi** ; pour un message sorti de la file, `ts` devient l'heure d'envoi, l'heure
  de mesure d'origine est conservée dans **`measuredAt`**, et le message reçoit une séquence fraîche ;
- sans clé, rien de tout cela ne s'applique : les messages partent tels quels, comme avant.

En MQTT, les messages critiques (QoS 1) que le client met en attente pendant une coupure du broker sont déjà signés : au-delà de
30 s de coupure ils seront rejetés comme trop anciens. Le repli HTTP, lui, applique la règle ci-dessus.

## 6. Limites connues

- **Une seule clé symétrique partagée** par tous les émetteurs et le serveur : pas de clé par appareil, pas de rotation
  automatique, pas de révocation individuelle. Un appareil compromis permet de signer au nom de tous. Étape suivante naturelle :
  une clé par appareil (dérivée d'une clé maître) ou des certificats (mTLS sur le broker).
- **Les horloges doivent être synchronisées** (NTP sur le Pi et sur le serveur). Un Pi en retard de plus de 30 s, ou en avance de
  plus de 5 s, voit toutes ses trames rejetées comme « trop anciennes ». Ajuster `FRAME_MAX_AGE_S` / `FRAME_MAX_FUTURE_S` si besoin.
- **Intégrité et authenticité, pas confidentialité** : les trames ne sont pas chiffrées (utiliser TLS pour cela).
- **Un seul émetteur par couple `source` + chambre** : deux processus qui publient avec la même source pour la même chambre (par
  exemple le simulateur embarqué et un simulateur autonome en même temps) se font rejeter mutuellement comme rejeux.
- L'état anti-rejeu et les compteurs sont **en mémoire** : après un redémarrage du serveur, une trame capturée dans les 30
  dernières secondes pourrait être rejouée une fois.
- L'ordre d'arrivée doit suivre l'ordre d'émission (vrai pour un client MQTT et pour les lots HTTP) ; une trame arrivée en retard
  derrière une plus récente du même émetteur est rejetée comme rejeu.
- Les routes historiques hors contrats (`/api/yolo/event`, déclencheurs de démonstration) ne passent pas par ce contrôle.
- Les commandes serveur → edge (`…/cmd/{équipement}`) ne sont pas signées dans cette étape.
