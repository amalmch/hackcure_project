# Interopérabilité — API HL7 FHIR R4 (lecture seule)

Hospital Copilot expose les données cliniques d'un patient au format **HL7 FHIR R4 (4.0.1)**, en JSON (`application/fhir+json`), pour qu'un système d'information hospitalier (SIH), un dossier patient informatisé ou un entrepôt de données puisse les lire sans connaître le modèle interne de la plateforme.

- Code : `dashboard/app/fhir/mapping.py` (fonctions de correspondance pures, sans accès base), `dashboard/app/api/fhir.py` (routes, droits, traçabilité).
- Interface : bouton **« Exporter en FHIR »** dans la vue *Dossier médical* (`dashboard/static/js/v3/fhir-export.js`) → télécharge `PAT-xxxx-fhir.json`.
- Tests : `dashboard/tests/test_v3_fhir.py`, `dashboard/tests/test_v3_fhir_documents.py`.
- Interrupteur : variable d'environnement `FHIR_ENABLED` (activée par défaut ; `FHIR_ENABLED=0` → toutes les routes `/fhir/*` répondent 404 avec un `OperationOutcome`). Elle est lue à chaque requête.

## 1. Ce qui est exposé

| Requête | Réponse |
|---|---|
| `GET /fhir/metadata` | `CapabilityStatement` minimal (ressources, interactions, paramètres de recherche) |
| `GET /fhir/Patient/{id}` | `Patient` |
| `GET /fhir/Observation?patient={id}` | `Bundle` : constantes vitales + biologie (filtre optionnel `category=vital-signs` ou `category=laboratory`) |
| `GET /fhir/Condition?patient={id}` | `Bundle` : maladies chroniques, antécédents, motif de l'hospitalisation en cours |
| `GET /fhir/AllergyIntolerance?patient={id}` | `Bundle` : allergies |
| `GET /fhir/MedicationRequest?patient={id}` | `Bundle` : ordonnances de traitement hospitalières (`inpatient`) et ordonnance de sortie signée (`discharge`) — § 8 |
| `GET /fhir/Encounter?patient={id}` | `Bundle` : admissions |
| `GET /fhir/DocumentReference?patient={id}` | `Bundle` : rapports médecin signés et comptes rendus de sortie, texte pseudonymisé en base64 — § 8 |
| `GET /fhir/Patient/{id}/$everything` | `Bundle` de toutes les ressources ci-dessus que le rôle de l'appelant peut lire |

`{id}` et `patient=` acceptent indifféremment le pseudonyme (`PAT-0001`), la référence FHIR (`Patient/PAT-0001`) ou l'identifiant interne (`patient_01`). En sortie, seul le pseudonyme apparaît.

Les recherches renvoient un `Bundle` de type `searchset` avec `total`, `link[self]` et `entry[{fullUrl, resource, search.mode}]`. Chaque ressource porte `resourceType`, `id`, `meta.lastUpdated` et une référence `subject` (ou `patient`) de la forme `Patient/PAT-0001`.

Les erreurs sont des `OperationOutcome` :

| Code HTTP | `issue.code` | Cas |
|---|---|---|
| 400 | `required` | paramètre `patient` absent |
| 401 | `login` | appel non authentifié |
| 403 | `forbidden` | ressource non accessible au rôle |
| 404 | `not-found` | patient inconnu |
| 404 | `not-supported` | API désactivée (`FHIR_ENABLED=0`) |

## 2. Correspondance modèle → ressource FHIR

