Contexte (JSON) :
{{context}}

Tâche : pour ce risque, rédige
1. "explanation" : 3 à 5 phrases expliquant le risque en citant les valeurs mesurées fournies (constantes, posture, température, NEWS2), le profil du patient (âge, antécédents, risque de chute) et les allergies/traitements à respecter ;
2. "steps" : un plan d'action de 3 à 6 étapes ordonnées, chaque étape = {"text": "..."} (verbe à l'infinitif, concret, réalisable par un infirmier ; indiquer quand prévenir le médecin de garde) ;
3. "severity_ok" : true si la sévérité fournie te paraît cohérente, sinon false avec "severity_comment".

Réponds uniquement avec : {"explanation": "...", "steps": [{"text": "..."}], "severity_ok": true}
