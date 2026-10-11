"""
État psychologique (V2, étape 7) — questionnaires d'admission et score continu, règles déterministes.

Trois troubles fréquents pour le prototype :
- dépression : **PHQ-9** (9 items, 0–27) ;
- anxiété généralisée : **GAD-7** (7 items, 0–21) ;
- insomnie / troubles du sommeil : court questionnaire **rédigé pour ce projet** (6 items, 0–18).

Sécurité : toute réponse positive à l'item 9 du PHQ-9 (idées de mort ou d'automutilation) déclenche une alerte
immédiate, quel que soit le score total.

Le score continu combine questionnaires, expressions du visage, levers et passages aux toilettes la nuit,
sommeil, constantes et antécédents. Ce n'est JAMAIS un diagnostic : un niveau de risque et ses facteurs.
"""

from __future__ import annotations

from typing import Any, Optional

SCALE = ["Jamais", "Plusieurs jours", "Plus de la moitié du temps", "Presque tous les jours"]
INTRO = "Au cours des deux dernières semaines, à quelle fréquence avez-vous été gêné(e) par les problèmes suivants ?"

QUESTIONNAIRES: dict[str, dict[str, Any]] = {
    "phq9": {"title": "Humeur", "name": "PHQ-9", "intro": INTRO, "items": [
        "Peu d'intérêt ou de plaisir à faire les choses",
        "Être triste, déprimé(e) ou désespéré(e)",
        "Difficultés à s'endormir ou à rester endormi(e), ou dormir trop",
        "Se sentir fatigué(e) ou manquer d'énergie",
        "Avoir peu d'appétit ou manger trop",
        "Avoir une mauvaise opinion de soi-même, ou avoir le sentiment d'être nul(le), ou d'avoir déçu sa famille ou s'être déçu(e) soi-même",
        "Avoir du mal à se concentrer, par exemple pour lire le journal ou regarder la télévision",
        "Bouger ou parler si lentement que les autres auraient pu le remarquer ; ou au contraire être si agité(e) que vous avez eu du mal à tenir en place",
        "Penser qu'il vaudrait mieux mourir, ou envisager de vous faire du mal d'une manière ou d'une autre",
    ]},
    "gad7": {"title": "Inquiétudes", "name": "GAD-7", "intro": INTRO, "items": [
        "Un sentiment de nervosité, d'anxiété ou de tension",
        "Une incapacité à arrêter de s'inquiéter ou à contrôler ses inquiétudes",
        "Une inquiétude excessive à propos de différentes choses",
        "Des difficultés à se détendre",
        "Une agitation telle qu'il est difficile de rester tranquille",
        "Une tendance à être facilement contrarié(e) ou irritable",
        "Un sentiment de peur, comme si quelque chose de terrible risquait de se produire",
    ]},
    # Questionnaire de sommeil rédigé pour Hospital Copilot (aucun questionnaire protégé n'est reproduit)
    "sleep": {"title": "Sommeil", "name": "Sommeil (Hospital Copilot)", "intro": "Ces dernières nuits, à quelle fréquence cela vous est-il arrivé ?", "items": [
        "Mettre plus d'une demi-heure à m'endormir",
        "Me réveiller plusieurs fois dans la nuit",
        "Me réveiller trop tôt sans pouvoir me rendormir",
        "Me sentir fatigué(e) au réveil, comme si je n'avais pas dormi",
        "Somnoler dans la journée ou avoir du mal à rester éveillé(e)",
        "M'inquiéter le soir à l'idée de mal dormir",
    ]},
}


def score_answers(answers: dict[str, list[int]]) -> dict[str, Any]:
    """`answers` : {phq9: [0..3]*9, gad7: [0..3]*7, sleep: [0..3]*6}. Renvoie totaux, niveaux et l'alerte de l'item 9."""
    def total(key: str) -> int:
        vals = answers.get(key) or []
        if len(vals) != len(QUESTIONNAIRES[key]["items"]) or any(not isinstance(v, int) or v < 0 or v > 3 for v in vals):
            raise ValueError(f"réponses incomplètes ou invalides pour {key}")
        return sum(vals)

    phq, gad, sl = total("phq9"), total("gad7"), total("sleep")
    return {
        "phq9": {"score": phq, "max": 27, "level": "sévère" if phq >= 20 else "modérément sévère" if phq >= 15 else "modéré" if phq >= 10 else "léger" if phq >= 5 else "minimal"},
        "gad7": {"score": gad, "max": 21, "level": "sévère" if gad >= 15 else "modéré" if gad >= 10 else "léger" if gad >= 5 else "minimal"},
        "sleep": {"score": sl, "max": 18, "level": "sévère" if sl >= 11 else "modéré" if sl >= 6 else "léger" if sl >= 3 else "minimal"},
        "q9": int(answers["phq9"][8]), "q9_positive": answers["phq9"][8] > 0,
    }


def _level(score: float) -> str:
    return "élevé" if score >= 60 else ("modéré" if score >= 35 else "faible")