| Donnée de la plateforme | Ressource FHIR | Détail |
|---|---|---|
| `Patient` | `Patient` | `id` = `Patient.code` ; `identifier` = `{system: "urn:hackcure:pseudonym", value: code}` ; `gender` ; `name` et `birthDate` selon les droits (§ 4) |
| Constantes en direct (`room_state(room)["vitals"]`), à défaut dernière mesure `VitalReading` | `Observation` (`vital-signs`) | dernière valeur par constante ; `effectiveDateTime` = horodatage de l'appareil ; `device.display` = identifiant de l'appareil ; `encounter` = admission en cours |
| `LabResult` | `Observation` (`laboratory`) | code local (`urn:hackcure:lab`) + code LOINC quand il est connu ; `valueQuantity` ou `valueString` (résultat qualitatif) ; `referenceRange` ; `interpretation` N / A |
| `MedicalRecordEntry` de type `chronique` | `Condition` (`problem-list-item`) | `code.text`, `onsetDateTime` = date du diagnostic |
| `Patient.history` (texte libre) | `Condition` (`problem-list-item`) | un antécédent par segment (virgules et points-virgules hors parenthèses), sans doublon avec les maladies chroniques ; `code.text` seulement |
| `Admission.reason` (admission en cours) | `Condition` (`encounter-diagnosis`) | motif d'hospitalisation, `code.text` |
| `Patient.allergies` + `MedicalRecordEntry` de type `allergie` | `AllergyIntolerance` | `code.text`, `onsetDateTime` si connu |
| `TreatmentOrder` + `TreatmentOrderLine` (ordonnance de traitement hospitalière) | `MedicationRequest` | `status` draft / active / stopped ; `intent` = `order` ; `medicationCodeableConcept.text` (DCI, dosage, spécialité) ; `dosageInstruction` (texte, voie, horaires `timeOfDay`, durée, `asNeededBoolean`) ; `requester`, `reasonCode`, `groupIdentifier` = n° d'ordonnance ; alertes allergie / interaction en `note` |
| `Treatment` (traitement saisi à l'admission) | `MedicationRequest` | `status` active / completed ; posologie et voie en `dosageInstruction` |
| `Prescription` signée + `PrescriptionLine` (ordonnance de sortie) | `MedicationRequest` (`discharge`) | `status` = `active` ; posologie structurée — § 8 |
| `MedicalReport` signé ; `MedicalRecordEntry` signé de type `hospitalisation` | `DocumentReference` | rapport médecin (LOINC 11488-4) ou compte rendu de sortie (18842-5), texte pseudonymisé — § 8 |
| `Admission` | `Encounter` | `class` = `IMP` (hospitalisation) ; `status` in-progress / finished ; `period` ; `location` = chambre ; `reasonCode` et médecin adresseur |

## 3. Codes LOINC et unités UCUM

### Constantes vitales

| Constante (métrique interne) | LOINC | Libellé LOINC | Unité affichée | Code UCUM |
|---|---|---|---|---|
| Fréquence cardiaque (`hr`) | 8867-4 | Heart rate | /min | `/min` |
| SpO2 (`spo2`) | 59408-5 (+ 2708-6) | Oxygen saturation in Arterial blood by Pulse oximetry | % | `%` |
| Pression artérielle (panel) | 85354-9 | Blood pressure panel with all children optional | — | — |
| ↳ systolique (`sys`) | 8480-6 | Systolic blood pressure | mmHg | `mm[Hg]` |
| ↳ diastolique (`dia`) | 8462-4 | Diastolic blood pressure | mmHg | `mm[Hg]` |
| ↳ moyenne (`map`, si présente) | 8478-0 | Mean blood pressure | mmHg | `mm[Hg]` |
| Température corporelle (`tempC`) | 8310-5 | Body temperature | °C | `Cel` |
| Fréquence respiratoire (`rr`) | 9279-1 | Respiratory rate | /min | `/min` |
| Glycémie capillaire (`glucose`) | 41653-7 | Glucose [Mass/volume] in Capillary blood by Glucometer | g/L | `g/L` |

La glycémie capillaire utilise 41653-7 (lecteur de glycémie) et non 2339-0 (glucose sanguin, mg/dL) : la plateforme mesure au lecteur, en g/L. La pression artérielle est une seule Observation à composants (pas de `valueQuantity` au niveau du panel), comme dans le profil FHIR des signes vitaux.

### Biologie

Chaque résultat porte le code local du laboratoire (`urn:hackcure:lab`, ex. `CRP`). Un code LOINC est ajouté pour : HB 718-7, LEUCO 6690-2, PNN 751-8, PLAQ 777-3, CRP 1988-5, PCT 33959-8, LACT 2524-7, NA 2951-2, K 2823-3, CREAT 14682-9, UREE 22664-7, GLY 2345-7, HBA1C 4548-4, TROPO 67151-1, BNP 33762-6, ASAT 1920-8, ALAT 1742-6, INR 6301-6, ALB 1751-7, TSH 3016-3, PH 2744-1, PCO2 2019-8. Les autres examens (ex. hémocultures, ECBU, TP, LDL, cétonémie) ne portent que le code local.

Unités UCUM de la biologie : `mg/L`, `g/L`, `mmol/L`, `umol/L` (µmol/L), `ng/L`, `ng/mL`, `pg/mL`, `%`, `10*9/L` (G/L), `U/L` (UI/L), `m[IU]/L` (mUI/L), `mm[Hg]`. Une unité inconnue est exportée en clair (`unit`) sans `system` ni `code`.

Cette table de correspondance est écrite à la main et n'a pas été validée contre un serveur de terminologie : elle est à faire relire par un biologiste avant tout usage réel.

## 4. Pseudonymisation et droits

**Identifiant.** L'identifiant FHIR d'un patient est toujours son pseudonyme (`PAT-0001`). Ni l'identifiant interne ni la clé de base n'apparaissent dans les ressources.

**Identité.** Le nom et la date de naissance complète ne sont ajoutés que si l'appelant possède la permission `view_identity` (réceptionniste, infirmier, médecins, propriétaire, psychiatre). Sinon (pharmacien) :

- pas de `name` ;
- `birthDate` réduit à l'année (`"1958"`) ;
- `meta.security` contient l'étiquette `PSEUDED` (`http://terminology.hl7.org/CodeSystem/v3-ObservationValue`).

Le sexe (`gender`) est toujours présent.

**Droits par rôle** — les mêmes que le dossier médical (`dashboard/app/api/dossier.py`) :

| Rôle | Patient | Observation | Condition | AllergyIntolerance | MedicationRequest | Encounter | DocumentReference |
|---|---|---|---|---|---|---|---|
| Médecins, propriétaire, psychiatre, infirmier, jeton de service | oui (identité) | oui | oui | oui | oui | oui | oui (texte pseudonymisé) |
| Pharmacien | oui (pseudonymisé) | 403 | 403 | oui | oui | 403 | 403 |
| Réceptionniste | oui (identité) | 403 | 403 | 403 | 403 | oui, sans motif ni médecin | 403 |
| Non authentifié | 401 | 401 | 401 | 401 | 401 | 401 | 401 |

`$everything` ne contient que les types autorisés pour le rôle (le pharmacien reçoit Patient + AllergyIntolerance + MedicationRequest). `GET /fhir/metadata` demande aussi une authentification.

**Traçabilité.** Chaque lecture écrit une ligne `AuditLog` : action `fhir_read`, entité `fhir:<Type>` (ou `fhir:Patient/$everything`), identifiant = pseudonyme, détails = portée, nombre de ressources renvoyées. Un refus (403) écrit une ligne `fhir_denied`.

## 5. Exemples

Authentification : le cookie de session de la plateforme, ou un jeton `Bearer` (celui renvoyé par `/api/auth/login`, ou le jeton de service `PLATFORM_SERVICE_TOKEN`). Les guillemets simples évitent que le shell interprète `$everything`.

```bash
# 1. Connexion (le jeton est renvoyé dans le champ "token")
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"medecin","password":"<mot de passe>"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

# 2. Capacités du serveur
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/fhir/metadata

# 3. Un patient, par son pseudonyme
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/fhir/Patient/PAT-0001

# 4. Dernières constantes vitales
curl -s -H "Authorization: Bearer $TOKEN" 'http://localhost:8000/fhir/Observation?patient=PAT-0001&category=vital-signs'

# 5. Allergies et prescriptions
curl -s -H "Authorization: Bearer $TOKEN" 'http://localhost:8000/fhir/AllergyIntolerance?patient=Patient/PAT-0002'
curl -s -H "Authorization: Bearer $TOKEN" 'http://localhost:8000/fhir/MedicationRequest?patient=PAT-0002'

# 6. Tout le dossier dans un fichier
curl -s -H "Authorization: Bearer $TOKEN" 'http://localhost:8000/fhir/Patient/PAT-0001/$everything' -o PAT-0001-fhir.json
```

Adapter l'hôte et le port à l'installation. Extrait d'une Observation :

```json
{
  "resourceType": "Observation",
  "id": "vital-PAT-0001-heart-rate",
  "meta": {"lastUpdated": "2026-10-11T08:30:00+00:00"},
  "status": "final",
  "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs", "display": "Vital Signs"}]}],
  "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4", "display": "Heart rate"}], "text": "Fréquence cardiaque"},
  "subject": {"reference": "Patient/PAT-0001"},
  "effectiveDateTime": "2026-10-11T08:30:00+00:00",
  "valueQuantity": {"value": 82, "unit": "/min", "system": "http://unitsofmeasure.org", "code": "/min"}
}
```

## 6. Comment un SIH consommerait l'API

1. **Découverte** : `GET /fhir/metadata` indique la version FHIR, les ressources et les paramètres de recherche disponibles.
2. **Rapprochement d'identité** : le SIH conserve la table de correspondance entre son identifiant permanent du patient (IPP) et le pseudonyme `PAT-xxxx`. L'API n'expose pas de recherche de patient par nom : le pseudonyme doit être connu.
3. **Synchronisation** : appel périodique de `GET /fhir/Patient/{id}/$everything` (ou des recherches par type) avec un compte de service ; les `id` des ressources sont stables d'un appel à l'autre, ce qui permet une mise à jour par remplacement côté SIH. Les Observations de constantes vitales représentent la *dernière* valeur connue (un `id` par constante), pas un historique.
4. **Export ponctuel** : le bouton « Exporter en FHIR » produit le même `Bundle` sous forme de fichier, importable dans un autre système ou transmissible avec le dossier lors d'un transfert.

## 7. Limites

- **Lecture seule** : pas de création, de modification ni de suppression (`POST` / `PUT` / `DELETE` ne sont pas implémentés).
- **Pas de SMART-on-FHIR** ni d'OAuth 2 : l'authentification est celle de la plateforme (cookie ou jeton JWT), les droits sont ceux du rôle.
- **Pas de serveur de terminologie** : pas de `$validate-code`, `$expand` ni `$translate` ; la correspondance LOINC est une table statique.
- **Pas de codes SNOMED CT / CIM-10** : antécédents, allergies, motifs d'admission et médicaments sont en texte libre dans la source, ils sont exportés en `code.text` (ou `medicationCodeableConcept.text`) sans code inventé. Les médicaments n'ont ni code ATC ni code CIP.
- **Recherche minimale** : seuls `patient` (alias `subject`) et, pour Observation, `category` sont pris en compte. Pas de `_count`, de pagination, de `_include`, de tri ni de filtre par date ou par code. Pas de lecture unitaire `GET /fhir/Observation/{id}` (seul `Patient` se lit par identifiant). La biologie est limitée aux 1 000 résultats les plus récents.
- **Constantes vitales** : dernière valeur seulement ; l'historique des mesures n'est pas exposé.
- **Conformité non certifiée** : les ressources suivent la structure FHIR R4 de base et n'ont pas été passées au validateur officiel HL7 ni vérifiées contre des profils nationaux.
- **Pseudonymisation, pas anonymisation** : l'année de naissance, le sexe et les données cliniques restent présents ; un export reste une donnée de santé à protéger.

## 8. Documents et ordonnance de sortie (application mobile du patient)

Une application mobile destinée au patient appelle `GET /fhir/Patient/{id}/$everything` avec le jeton de service de la plateforme (`Authorization: Bearer <PLATFORM_SERVICE_TOKEN>`, rôle `owner`) et construit, à partir du `Bundle`, les rappels de prise de médicaments et le plan de soins. Deux ajouts servent cet usage ; ils sont purement additifs (aucun champ existant n'a été retiré).

### 8.1 DocumentReference

`GET /fhir/DocumentReference?patient={id}` (alias `subject=`), et inclus dans `$everything`. Droits : comme `Observation` et `Condition` (médecins, propriétaire, psychiatre, infirmier, jeton de service) ; pharmacien et réceptionniste reçoivent 403 et ne le trouvent pas dans `$everything`.

| Source | `id` | `type` (LOINC) |
|---|---|---|
| `MedicalReport` **signé** d'un séjour en cours, dont le titre ne mentionne ni « sortie » ni « hospitalisation » | `docref-report-{id}` | 11488-4 *Consult note* — « Compte rendu médical » |
| `MedicalReport` **signé** d'un séjour terminé (`Admission.discharged_at` renseigné), ou dont le titre contient « sortie » ou « hospitalisation » | `docref-report-{id}` | 18842-5 *Discharge summary* — « Compte rendu de sortie d'hospitalisation » |
| `MedicalRecordEntry` **signé** de type `hospitalisation` (dossier médical) | `docref-record-{id}` | 18842-5 *Discharge summary* |

Il n'existe pas de table « rapport de sortie » dans le modèle : le compte rendu de sortie est le rapport médecin signé du séjour (règle ci-dessus), complété par les comptes rendus d'hospitalisation du dossier médical. Les brouillons ne sont jamais exportés.

Champs : `status` = `current`, `docStatus` = `final`, `type`, `subject`, `date` (date de signature), `author[0].display` (médecin signataire), `description`, `context.encounter`, et `content[0].attachment` = `{contentType: "text/plain; charset=utf-8", language: "fr", data: <base64 du texte UTF-8>, title, creation}`.

**Les documents sont toujours pseudonymisés**, quel que soit le rôle de l'appelant (y compris `owner` et le jeton de service), parce que le document quitte la plateforme : avant l'encodage en base64, le titre, la description et le texte passent par `privacy.text` (tous les noms de patients connus → pseudonyme), puis le nom et le prénom du patient concerné sont remplacés sans tenir compte de la casse. La ressource porte l'étiquette `meta.security` = `PSEUDED`. Les noms des soignants (auteur) sont conservés. Limite : un nom mal orthographié dans le texte libre n'est pas reconnu.

```json
{
  "resourceType": "DocumentReference",
  "id": "docref-report-4",
  "meta": {"lastUpdated": "2026-10-11T09:10:00+00:00", "security": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationValue", "code": "PSEUDED", "display": "pseudonymized"}]},
  "status": "current",
  "docStatus": "final",
  "type": {"coding": [{"system": "http://loinc.org", "code": "11488-4", "display": "Consult note"}], "text": "Compte rendu médical"},
  "subject": {"reference": "Patient/PAT-0001"},
  "date": "2026-10-11T09:10:00+00:00",
  "author": [{"display": "Dr Leila Trabelsi"}],
  "description": "Compte rendu médical",
  "content": [{"attachment": {"contentType": "text/plain; charset=utf-8", "language": "fr", "data": "UGF0aWVudCBQQVQtMDAwMSwgdnUgY2Ugam91ci4KCsOJdm9sdXRpb24gOiBmYXZvcmFibGUu", "title": "Compte rendu médical", "creation": "2026-10-11T09:10:00+00:00"}}],
  "context": {"encounter": [{"reference": "Encounter/enc-1"}]}
}
```

### 8.2 Les deux sortes de MedicationRequest

Toutes ont `intent` = `order` ; `category[0].coding[0]` (système `http://terminology.hl7.org/CodeSystem/medicationrequest-category`) les distingue.

| Source | `category` | `id` | `status` | `groupIdentifier.system` |
|---|---|---|---|---|
| `TreatmentOrder` + `TreatmentOrderLine` (ordonnance de traitement hospitalière) | `inpatient` | `medreq-order-{ordonnance}-line-{ligne}` | draft / active / stopped | `urn:hackcure:treatment-order` |
| `Treatment` (traitement saisi à l'admission) | `inpatient` | `medreq-treatment-{id}` | active / completed | — |
| `Prescription` **signée** + `PrescriptionLine` (ordonnance de sortie) | `discharge` | `medreq-prescription-{ordonnance}-line-{ligne}` | active | `urn:hackcure:discharge-prescription` |

Champs communs : `medicationCodeableConcept.text` (DCI, dosage et spécialité, ex. « Paracétamol 1 g (Doliprane) »), `authoredOn` (date de signature), `requester.display` (prescripteur), `encounter`, `dosageInstruction[0]`. Une ordonnance de sortie en brouillon n'est pas exportée. La note libre de l'ordonnance de sortie (`note`) est pseudonymisée.

### 8.3 Correspondance de `dosageInstruction`

| Champ FHIR | Ordonnance de sortie (`PrescriptionLine`) | Ordonnance hospitalière (`TreatmentOrderLine`) | Traitement d'admission (`Treatment`) |
|---|---|---|---|
| `text` | `dosage` · `frequency` · voie · « pendant N j » | `dose` · voie · « à HH:MM, … » · « si besoin » · « pendant N j » | `posology` · voie |
| `route.text` (+ `route.coding` SNOMED CT) | `route` | `route` | `route` |
| `doseAndRate[0].doseQuantity` | `dosage` s'il se lit « nombre + unité » (« 1 g », « 0,5 mg », « 12 UI ») | `dose`, même règle | début de `posology`, même règle |
| `doseAndRate[0].rateRatio` | — | — | `posology` de la forme « 500 ml/24 h » (débit) |
| extension `urn:hackcure:fhir:dose-text` | `dosage` non reconnu (« 1 cp le matin ») | `dose` non reconnue | `posology` non reconnue |
| `timing.repeat.frequency` / `period` / `periodUnit` | `frequency` si elle est reconnue (voir ci-dessous) | nombre d'horaires programmés, par jour (3 horaires → 3 / 1 / `d`) | fin de `posology` (« x3/j », « /j ») |
| `timing.repeat.when` | `MORN` / `NOON` / `EVE` / `HS` si « matin », « midi », « soir », « coucher » sont écrits | — | idem |
| `timing.repeat.timeOfDay` | jamais (l'ordonnance de sortie n'a pas d'horaire) | `times` (« 08:00,14:00,20:00 » → `["08:00:00","14:00:00","20:00:00"]`) | jamais |
| `timing.repeat.boundsDuration` | `duration_days` (jours, UCUM `d`) | `duration_days` | — |
| `timing.code.text` | `frequency` telle qu'écrite | — | — |
| extension `urn:hackcure:fhir:frequency-text` | `frequency` non reconnue | — | — |
| `asNeededBoolean` | — | `prn` | — |

Fréquences reconnues : « 3/j », « x3/j », « 3x/j », « 2 fois/j », « 3 fois par jour » (→ *n* / 1 / `d`), « 1 fois par semaine » (→ 1 / 1 / `wk`), « toutes les 8 h » (→ 1 / 8 / `h`), « matin et soir » (→ 2 / 1 / `d` + `when`). Tout autre texte (« selon glycémie », « si besoin ») laisse `frequency` absent : le texte reste dans `text`, `timing.code.text` et l'extension. **Aucune dose, fréquence ou heure n'est déduite** : ce qui n'est pas dans la donnée n'est pas dans la ressource.

Voies : `PO` 26643006 *Oral route*, `IV` 47625008 *Intravenous route*, `SC` 34206005 *Subcutaneous route*, `IM` 78421000 *Intramuscular route* (système `http://snomed.info/sct`) ; la voie inhalée (`INH`) reste en texte seul. Unités de dose avec code UCUM : mg, g, µg (`ug`), ml (`mL`), l (`L`), UI (`[iU]`), mmol ; une autre unité (« bouffées », « cp ») est exportée dans `unit` sans `system` ni `code`. Ces codes n'ont pas été validés contre un serveur de terminologie.

Exemple (ligne d'ordonnance de sortie « Doliprane, 1 g, 3/j, 5 jours, PO ») :

```json
{
  "resourceType": "MedicationRequest",
  "id": "medreq-prescription-3-line-7",
  "meta": {"lastUpdated": "2026-10-11T09:05:00+00:00"},
  "status": "active",
  "intent": "order",
  "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/medicationrequest-category", "code": "discharge", "display": "Discharge"}]}],
  "medicationCodeableConcept": {"text": "Paracétamol 1 g (Doliprane)"},
  "subject": {"reference": "Patient/PAT-0001"},
  "encounter": {"reference": "Encounter/enc-1"},
  "authoredOn": "2026-10-11T09:05:00+00:00",
  "requester": {"display": "Dr Youssef Mansour"},
  "groupIdentifier": {"system": "urn:hackcure:discharge-prescription", "value": "3"},
  "dosageInstruction": [{
    "text": "1 g · 3/j · voie orale · pendant 5 j",
    "route": {"text": "voie orale", "coding": [{"system": "http://snomed.info/sct", "code": "26643006", "display": "Oral route"}]},
    "doseAndRate": [{"doseQuantity": {"value": 1, "unit": "g", "system": "http://unitsofmeasure.org", "code": "g"}}],
    "timing": {"repeat": {"frequency": 3, "period": 1, "periodUnit": "d", "boundsDuration": {"value": 5, "unit": "jour", "system": "http://unitsofmeasure.org", "code": "d"}}, "code": {"text": "3/j"}}
  }],
  "note": [{"text": "Ordonnance de sortie"}]
}
```

Pour une ligne d'ordonnance hospitalière avec horaires, `timing.repeat` devient `{"frequency": 3, "period": 1, "periodUnit": "d", "timeOfDay": ["08:00:00", "14:00:00", "20:00:00"], "boundsDuration": {...}}`.
