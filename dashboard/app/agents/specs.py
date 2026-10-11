"""
Spécifications des raisonnements LLM des agents (V2) : une seule source pour
- les workflows n8n (`n8n/build_workflows.py` génère un workflow par entrée) ;
- le repli local (`orchestration._run_local`) quand n8n est indisponible.

Chaque entrée : `agent` (agent Python propriétaire), `webhook` (chemin du webhook n8n), `title`, `system`
(consigne), `format` (forme JSON exacte attendue), `required` (clés obligatoires), `max_tokens`,
`mock(context)` (réponse déterministe de secours, construite à partir des seules valeurs du contexte).
"""

from __future__ import annotations

import json
from typing import Any, Optional

RULES = (
    "Tu es un assistant d'aide à la décision d'une clinique (Hospital Copilot). "
    "Règles : n'invente JAMAIS de valeur ; cite les valeurs fournies ; respecte strictement les allergies et les traitements en cours ; "
    "tu ne poses pas de diagnostic et tu ne prescris rien : tu expliques, synthétises et suggères, un soignant valide. "
    "La détection et la sévérité sont déjà fixées par des règles déterministes : ne les modifie pas. "
    "Réponds en français, UNIQUEMENT par un objet JSON valide, sans texte autour et sans balise Markdown."
)

SPECS: dict[str, dict[str, Any]] = {}


def spec(name: str, **kw: Any) -> None:
    kw.setdefault("webhook", name)
    kw.setdefault("max_tokens", 8000)  # le modèle consomme des tokens de réflexion avant de répondre
    kw.setdefault("required", [])
    SPECS[name] = kw


def build_prompt(workflow: str, context: dict[str, Any]) -> tuple[str, str]:
    s = SPECS[workflow]
    system = RULES + "\n" + s["system"]
    user = f"Contexte (JSON) :\n{json.dumps(context, ensure_ascii=False, indent=1, default=str)}\n\nFormat exact attendu :\n{s['format']}"
    return system, user


def validate(workflow: str, data: Optional[dict[str, Any]]) -> Optional[str]:
    """None si la réponse est exploitable, sinon le motif du rejet."""
    if not isinstance(data, dict):
        return "réponse absente ou JSON invalide"
    missing = [k for k in SPECS[workflow]["required"] if data.get(k) in (None, "", [])]
    return f"clé(s) manquante(s) : {', '.join(missing)}" if missing else None


def _v(ctx: dict[str, Any], *path: str, default: Any = None) -> Any:
    cur: Any = ctx
    for k in path:
        cur = cur.get(k) if isinstance(cur, dict) else None
        if cur is None:
            return default
    return cur


# ─── FeverAgent ───────────────────────────────────────────────────────────────
def _mock_fever(ctx: dict[str, Any]) -> dict[str, Any]:
    p = ctx.get("patient") or {}
    v = ctx.get("constantes") or {}
    labs = ctx.get("bilan_propose") or []
    if ctx.get("phase") == "resultats":
        res = ctx.get("resultats") or []
        abn = [r for r in res if r.get("anormal")]
        return {
            "summary": f"Résultats du bilan reçus pour {p.get('nom', 'le patient')} : {len(abn)} valeur(s) hors normes sur {len(res)}.",
            "interpretation": "; ".join(f"{r['examen']} {r['valeur']} {r.get('unite', '')} (normes {r.get('normes', 'n/a')})" for r in abn) or "Aucune valeur hors normes.",
            "labs": [], "watch": ["Recontrôler la température centrale après l'antipyrétique prescrit.", "Surveiller NEWS2 et qSOFA toutes les heures jusqu'à apyrexie."],
        }
    return {
        "summary": f"Fièvre vraie chez {p.get('nom', 'le patient')} ({p.get('age', '?')} ans) : température centrale {v.get('tempC', '?')} °C ({ctx.get('critere', '')}), "
                   f"qSOFA {ctx.get('qsofa', '?')}, NEWS2 {ctx.get('news2', '?')}. Antécédents : {p.get('antecedents') or 'non renseignés'}. Allergies : {p.get('allergies') or 'aucune connue'}.",
        "exam_focus": ["Rechercher un foyer infectieux (pulmonaire, urinaire, cutané, voie veineuse).", "Évaluer conscience, hydratation et signes de sepsis (qSOFA, NEWS2)."],
        "labs": [{"code": x["code"], "justification": x.get("motif") or "Examen proposé par la règle du parcours fièvre."} for x in labs],
        "watch": ["Température centrale et constantes toutes les heures.", "Vérifier les allergies avant tout traitement."],
    }