def compute(inp: dict[str, Any]) -> dict[str, Any]:
    """Score continu. `inp` : questionnaire (résultat de score_answers ou None), expr {sad, pain, fear, total},
    night_exits, night_toilets, sleep_hours (None si inconnu), vitals {hr, sys, tempC}, history (texte), pain_risk (bool).
    Renvoie {wellbeing 0–100, depression / anxiety / insomnia : {score 0–100, level, factors}}."""
    q = inp.get("questionnaire") or {}
    expr = inp.get("expr") or {}
    n = max(1, int(expr.get("total") or 0))
    sad, pain, fear = (expr.get(k, 0) / n for k in ("sad", "pain", "fear"))
    hist = (inp.get("history") or "").lower()
    v = inp.get("vitals") or {}
    exits, toilets, sleep_h = int(inp.get("night_exits") or 0), int(inp.get("night_toilets") or 0), inp.get("sleep_hours")
    beh = inp.get("behavior") or {}  # analyse comportementale de la vision (optionnelle) : nombre d'observations par indicateur
    agit, immob = int(beh.get("agitation") or 0), int(beh.get("immobility") or 0)

    def build(parts: list[tuple[float, str]]) -> dict[str, Any]:
        used = [(w, t) for w, t in parts if w > 0]
        score = min(100.0, sum(w for w, _ in used))
        return {"score": round(score), "level": _level(score), "factors": [t for _, t in sorted(used, key=lambda x: -x[0])]}

    phq, gad, sl = (q.get(k, {}).get("score") for k in ("phq9", "gad7", "sleep"))
    dep = build([
        ((phq / 27 * 70) if phq is not None else 0, f"PHQ-9 à {phq}/27 ({q.get('phq9', {}).get('level')})" if phq is not None else ""),
        (25 if q.get("q9_positive") else 0, "idées de mort ou d'automutilation déclarées (item 9)"),
        (min(20, sad * 60) if sad >= 0.15 else 0, f"expression de tristesse sur {sad:.0%} des observations"),
        (8 if sleep_h is not None and sleep_h < 5 else 0, f"sommeil court (≈ {sleep_h:.1f} h)" if sleep_h is not None else ""),
        (10 if any(k in hist for k in ("dépress", "deuil", "humeur")) else 0, "antécédent dépressif ou deuil au dossier"),
        (6 if pain >= 0.25 else 0, f"douleur visible sur {pain:.0%} des observations"),
        (6 if immob >= 3 else 0, f"immobilité prolongée observée {immob} fois (analyse comportementale)"),
    ])
    anx = build([
        ((gad / 21 * 70) if gad is not None else 0, f"GAD-7 à {gad}/21 ({q.get('gad7', {}).get('level')})" if gad is not None else ""),
        (min(20, fear * 70) if fear >= 0.12 else 0, f"expression de peur sur {fear:.0%} des observations"),
        (min(14, exits * 5), f"{exits} lever(s) nocturne(s)"),
        (8 if (v.get("hr") or 0) >= 100 else 0, f"fréquence cardiaque {v.get('hr'):.0f}/min" if v.get("hr") else ""),
        (6 if (v.get("sys") or 0) >= 160 else 0, f"pression artérielle {v.get('sys'):.0f} mmHg" if v.get("sys") else ""),
        (10 if "anxi" in hist else 0, "antécédent anxieux au dossier"),
        (min(12, agit * 4) if agit >= 2 else 0, f"agitation observée {agit} fois (analyse comportementale)"),
    ])
    ins = build([
        ((sl / 18 * 65) if sl is not None else 0, f"questionnaire de sommeil à {sl}/18 ({q.get('sleep', {}).get('level')})" if sl is not None else ""),
        (min(22, (exits + toilets) * 5.5), f"{exits} lever(s) et {toilets} passage(s) aux toilettes la nuit"),
        ((20 if sleep_h < 4 else 12 if sleep_h < 5.5 else 0) if sleep_h is not None else 0, f"sommeil estimé à ≈ {sleep_h:.1f} h" if sleep_h is not None else ""),
        (6 if (v.get("tempC") or 0) >= 38.0 else 0, "fièvre (sommeil perturbé)"),
        (6 if pain >= 0.25 else 0, "douleur visible"),
    ])
    worst = max(dep["score"], anx["score"], ins["score"])
    mean = (dep["score"] + anx["score"] + ins["score"]) / 3
    wellbeing = round(max(0.0, 100 - (0.65 * worst + 0.35 * mean)))
    return {"wellbeing": wellbeing, "depression": dep, "anxiety": anx, "insomnia": ins, "q9_positive": bool(q.get("q9_positive")),
            "level": "élevé" if wellbeing < 45 else ("modéré" if wellbeing < 65 else "faible")}


CONDUCT = {
    "depression": ["Entretien d'écoute par l'infirmier(ère) ; noter les propos du patient.", "Signaler au psychiatre et au médecin ; évaluation clinique à programmer.", "Favoriser les visites et les activités ; surveiller l'alimentation et le sommeil."],
    "anxiety": ["Réassurance, information claire sur les soins prévus.", "Techniques de relaxation ou de respiration ; limiter les stimulations le soir.", "Signaler au psychiatre si l'anxiété persiste ou gêne les soins."],
    "insomnia": ["Hygiène de sommeil : lumière tamisée, bruit réduit, regrouper les soins de nuit.", "Rechercher une cause : douleur, fièvre, envie d'uriner, inquiétude.", "Signaler au médecin si le sommeil reste très court malgré ces mesures."],
}
Q9_CONDUCT = ["Ne pas laisser le patient seul ; rester à son écoute.", "Prévenir immédiatement le psychiatre et le médecin de garde.", "Sécuriser l'environnement de la chambre (objets dangereux, médicaments).", "Évaluation psychiatrique du risque suicidaire dans les meilleurs délais."]
LABELS = {"depression": "Dépression", "anxiety": "Anxiété généralisée", "insomnia": "Insomnie / troubles du sommeil"}


def conduct(result: dict[str, Any]) -> list[str]:
    if result.get("q9_positive"):
        return list(Q9_CONDUCT)
    worst = max(("depression", "anxiety", "insomnia"), key=lambda k: result[k]["score"])
    return list(CONDUCT[worst])
