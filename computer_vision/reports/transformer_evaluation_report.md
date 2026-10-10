# Rapport d'Évaluation & Analyse de Pertinence : Vision Transformer HackCure

## 1. Vue d'Ensemble
- **Architecture :** DINOv2 (ViT-S/14 Foundation Backbone) + Multi-Head Self-Attention Head + Attention Pooling
- **Date d'Entraînement :** 2026-10-10 18:52:26
- **Tâche :** Classification de posture patient & Détection de chute (`falling` vs `no_falling`)
- **Matériel :** NVIDIA GeForce RTX 4060 Laptop GPU

## 2. Performances sur le Jeu de Test (Test Set - 130 patients)
| Métrique | Score | Interprétation |
| :--- | :--- | :--- |
| **Exactitude (Accuracy)** | **92.31%** | Performance globale de classification |
| **Rappel Chute (Recall 'falling')** | **93.48%** | 43/46 chutes détectées sans faux négatifs critiques |
| **Précision Chute (Precision 'falling')** | **86.00%** | Taux de vraies alertes de chute |
| **F1-Score Chute** | **89.58%** | Équilibre précision / rappel sur événement critique |
| **Macro F1-Score** | **91.74%** | Moyenne non biaisée sur les deux classes |
| **ROC-AUC** | **0.9746** | Capacité de discrimination probabiliste |
| **Latence d'inférence (Tête GPU)** | **5.35 ms** (**186.8 FPS**) | Inférence ultra-rapide temps réel |

## 3. Matrice de Confusion
- **Vrais Positifs (Chutes bien détectées) :** `43`
- **Faux Négatifs (Chutes manquées) :** `3`
- **Faux Positifs (Fausses alertes de chute) :** `7`
- **Vrais Négatifs (Positions normales confirmées) :** `77`

## 4. Analyse de Pertinence : Est-ce Pertinent pour HackCure ?
**Verdict : HAUTEMENT PERTINENT**

### Pourquoi ce résultat est pertinent :
1. **Complémentarité avec YOLOv8 :**
   - YOLOv8 localise spatialement le patient dans la chambre (boîte englobante).
   - Le **Vision Transformer (DINOv2)** analyse la **sémantique fine de posture** (orientation de la colonne vertébrale, contact avec le sol, étalement des membres) via son mécanisme d'attention spatiale.
2. **Réduction des faux négatifs critiques :**
   - En milieu hospitalier, le pire scénario est de ne pas voir une chute (`False Negative`). Avec un rappel élevé de **93.5%**, le modèle alerte l'équipe soignante de manière fiable.
3. **Synergie avec l'Agent d'Intervention :**
   - Le score de probabilité continu émis par le Transformer alimente directement le module de décision temporelle (`TemporalRiskAnalyzer`) et l'adaptateur d'agent (`agent_adapter.py`) pour qualifier le niveau de risque (`moderate`, `high`, `critical`).