spec(
    "fever-pathway", agent="FeverAgent", title="Parcours fièvre : synthèse et justification du bilan",
    system=("Un patient hospitalisé présente une FIÈVRE VRAIE (température centrale, critère déterministe fourni). Le médecin de garde est demandé. "
            "Phase « bilan » : rédige une synthèse courte, les points à examiner en priorité, et justifie CHAQUE examen biologique proposé à partir du dossier "
            "(antécédents, dernières valeurs, traitements, allergies). Tu peux suggérer un examen supplémentaire uniquement s'il figure dans `catalogue`. "
            "Phase « resultats » : interprète prudemment les résultats fournis (valeurs et normes citées) et propose la surveillance."),
    format='{"summary": "2 à 3 phrases", "exam_focus": ["point d\'examen clinique"], "labs": [{"code": "CRP", "justification": "pourquoi, pour CE patient"}], "interpretation": "phase resultats uniquement", "watch": ["surveillance"]}',
    required=["summary"], mock=_mock_fever,
)


# ─── ReportAgent : synthèse du dossier médical ───────────────────────────────
def _mock_record_summary(ctx: dict[str, Any]) -> dict[str, Any]:
    p = ctx.get("patient") or {}
    chron = [f"{c['label']} (depuis {c['since']})" for c in ctx.get("maladies_chroniques") or []]
    return {
        "summary": f"{p.get('nom', 'Patient')}, {p.get('age', '?')} ans : {len(chron)} maladie(s) chronique(s) suivie(s), {len(ctx.get('allergies') or [])} allergie(s) documentée(s), "
                   f"{ctx.get('documents_au_dossier', '?')} documents au dossier." + (f" Hospitalisation en cours : {ctx['hospitalisation_en_cours']}." if ctx.get("hospitalisation_en_cours") else ""),
        "allergies": [f"{a['allergen']}" + (f" (documentée en {a['since']})" if a.get("since") else "") for a in ctx.get("allergies") or []] or ["Aucune allergie connue"],
        "chronic": chron or ["Aucune maladie chronique enregistrée"],
        "history": [f"{h['label']} ({h['year']})" for h in ctx.get("antecedents") or []] or ["Aucun antécédent chirurgical ou d'hospitalisation enregistré"],
        "active_treatments": [f"{t['dci']} {t.get('posology', '')}".strip() for t in (ctx.get("traitements_au_long_cours") or [])] + [f"{t['dci']} {t.get('posology', '')} ({t.get('route', '')}, hospitalier)".strip() for t in (ctx.get("traitements_hospitaliers_en_cours") or [])],
        "attention": [f"{v['examen']} {v['valeur']} {v['unite']} le {v['date']} (hors normes)" for v in (ctx.get("dernieres_valeurs_biologiques") or {}).values() if v.get("anormal")][:5]
                     + ([f"Risque de chute {p['risque_de_chute']}"] if p.get("risque_de_chute") in ("high", "medium") else []),
    }


spec(
    "record-summary", agent="ReportAgent", title="Synthèse du dossier médical",
    system=("Tu synthétises le dossier médical d'un patient pour l'équipe soignante, à partir des seuls éléments fournis (extraits déterministes du dossier). "
            "Sois factuel et concis : chaque point cite une date ou une valeur du dossier. Les points d'attention sont ce qu'un soignant doit savoir AVANT d'agir "
            "(allergies, interactions à surveiller, valeurs biologiques hors normes récentes, risque de chute, fragilités)."),
    format='{"summary": "3 à 5 phrases", "allergies": ["..."], "chronic": ["maladie (depuis AAAA)"], "history": ["antécédent (AAAA)"], "active_treatments": ["médicament posologie"], "attention": ["point d\'attention"]}',
    required=["summary"], mock=_mock_record_summary,
)


