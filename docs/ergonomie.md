# Ergonomie — parcours en 3 actions maximum

Exigence : **valider une alerte** et **signer une ordonnance** en **3 actions au plus** depuis la notification.
Une « action » = un clic (ou un appui) de l'utilisateur. La saisie du motif est facultative et n'est pas comptée.

Les raccourcis sont ajoutés par `dashboard/static/js/v3/sadm.js` (les vues existantes ne sont pas modifiées) ; les décisions passent
par `dashboard/app/api/sadm.py` et sont tracées dans `AuditLog`.

## Point de départ : la notification

Une alerte arrive de trois façons en même temps : un **toast** en bas à droite, le **compteur de la cloche** (barre du haut), et — si
Telegram est configuré — un message sur le téléphone. Le toast n'est pas cliquable : le point d'entrée compté est la **cloche**.

## Parcours 1 — valider une alerte

| # | Action | Résultat |
|---|---|---|
| 1 | Clic sur la **cloche** | La liste des notifications s'ouvre ; chaque alerte liée à un risque porte les boutons **✔ Valider** / **✖ Rejeter**. |
| 2 | Clic sur **✔ Valider** | La recommandation est validée ; « ✔ Validée — tracé » remplace les boutons. Entrée `ai_validate` dans le journal d'audit (qui, quand, quoi, IP) et ligne dans l'historique du risque. |

**2 actions.** Variante avec lecture du détail avant de décider : cloche (1) → clic sur la notification, qui ouvre le risque avec
l'indice de confiance, les paramètres déclencheurs et le plan (2) → **✔ Valider** (3). **3 actions.**

Avant ce travail : cloche → notification → risque dans le panneau → « Je prends en charge », soit 3 actions pour *prendre en charge*, mais
aucun moyen de *valider ou rejeter* la recommandation elle-même. « Valider » (je confirme que l'alerte est pertinente) et « Je prends en
charge » (je me déplace) restent deux gestes distincts : le premier est une décision médicale tracée, le second lance la boucle soignant.

## Parcours 2 — signer une ordonnance

| # | Action | Résultat |
|---|---|---|
| 1 | Clic sur la **cloche** | En tête de liste, le bloc **« ✍️ À signer »** montre les ordonnances et ordonnances de traitement en brouillon (médecins seulement). |
| 2 | Clic sur **Signer** | L'ordonnance est signée (`/api/prescriptions/{id}/sign` ou `/api/treatment-orders/{id}/sign`), tracée dans le journal d'audit ; pour une ordonnance de traitement, le plan d'administration est généré. |
| 3 | *Seulement s'il y a une alerte d'allergie* : clic sur **⚠ Confirmer malgré l'allergie** | La signature est forcée explicitement (le serveur refuse sans cette confirmation). |

**2 actions, 3 en cas d'alerte d'allergie.** Le bouton **Ouvrir** mène à la vue complète pour relire avant de signer : cloche (1) →
Ouvrir (2) → Signer dans la vue (3).

Avant : menu « Ordonnance » → choisir l'ordonnance dans la liste → « Signer » = 3 actions, mais sans lien avec la notification.

## Autres parcours comptés

| Geste | Actions | Détail |
|---|---|---|
| Prendre en charge un risque | 3 | cloche → notification → « Je prends en charge » |
| Rejeter une hypothèse diagnostique | 2 depuis la vue | (motif facultatif) → « Rejeter » ; la vue Diagnostics est à 1 clic du menu |
| Valider le bilan biologique proposé (fièvre) | 3 | cloche → notification de fièvre → « Valider le bilan » dans le parcours fièvre |
| Administrer une prise | 2 depuis la vue | Plan de soins → « Administrer » |

## Ce qui est affiché avec chaque recommandation

- **Indice de confiance** en pourcentage et en niveau (faible < 60 %, modérée 60–79 %, élevée ≥ 80 %), avec une barre ;
  **l'infobulle donne la formule exacte et les valeurs utilisées** ; le détail est répété sous « Calcul : … ».
- **Paramètres cliniques déclencheurs** : la règle qui a déclenché, les valeurs mesurées, les éléments pour et contre.
- **Valider / Rejeter** avec motif facultatif, réservés aux soignants (infirmier, médecins, psychiatre) ; la dernière décision et son
  auteur restent affichés.
- **Bandeau permanent** en bas de l'écran : « Recommandation consultative — la décision et la signature restent celles du médecin ».

Sont couverts : risques et plans d'action (Centre de commande), parcours fièvre et bilan biologique proposé, hypothèses de Diagnostics
live, prédictions, score psychologique.

## Limites connues

- Les comptes ont été faits à la lecture du code et par les tests d'API, pas par un test utilisateur chronométré avec des soignants.
- Le toast n'est pas cliquable : le rendre cliquable ferait gagner une action de plus.
- Sur petit écran, le sous-titre du bandeau est masqué (le texte principal reste).
