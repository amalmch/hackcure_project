# HackCure — Mobile App & Hospital Copilot Architecture & Guide

Ce document décrit l'intégration cohérente de l'application mobile patient (`mobile/` et `mobile_backend/`) au sein du projet `Hospital_copilot`.

---

## ??? Architecture Globale HackCure

Le projet combine deux piliers complémentaires :

1. **Hospital Copilot (Poste Soignants & Jumeau Numérique 3D)**
   - **Dossier** : `dashboard/` + `computer_vision/`
   - **Port** : `http://localhost:8000`
   - **Rôle** : Surveillance clinique en temps réel dans les chambres d'hôpital (chambre 101, 102...), jumeau 3D, alertes chutes/inconfort facial/posture par caméra, alertes machines et constantes vitales.

2. **Mobile Patient App & API (Application Mobile Patient & Suivi Autonomie)**
   - **Dossier Mobile** : `mobile/` (React Native / Expo Router v57)
   - **Dossier Backend API** : `mobile_backend/` (FastAPI sur port `8001`)
   - **Rôle** :
     - Consultation des prescriptions médicales prescrites par le médecin (source unique de vérité).
     - Rappel des prises médicamenteuses (doses `SCHEDULED`, `DUE`, `TAKEN_ON_TIME`).
     - Suivi de l'observance et du score d'adhésion.
     - Thérapie sportive et nutritionnelle personnalisée.
     - Recherche géolocalisée de pharmacies à proximité avec disponibilité en stock.
     - Messagerie directe avec le médecin et téléconsultation.
     - Compagnon d'assistance IA Sakina.
     - Support multilingue (Français, Anglais, Arabe RTL) et mode hors-ligne.

---

## ?? Guide de Démarrage Rapide

### 1. Démarrer le Backend Hospitalier (Déjà en cours ou à relancer)
```powershell
cd C:\Users\bousl\Desktop\Hospital_copilot\dashboard
python -m uvicorn server:app --reload --port 8000
```
- Accès Dashboard 3D : [http://localhost:8000](http://localhost:8000)

### 2. Démarrer le Backend Mobile Patient (Port 8001)
Dans un nouveau terminal :
```powershell
cd C:\Users\bousl\Desktop\Hospital_copilot
.\run_mobile_backend.ps1
```
*(ou manuellement : `cd mobile_backend; python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload`)*
- Documentation interactive Swagger : [http://localhost:8001/docs](http://localhost:8001/docs)

### 3. Lancer l'Application Mobile (Expo / Web)
Dans un troisième terminal :
```powershell
cd C:\Users\bousl\Desktop\Hospital_copilot
.\run_mobile_app.ps1
```
- **Aperçu dans le navigateur Web** : tapez `w` dans la console ou lancez `npm run web` (ouvre `http://localhost:8081`).
- **Sur smartphone physique** : ouvrez l'application **Expo Go** (Android / iOS) et scannez le QR code affiché dans le terminal.

---

## ?? Identifiants Démo Médicaux

La base de données `hackcure.db` a été pré-remplie avec des données médicales réalistes :

| Rôle | Email | Mot de passe | Description |
|---|---|---|---|
| **Patient** | `mohamed@example.com` | `Test123!@#` | Patient avec prescription cardiologie active, plan de marche & régime hyposodé |
| **Médecin** | `dr.karim@example.com` | `Test123!@#` | Cardiologue référent |
| **Pharmacien** | `pharmacist@example.com` | `Test123!@#` | Pharmacie centrale avec stock de médicaments |

---

## ??? Vérification & Tests

- **Compilation TypeScript Mobile** :
  ```powershell
  cd mobile
  npx tsc --noEmit   # 0 erreurs
  ```
- **Tests Backend Mobile** :
  ```powershell
  cd mobile_backend
  python -m pytest tests/ -q   # 34 tests validés avec succès
  ```