# ─── DiagnosticsAgent ─────────────────────────────────────────────────────────
def _mock_diagnostics(ctx: dict[str, Any]) -> dict[str, Any]:
    hyps = ctx.get("hypotheses") or []
    lead = hyps[0] if hyps else None
    p = ctx.get("patient") or {}
    if not lead:
        return {"summary": "Aucune hypothèse au-dessus du seuil : surveillance habituelle.", "next_steps": []}
    return {"summary": f"{p.get('nom', 'Patient')} : l'hypothèse la plus étayée est « {lead['label']} » (probabilité {lead['probability']}) — éléments : {'; '.join(lead['pros'][:4])}."
                       + (f" À nuancer : {'; '.join(lead['cons'])}." if lead.get("cons") else ""),
            "next_steps": lead.get("exams", [])[:3]}


spec(
    "diagnostics-live", agent="DiagnosticsAgent", title="Synthèse des hypothèses diagnostiques",
    system=("Tu reçois les hypothèses diagnostiques d'un patient hospitalisé, calculées par des règles déterministes (éléments pour, contre, examens utiles). "
            "Rédige pour le médecin et l'infirmier une synthèse de 3 phrases au plus, puis au plus 4 prochaines étapes concrètes (examens ou surveillances déjà listés). "
            "N'ajoute aucune hypothèse, ne change aucune probabilité, ne conclus pas à un diagnostic."),
    format='{"summary": "3 phrases au plus", "next_steps": ["étape concrète"]}', required=["summary"], mock=_mock_diagnostics,
)


# ─── MedicationAgent ──────────────────────────────────────────────────────────
def _mock_medication(ctx: dict[str, Any]) -> dict[str, Any]:
    if ctx.get("alerte_allergie"):
        return {"vigilance": f"{ctx['alerte_allergie']} — ne pas administrer sans avis médical."}
    if ctx.get("allergies") and ctx["allergies"] != "aucune connue":
        return {"vigilance": f"Allergies connues : {ctx['allergies']}. Vérifier l'identité du patient et le médicament avant l'administration."}
    return {"vigilance": "Vérifier l'identité du patient, la dose et la voie avant l'administration."}


spec(
    "medication-reminders", agent="MedicationAgent", title="Rappel de prise de médicament",
    system=("Un rappel de prise de médicament va être envoyé à l'équipe soignante (le texte du rappel est déjà rédigé par la plateforme). "
            "Ajoute UN point de vigilance utile et court pour cette prise et ce patient : allergie, condition de prise, surveillance après administration. "
            "Si une alerte d'allergie est fournie, c'est le point de vigilance. N'invente ni dose ni horaire."),
    format='{"vigilance": "une phrase"}', required=["vigilance"], max_tokens=4000, mock=_mock_medication,
)


# ─── InterventionAgent ────────────────────────────────────────────────────────
def _mock_intervention(ctx: dict[str, Any]) -> dict[str, Any]:
    r = ctx.get("risque") or {}
    done = [s["etape"] for s in ctx.get("plan_d_action") or [] if s.get("faite")]
    visits = ctx.get("visites") or []
    return {
        "summary": f"{r.get('titre', 'Intervention')} — détecté à {r.get('detecte_a')}, résolu et vérifié à {r.get('resolu_a')}.",
        "context": f"{r.get('titre')} (sévérité {r.get('severite')}) détecté à {r.get('detecte_a')} par {r.get('source')}." + (f" Escaladé à {r['escalade_a']}." if r.get("escalade_a") else ""),
        "intervention": ([f"Prise en charge à {r['pris_en_charge_a']}."] if r.get("pris_en_charge_a") else []) + [f"Visite du personnel de {v['debut']} à {v['fin'] or '—'} ({v['personnes']} personnes)." for v in visits]
                        + ([f"Étapes du plan réalisées : {'; '.join(done)}."] if done else ["Aucune étape du plan n'a été cochée dans la plateforme."]),
        "outcome": f"Revérification : {r.get('verification') or 'critère satisfait'}. Risque clos à {r.get('resolu_a')}.",
        "follow_up": ["Surveillance habituelle des constantes.", "Compléter ce compte rendu si nécessaire avant signature."],
    }


spec(
    "intervention-report", agent="InterventionAgent", title="Brouillon de compte rendu d'intervention",
    system=("Rédige le BROUILLON du compte rendu d'une intervention soignante, uniquement à partir du journal fourni (heures, détection, plan d'action, visites, revérification). "
            "Style factuel et chronologique, avec les heures. Si une information n'est pas dans le journal, écris « non renseigné » : le soignant complétera avant de signer."),
    format='{"summary": "une phrase", "context": "ce qui a été détecté, quand", "intervention": ["action horodatée"], "outcome": "résultat de la revérification", "follow_up": ["suite à donner"]}',
    required=["summary", "intervention"], mock=_mock_intervention,
)


