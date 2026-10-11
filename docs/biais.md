# Maîtrise des biais et limites des scores

Hospital Copilot est un **prototype d'aide à la décision**, pas un dispositif médical validé. Cette note dit d'où peuvent venir les
erreurs systématiques, ce qui est fait pour les limiter, et ce qui reste à faire avant tout usage réel.

## 1. D'où viennent les données

| Source | Nature | Biais possible |
|---|---|---|
| Patients, dossiers médicaux, biologie | **Entièrement fictifs**, générés de façon déterministe (`dashboard/app/medical_history.py`, `seed.py`) | 4 patients âgés (68 à 81 ans), pathologies choisies pour la démonstration : aucune représentativité. |
| Constantes, appareils | **Simulées** (`simulator/engine.py`), bruit réglé à la main | Les seuils ont été ajustés sur ces signaux propres ; un vrai moniteur a des artefacts que le simulateur n'a pas. |
| Vision (chute, posture) | Modèle YOLO entraîné sur un jeu d'images de chutes (`computer_vision/`, rapports dans `computer_vision/reports/`) | Jeu de données réduit, issu de vidéos publiques : peu de diversité de corpulences, de tenues, d'éclairages, de mobilier hospitalier. Pas de validation en chambre réelle. |
| Expressions du visage | Modèle FER+ (si installé) ou indices de posture | Les modèles d'expression sont connus pour varier selon l'âge, la couleur de peau, les lunettes, les pansements ; une « douleur » lue sur un visage n'est jamais une mesure. |
| Questionnaires | PHQ-9 et GAD-7 (échelles standard) ; questionnaire de sommeil **rédigé pour le projet, non validé** | Traduction, niveau de lecture, pudeur culturelle : un score bas ne veut pas dire « va bien ». |

## 2. Limites de chaque score

- **NEWS2, qSOFA, seuils de SpO2** : règles publiées, appliquées telles quelles (échelle 2 pour les patients BPCO). Elles ont été
  établies sur des populations adultes hospitalisées ; elles ne valent ni en pédiatrie, ni en obstétrique, ni en soins palliatifs.
- **Prédictions (sepsis, cardiaque, épilepsie, diabète, détérioration)** : somme de facteurs pondérés **choisis par l'équipe** et
  extrapolation linéaire d'une pente sur 10 minutes. Les poids ne sont issus d'aucune étude. L'écran porte la mention
  « Estimation de prototype, non validée cliniquement ».
- **Score de bien-être psychologique** : combinaison de questionnaires, d'expressions et d'observations nocturnes ; c'est un repère
  pour orienter l'attention, **jamais un diagnostic**.
- **Hypothèses diagnostiques** : règles « éléments pour / éléments contre » ; la liste n'est pas exhaustive et ignore ce qui n'est pas
  mesuré par la plateforme.
- **Indice de confiance (SADM)** : il mesure la **solidité des données** qui fondent une recommandation (confiance du détecteur,
  persistance du signal, concordance, complétude), par une formule affichée. **Ce n'est pas une probabilité que la recommandation soit
  juste** : aucun jeu de vérité terrain n'a permis de le calibrer.
- **Textes du LLM** : ils expliquent et résument ; ils peuvent être faux ou incomplets. Ils ne fixent jamais la détection ni la
  sévérité, qui viennent des règles en Python.

## 3. Populations non représentées

Enfants, femmes enceintes, patients en soins intensifs ou en fin de vie, personnes à mobilité très réduite (un patient immobile peut
être lu comme « endormi »), patients agités ou confus, chambres à plusieurs lits, peaux foncées et visages partiellement couverts pour
la vision, patients ne lisant pas le français pour les questionnaires. Pour ces situations, le système doit être considéré comme
**non évalué**.

## 4. Garde-fous en place

1. **Les règles décident, le LLM explique** : détection et sévérité sont déterministes, relisibles et testées (`dashboard/app/clinical/`).
2. **Humain dans la boucle** : aucun risque clinique ne se clôt seul ; chaque recommandation peut être validée ou rejetée, avec motif,
   et la décision est tracée (`AuditLog`). Bandeau permanent : la décision et la signature restent celles du médecin.
3. **Transparence** : pour chaque recommandation, les paramètres déclencheurs et la formule de l'indice de confiance sont affichés.
4. **Seuils adaptés au patient** quand la règle le prévoit (BPCO : cible SpO2 88–92 %, fibrillation atriale : seuil de fréquence relevé).
5. **Anti fausses alertes** : confirmation sur plusieurs lectures, durée minimale d'observation avant de parler de tendance, pas de
   doublon de risque, un patient immobile dans son lit n'est pas un risque comportemental.
6. **Repli sûr** : sans LLM, sans n8n ou sans réseau, les règles et les alertes continuent ; le texte de secours est signalé comme tel.
7. **Vie privée** : aucune image ne quitte la chambre ; ce qui sort de la plateforme est pseudonymisé.
8. **Traçabilité des rejets** : les recommandations rejetées restent au journal — c'est la matière première d'une future mesure du taux
   de fausses alertes par type.

## 5. Ce qu'il faudrait faire avant un usage réel

- Mesurer sensibilité, spécificité et taux de fausses alertes **par sous-groupe** (âge, sexe, pathologie, service) sur des données
  réelles, avec l'accord d'un comité d'éthique.
- Calibrer l'indice de confiance sur les décisions réelles des soignants (validées / rejetées).
- Faire valider les poids des prédictions par des cliniciens, ou les remplacer par des scores publiés.
- Évaluer la vision en conditions réelles (nuit, couverture, visiteurs, matériel) et sur des morphologies variées.
- Surveiller la dérive dans le temps (changement de matériel, de population) et prévoir une revue périodique des règles.
