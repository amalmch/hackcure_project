# Script de démonstration — 3 minutes

Préparation (avant le jury) : `scripts\run-demo.ps1 -Reset` (ou `./scripts/run-demo.sh --reset`), ouvrir <http://localhost:8000>,
se connecter en **infirmier** (`infirmier` / `hackcure2026`) dans un onglet, et en **médecin de garde** (`medecin_garde`) dans un second onglet
(ou un second écran). Onglet **Agents** visible à droite. Variables conseillées : `FOLLOWUP_RECHECK_S=30` (réglé par le script).

**n8n** : `npx n8n` lancé, `.\n8n\import.ps1 -Check` affiche 4 × ACTIF, le badge **« n8n · orchestration »** est rose dans la barre du haut.
Ouvrir n8n dans un troisième onglet (bouton **🔗 Ouvrir n8n**, visible en médecin) sur le workflow `risk-triage`, onglet **Executions**.
Garder Telegram ouvert sur un téléphone ou à l'écran.

| Temps | Action | Ce que le jury voit |
|---|---|---|
| 0:00 | Présenter le jumeau 3D : 4 chambres, accueil, extérieur. Cliquer **101** pour zoomer. | Avatar dans le lit, moniteur animé avec les **vraies constantes** du simulateur (FC, SpO2, PA, T°), étiquettes potence et moniteur, bandeau KPI. |
| 0:20 | **Lancer la démo → full_demo** (chambre 101). | Toast « scénario lancé », étapes affichées au fil de l'eau. |
| 0:30 | Le patient se redresse puis **se lève** (nuit). | Avatar assis puis **debout** à côté du lit ; VisionAgent → RiskAgent : risque **« Lever non accompagné »** (moyen/élevé), notification cloche, chambre **orange**. Veilleuse allumée (règle locale sur le Pi réel). |
| 0:50 | Il marche vers la porte puis **chute**. | Avatar **au sol** (pose existante), expression douleur, chambre **violette** pulsée, bannière critique. Panneau Agents : **VisionAgent → RiskAgent** (critical, « orchestré par n8n ») → **n8n:risk-triage** : appel Claude, plan d'action de 3 à 6 étapes en ~10 s, **Telegram** à l'infirmier, attente d'acquittement. Alarme locale `safety/alarm` si edge réel. |
| 1:10 | Ouvrir **Centre de commande** (infirmier). Montrer l'explication IA qui cite les constantes, les allergies (AINS, aspirine), les traitements. | Étiquette **« orchestré par n8n »**, plan d'action (fournisseur « anthropic … (n8n) ») avec cases à cocher, bouton **🙋 Je prends en charge** ; équipements de la chambre. |
| 1:15 | Basculer 10 s sur l'onglet **n8n** : exécution en cours de `risk-triage`. | Le graphe du workflow : Webhook → prompt → **HTTP Anthropic** (ouvrir le nœud : la réponse JSON de Claude) → plan → Telegram → **Wait** en attente. Montrer le message reçu sur Telegram. |
| 1:25 | À 1:00 du scénario, **l'infirmier entre** dans la chambre. | Avatar **infirmier** en tenue teal près du lit ; FollowUpAgent : risques → **en cours**, `StaffVisit` enregistré ; KPI « personnel en chambre ». |
| 1:35 | Cocher 2 étapes du plan (horodatées), le patient est réinstallé (scénario), **l'infirmier sort**. | FollowUpAgent : « re-vérification déléguée à n8n » ; **n8n:risk-verify** : attente 30 s. |
| 2:10 | Attendre la re-vérification. | n8n relit l'état réel de la chambre, Claude justifie (« plus au sol : posture lying_bed, FC 82… ») : risques **résolus + vérifiés**, chambre **verte**, Telegram de confirmation, journal des agents complet (📥 → 🧠 → ✅). |
| 2:20 | Bonus : à 2:10 du scénario, la **caméra thermique** monte (chaufferette). | Halo orange/rouge sur la tête de l'avatar, moniteur 39 °C, VitalsAgent → risque **« Fièvre »** avec plan (contrôle thermomètre, NEWS2, prévenir le médecin si ≥ 39 °C). |
| 2:35 | **Rapport de garde → Générer** (12 h) puis **Imprimer / PDF**. | « n8n rédige… » puis, ~25 s plus tard, le rapport apparaît (workflow `shift-report`) : par chambre, événements, risques, actions, état, **humeur** ; lien d'impression reçu sur Telegram ; page A4. |
| 2:50 | Onglet médecin : **Ordonnance** → ajouter *Clamoxyl* pour la chambre 102. | **Alerte allergie (pénicilline)** immédiate ; signature refusée tant que la ligne existe ; impression. |
| 3:00 | Conclusion : rôles (pharmacien = pharmacie seulement), mode Real pour un vrai Pi (`edge/main.py`), MQTT optionnel. | — |

## Montrer n8n au jury (1 minute de plus)
1. **L'escalade** : lancer `fall_demo` (chambre 104) et ne rien toucher. Après 2 min sans « Je prends en charge », le nœud Wait de `risk-triage` expire : le risque passe **escaladé**, Telegram au médecin de garde. (Pour aller vite : lancer la plateforme avec `ESCALATION_CRITICAL_S=20`.) Puis `nurse_resolves` : `risk-verify` clôture le risque.
2. **L'acquittement** : sur un risque ouvert, cliquer **🙋 Je prends en charge** : toast « n8n informé (attente levée) », l'exécution n8n se termine sur « acquitté », pas d'escalade.
3. **Le repli** : arrêter n8n (Ctrl+C). En 20 s, le badge devient **« n8n hors ligne · repli local »** ; relancer un scénario : le plan est rédigé par le RiskAgent (étiquette « agents locaux »), l'escalade et la re-vérification repassent au FollowUpAgent. Rien ne s'arrête.
4. **Pharmacie** : vue Pharmacie → **📣 Envoyer les alertes (n8n)** : Telegram au pharmacien (stock sous le seuil, péremption < 30 j).
5. Phrase clé : « la plateforme détecte avec des règles déterministes ; n8n orchestre la réponse ; Claude rédige, un soignant valide ».

## Variantes rapides
- `fall_demo` (chambre 104, 40 s) puis `nurse_resolves` (45 s) : même boucle en chambre 104, plus courte.
- `sepsis_trend` (chambre 102, 2 min) : dérive progressive → NEWS2 ≥ 5 → risque « Score NEWS2 élevé » / « Tendance sepsis ».
- `iv_empty` (chambre 103) : perfusion < 50 ml puis occlusion → alertes équipement, étiquette rouge sur la potence.
- `fever_101` : fièvre seule en 101.
- `stop` : remet toutes les chambres au calme.
- Boutons de démo existants (Chute / Douleur / Chute + douleur / Récupération / Séquence auto / Reset) : toujours fonctionnels (état 3D legacy).

## Avec le vrai Raspberry Pi
`python edge/main.py` sur le Pi (voir `MORNING_REPORT.md`) : la chambre 101 passe en vision réelle (`source: edge-yolo|edge-pose`),
le simulateur embarqué coupe automatiquement sa vision virtuelle pour la 101 et ne garde que les appareils.