# ─── PsychAgent ───────────────────────────────────────────────────────────────
def _mock_psych(ctx: dict[str, Any]) -> dict[str, Any]:
    troubles = ctx.get("troubles") or {}
    worst = max(troubles.items(), key=lambda kv: kv[1].get("score", 0)) if troubles else ("—", {"niveau": "faible", "facteurs": []})
    return {"explanation": f"Score de bien-être {ctx.get('score_bien_etre')}/100, sous le seuil de {ctx.get('seuil')}. Risque le plus marqué : {worst[0].lower()} ({worst[1].get('niveau')}), "
                           f"porté par : {'; '.join(worst[1].get('facteurs', [])[:4]) or 'facteurs non précisés'}. Il s'agit d'un niveau de risque estimé, pas d'un diagnostic.",
            "conduct": list(ctx.get("conduite_a_tenir_standard") or [])[:4]}


spec(
    "psych-monitoring", agent="PsychAgent", title="Explication du score de bien-être psychologique",
    system=("Le score de bien-être psychologique d'un patient hospitalisé est passé sous le seuil. Les scores par trouble (dépression, anxiété généralisée, insomnie) et leurs facteurs "
            "sont calculés par des règles à partir de questionnaires (PHQ-9, GAD-7, sommeil) et d'observations (expressions, levers nocturnes, sommeil, constantes). "
            "Explique en 3 phrases au plus, pour l'équipe soignante, quels facteurs pèsent le plus, puis propose 3 à 4 conduites à tenir simples et bienveillantes (tu peux reprendre la conduite standard fournie). "
            "Ce n'est JAMAIS un diagnostic : ne nomme pas une maladie comme établie, parle de « risque » et de « signes ». Si des idées suicidaires sont mentionnées, la sécurité du patient passe en premier."),
    format='{"explanation": "3 phrases au plus", "conduct": ["conduite à tenir"]}', required=["explanation"], mock=_mock_psych,
)


# ─── PredictionAgent ──────────────────────────────────────────────────────────
def _mock_prediction(ctx: dict[str, Any]) -> dict[str, Any]:
    conduct = {
        "Crise d'épilepsie": ["Sécuriser l'environnement du lit (barrières, objets éloignés) et rester auprès du patient.", "Vérifier la prise de l'antiépileptique prescrit et prévenir le médecin de garde.", "Noter l'heure de début de tout mouvement anormal ; position latérale de sécurité si crise."],
        "Sepsis / choc septique": ["Recontrôler les constantes toutes les 15 min et recalculer qSOFA et NEWS2.", "Prévenir le médecin de garde ; préparer le bilan (hémocultures, lactates).", "Vérifier la voie veineuse et les allergies avant tout traitement."],
        "Infarctus / événement cardiaque": ["ECG 12 dérivations immédiat et appel du médecin de garde.", "Patient au repos strict, scope, oxygène selon la SpO2.", "Préparer le dosage de troponine ; vérifier allergies et anticoagulants en cours."],
        "Détérioration générale": ["Rapprocher la surveillance (constantes toutes les 15 à 30 min).", "Rechercher la cause : infection, douleur, saignement, détresse respiratoire.", "Prévenir le médecin de garde si le NEWS2 continue de monter."],
        "Complication du diabète": ["Contrôler la glycémie capillaire immédiatement, puis à 15 min.", "Appliquer le protocole de resucrage ou d'hyperglycémie prescrit ; prévenir le médecin.", "Vérifier l'heure du dernier repas et de la dernière dose d'insuline ou d'antidiabétique."],
    }.get(ctx.get("condition"), ["Rapprocher la surveillance et prévenir le médecin de garde."])
    return {"explanation": f"Risque de {str(ctx.get('condition', 'crise')).lower()} estimé à {ctx.get('risque')}/100 ({ctx.get('niveau')}), fenêtre {ctx.get('fenetre_estimee')}, confiance {ctx.get('confiance')}. "
                           f"Facteurs retenus : {'; '.join((ctx.get('facteurs') or [])[:4])}. Estimation de prototype, non validée cliniquement.",
            "conduct": conduct}


spec(
    "crisis-prediction", agent="PredictionAgent", title="Explication d'une prédiction de crise",
    system=("Un score déterministe estime qu'un patient hospitalisé risque une crise (condition, risque sur 100, fenêtre de temps approximative, facteurs fournis). "
            "Explique en 3 phrases au plus pourquoi le risque est à ce niveau en citant les facteurs et les valeurs, puis propose 3 à 4 conduites à tenir concrètes pour l'infirmier et le médecin de garde. "
            "Rappelle que c'est une estimation de prototype, non validée cliniquement. Ne modifie ni le risque ni la fenêtre ; n'annonce pas la crise comme certaine."),
    format='{"explanation": "3 phrases au plus", "conduct": ["conduite à tenir"]}', required=["explanation"], mock=_mock_prediction,
)


# ─── AmbulanceAgent ───────────────────────────────────────────────────────────
def _mock_ambulance(ctx: dict[str, Any]) -> dict[str, Any]:
    m = ctx.get("mission") or {}
    return {"briefing": f"{m.get('patient_name', 'Patient')} ({m.get('age') or '?'} ans) arrive dans environ {m.get('eta_minutes', '?')} min pour {str(m.get('emergency_label', 'une urgence')).lower()} "
                        f"({m.get('severity_label', '')}) : {m.get('reason', '')}. Chambre {m.get('reserved_room')} réservée. Allergies : {ctx.get('allergies') or 'non connues'}.",
            "preparation": ctx.get("preparation_standard") or {"materiel": [], "equipe": [], "examens": []}}


spec(
    "ambulance-dispatch", agent="AmbulanceAgent", title="Briefing d'arrivée d'une ambulance",
    system=("Une ambulance vient de partir avec un patient ; une chambre est réservée à la clinique. À partir de la fiche d'intervention (motif, type d'urgence, gravité, constantes transmises, antécédents et allergies s'ils sont connus) "
            "et de la préparation standard fournie, rédige un briefing de 3 phrases au plus pour l'équipe qui va accueillir le patient, puis la préparation adaptée à CE patient : matériel, équipe à prévenir, examens à anticiper. "
            "Reste dans le cadre de la préparation standard (tu peux l'ordonner et la préciser) ; signale toute allergie ou tout antécédent qui change l'accueil."),
    format='{"briefing": "3 phrases au plus", "preparation": {"materiel": ["..."], "equipe": ["..."], "examens": ["..."]}}', required=["briefing"], mock=_mock_ambulance,
)


# ─── VisionAgent, VitalsAgent, EnvironmentAgent (agents V1 : leur raisonnement passe aussi par n8n) ──────────
def _mock_vision(ctx: dict[str, Any]) -> dict[str, Any]:
    return {"observation": f"{ctx.get('evenement', 'Événement')} en chambre {ctx.get('chambre')} : posture {ctx.get('posture')}, activité {ctx.get('activite')}, expression {ctx.get('expression')}"
                           + (", de nuit" if ctx.get("nuit") else "") + f", {ctx.get('personnes')} personne(s) dans la chambre.", "mood": {"pain": "pain", "sad": "sad", "fear": "anxious"}.get(str(ctx.get("expression")), "neutral")}


spec(
    "vision-watch", agent="VisionAgent", title="Observation comportementale (vision)",
    system=("Le VisionAgent vient de signaler un événement à partir de la caméra d'une chambre (posture, activité, expression, nombre de personnes ; aucune image ne quitte la chambre). "
            "Rédige UNE observation comportementale factuelle de 2 phrases au plus pour les transmissions infirmières, et propose une humeur observée parmi : calm, anxious, pain, sad, agitated, neutral. "
            "Ne déduis rien de médical : décris ce qui est observé."),
    format='{"observation": "2 phrases au plus", "mood": "calm|anxious|pain|sad|agitated|neutral"}', required=["observation"], max_tokens=4000, mock=_mock_vision,
)


def _mock_vitals(ctx: dict[str, Any]) -> dict[str, Any]:
    var = ctx.get("variation_sur_10_min") or {}
    moves = [f"{k} {'+' if v > 0 else ''}{v}" for k, v in var.items() if abs(v) >= 1]
    n = (ctx.get("news2") or {}).get("score")
    return {"reading": f"{ctx.get('alerte', 'Alerte')} en chambre {ctx.get('chambre')}. Sur 10 min : {', '.join(moves) or 'constantes stables'}." + (f" NEWS2 {n}." if n is not None else ""),
            "watch": ["Recontrôler les constantes dans 15 min.", "Prévenir le médecin si la tendance se confirme."]}


spec(
    "vitals-trend", agent="VitalsAgent", title="Lecture de la tendance des constantes",
    system=("Le VitalsAgent vient de lever une alerte sur une constante (seuils déterministes, adaptés au patient). À partir des constantes actuelles, de leur variation sur 10 minutes et du NEWS2, "
            "rédige une lecture de tendance de 2 phrases au plus (ce qui monte, ce qui baisse, depuis quand) et 2 ou 3 points à surveiller. Cite les valeurs. N'interprète pas en diagnostic."),
    format='{"reading": "2 phrases au plus", "watch": ["point à surveiller"]}', required=["reading"], max_tokens=4000, mock=_mock_vitals,
)


def _mock_environment(ctx: dict[str, Any]) -> dict[str, Any]:
    acts = "; ".join(f"{a['equipement']} {a['action']} ({a['motif']})" for a in ctx.get("actions") or [])
    return {"note": f"Chambre {ctx.get('chambre')} : {acts or 'aucune action'}. Mesure de confort, sans effet sur un risque clinique.", "next_check": "Revérifier la température de la chambre dans quelques minutes."}


spec(
    "environment-comfort", agent="EnvironmentAgent", title="Note de confort de la chambre",
    system=("L'EnvironmentAgent vient d'agir sur les équipements d'une chambre (fenêtre, chauffage, climatisation) selon des règles déterministes. "
            "Rédige une note de confort d'une ou deux phrases pour l'équipe : ce qui a été fait et pourquoi (température de la chambre, air extérieur, fragilité du patient), et quand revérifier. "
            "Rappelle que c'est une mesure de confort et non un traitement."),
    format='{"note": "1 à 2 phrases", "next_check": "quand revérifier"}', required=["note"], max_tokens=4000, mock=_mock_environment,
)

# Déclencheurs de chaque workflow (carte des agents : n8n/README.md et GET /api/agents/map)
TRIGGERS = {
    "fever-pathway": "fièvre vraie détectée (température centrale) ; résultats du bilan biologique",
    "record-summary": "bouton « Générer la synthèse » du dossier médical",
    "diagnostics-live": "changement des hypothèses diagnostiques d'un patient (au plus toutes les 2 min)",
    "medication-reminders": "prise due, relance (> 30 min), médecin prévenu (> 60 min)",
    "intervention-report": "risque résolu et vérifié",
    "psych-monitoring": "score de bien-être sous le seuil",
    "crisis-prediction": "prédiction passant à « élevé » ou « critique »",
    "ambulance-dispatch": "départ d'une ambulance",
    "vision-watch": "événement signalé par la vision (lever nocturne, chute, douleur…), au plus toutes les 5 min par chambre",
    "vitals-trend": "alerte sur une constante, au plus toutes les 5 min par chambre",
    "environment-comfort": "action de l'EnvironmentAgent sur un équipement, au plus toutes les 5 min par chambre",
}
V1_WORKFLOWS = [
    {"workflow": "risk-triage", "agent": "RiskAgent", "title": "Explication du risque, plan d'action, alerte, attente d'acquittement, escalade", "trigger": "tout nouveau risque (webhook risk-created)"},
    {"workflow": "risk-verify", "agent": "FollowUpAgent", "title": "Revérification après le passage du soignant", "trigger": "sortie du personnel de la chambre (webhook staff-left)"},
    {"workflow": "shift-report", "agent": "ReportAgent", "title": "Rapport de garde", "trigger": "Cron 07:45 et 19:45, bouton « Générer »"},
    {"workflow": "pharmacy-alerts", "agent": "ReportAgent", "title": "Alertes de stock et de péremption", "trigger": "Cron quotidien 08:00, bouton de la vue Pharmacie"},
]


def agent_map() -> list[dict[str, str]]:
    return V1_WORKFLOWS + [{"workflow": name, "agent": s["agent"], "title": s["title"], "trigger": TRIGGERS.get(name, "")} for name, s in SPECS.items()]
