"""
Hypothèses diagnostiques « live » (V2, étape 4) — règles déterministes et transparentes.

Chaque hypothèse reçoit un score à partir d'éléments observables (constantes, scores NEWS2 / qSOFA, vision,
biologie récente, antécédents et traitements du dossier). Le score donne une probabilité QUALITATIVE
(faible / modérée / élevée) et la liste des éléments pour, des éléments contre et des examens utiles.
Ce ne sont pas des diagnostics : le médecin confirme, rejette ou annote.
"""

from __future__ import annotations

from typing import Any, Optional


def _has(text: str, *keys: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in keys)


def _lab(labs: dict[str, dict[str, Any]], code: str) -> Optional[float]:
    v = labs.get(code)
    return v.get("value") if v else None


def probability(score: float) -> str:
    return "élevée" if score >= 6 else ("modérée" if score >= 3 else "faible")


def hypotheses(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """`ctx` : vitals, news2, qsofa, posture, expression, history, treatments, labs {code: {value, date, abnormal}}, open_risks [types], age.
    Renvoie les hypothèses de score ≥ 2, triées par score décroissant."""
    v = ctx.get("vitals") or {}
    labs = ctx.get("labs") or {}
    hist, tr = ctx.get("history") or "", ctx.get("treatments") or ""
    risks = set(ctx.get("open_risks") or [])
    temp, hr, rr, sys_, spo2, glu = v.get("tempC"), v.get("hr"), v.get("rr"), v.get("sys"), v.get("spo2"), v.get("glucose")
    news2, qsofa = ctx.get("news2"), ctx.get("qsofa") or 0
    out: list[dict[str, Any]] = []

    def hyp(code: str, label: str, items: list[tuple[bool, float, str]], contra: list[tuple[bool, str]], exams: list[str]) -> None:
        pros = [(w, txt) for ok, w, txt in items if ok]
        score = sum(w for w, _ in pros)
        cons = [txt for ok, txt in contra if ok]
        score -= 0.5 * len(cons)
        if score >= 2:
            out.append({"code": code, "label": label, "score": round(score, 1), "probability": probability(score), "pros": [t for _, t in pros], "cons": cons, "exams": exams})

    crp, pct, leuco, lact = _lab(labs, "CRP"), _lab(labs, "PCT"), _lab(labs, "LEUCO"), _lab(labs, "LACT")
    fever = temp is not None and temp >= 38.0
    hyp("sepsis", "Infection sévère / sepsis", [
        (fever, 2, f"température centrale {temp} °C"), (qsofa >= 2, 3, f"qSOFA {qsofa}/3"), (qsofa == 1, 1, "qSOFA 1/3"),
        (news2 is not None and news2 >= 5, 2, f"NEWS2 {news2}"), (hr is not None and hr >= 110, 1, f"FC {hr:.0f}/min" if hr else ""),
        (sys_ is not None and sys_ <= 100, 2, f"PAS {sys_:.0f} mmHg" if sys_ else ""), (lact is not None and lact > 2, 2, f"lactates {lact} mmol/L"),
        (pct is not None and pct > 0.5, 2, f"procalcitonine {pct} ng/mL"), (crp is not None and crp > 50, 1, f"CRP {crp:.0f} mg/L" if crp else ""),
        ("sepsis_trend" in risks, 1, "tendance évocatrice détectée par le VitalsAgent"),
    ], [(temp is not None and temp < 37.8 and qsofa == 0, "apyrétique, qSOFA 0"), (pct is not None and pct <= 0.5 and crp is not None and crp <= 20, "CRP et procalcitonine basses")],
        ["Hémocultures", "Lactates", "NFS, CRP, procalcitonine", "ECBU", "Radiographie thoracique"])

    hyp("pneumonia", "Infection respiratoire basse", [
        (fever, 2, f"fièvre {temp} °C"), (spo2 is not None and spo2 < 94, 2, f"SpO2 {spo2:.0f} %" if spo2 else ""), (rr is not None and rr >= 22, 1, f"FR {rr:.0f}/min" if rr else ""),
        (_has(hist, "bpco", "pneumopathie") or _has(ctx.get("admission_reason") or "", "pneumopath"), 2, "contexte respiratoire au dossier (BPCO ou pneumopathie)"),
        (leuco is not None and leuco > 10, 1, f"leucocytes {leuco} G/L"), (crp is not None and crp > 50, 1, f"CRP {crp:.0f} mg/L" if crp else ""),
    ], [(spo2 is not None and spo2 >= 96 and (rr or 16) < 20, "SpO2 et fréquence respiratoire normales")], ["Radiographie thoracique", "Gaz du sang si SpO2 basse", "Antigénuries, ECBC"])

    bnp = _lab(labs, "BNP")
    hyp("heart_failure", "Décompensation cardiaque", [
        (_has(hist, "insuffisance cardiaque"), 3, "insuffisance cardiaque connue"), (spo2 is not None and spo2 < 94, 1, f"SpO2 {spo2:.0f} %" if spo2 else ""),
        (rr is not None and rr >= 22, 1, f"FR {rr:.0f}/min" if rr else ""), (hr is not None and hr >= 110, 1, f"FC {hr:.0f}/min" if hr else ""),
        (bnp is not None and bnp > 400, 2, f"NT-proBNP {bnp:.0f} pg/mL" if bnp else ""), (_has(hist, "fibrillation"), 1, "fibrillation atriale"),
    ], [(fever, "fièvre : rechercher d'abord une cause infectieuse")], ["NT-proBNP", "ECG", "Échocardiographie", "Ionogramme, créatinine", "Radiographie thoracique"])

    hyp("copd", "Exacerbation de BPCO", [
        (_has(hist, "bpco"), 3, "BPCO connue"), (spo2 is not None and spo2 < 88, 2, f"SpO2 {spo2:.0f} % (cible 88–92 %)" if spo2 else ""),
        (rr is not None and rr >= 24, 2, f"FR {rr:.0f}/min" if rr else ""), (fever, 1, "fièvre (surinfection ?)"),
    ], [(spo2 is not None and spo2 >= 90 and (rr or 16) < 22, "SpO2 dans la cible, FR normale")], ["Gaz du sang (pH, PaCO2)", "Radiographie thoracique", "ECBC si expectoration purulente"])

    hb = _lab(labs, "HB")
    hyp("bleeding", "Hypovolémie / saignement", [
        (sys_ is not None and sys_ < 95, 2, f"PAS {sys_:.0f} mmHg" if sys_ else ""), (hr is not None and hr >= 110, 2, f"FC {hr:.0f}/min" if hr else ""),
        (_has(tr, "énoxaparine", "enoxaparine", "apixaban", "warfarine", "héparine"), 1, "sous anticoagulant"), (_has(hist, "opér", "post-op", "anémie"), 1, "contexte post-opératoire ou anémie"),
        (hb is not None and hb < 10, 2, f"hémoglobine {hb} g/dL"), ("fall" in risks, 1, "chute récente"),
    ], [(fever, "fièvre : évoque plutôt une cause infectieuse")], ["NFS en urgence", "Groupe, RAI", "TP, INR", "Recherche d'un saignement extériorisé"])

    diabetic = _has(hist, "diab") or _has(tr, "metformine", "insuline")
    hyp("hypoglycemia", "Hypoglycémie", [
        (glu is not None and glu < 0.7, 4, f"glycémie capillaire {glu} g/L"), (diabetic, 1, "patient diabétique traité"), (hr is not None and hr >= 100, 1, "tachycardie"),
        (ctx.get("expression") in ("fear", "pain", "sad") and glu is not None and glu < 0.8, 1, "malaise visible"),
    ], [(glu is not None and glu >= 0.8, f"glycémie {glu} g/L")], ["Glycémie capillaire de contrôle à 15 min", "Révision du traitement antidiabétique"])
    hyp("hyperglycemia", "Déséquilibre hyperglycémique / acidocétose", [
        (glu is not None and glu >= 2.5, 3, f"glycémie capillaire {glu} g/L"), (glu is not None and glu >= 3.0, 1, "glycémie ≥ 3 g/L"), (diabetic, 1, "patient diabétique"),
        (rr is not None and rr >= 24, 1, "polypnée"), (fever, 1, "fièvre (facteur déclenchant)"),
    ], [], ["Cétonémie capillaire", "Gaz du sang, ionogramme", "ECBU, recherche d'un foyer"])

    hyp("trauma", "Traumatisme après chute", [
        ("fall" in risks, 4, "chute détectée"), (ctx.get("posture") == "on_floor", 1, "patient au sol"), (ctx.get("expression") == "pain", 1, "douleur visible"),
        (_has(tr, "énoxaparine", "enoxaparine", "apixaban", "warfarine"), 1, "sous anticoagulant (risque hémorragique)"), (_has(hist, "ostéoporose"), 1, "ostéoporose"),
    ], [], ["Examen clinique complet avant mobilisation", "Imagerie selon l'examen (hanche, crâne)", "Surveillance neurologique"])

    return sorted(out, key=lambda h: -h["score"])


# Interactions médicamenteuses simples (prototype) : paires de mots-clés de DCI → message
INTERACTIONS = [
    (("apixaban", "énoxaparine", "enoxaparine", "warfarine", "héparine"), ("ibuprofène", "kétoprofène", "diclofénac", "aspirine", "acide acétylsalicylique"), "Anticoagulant + AINS / aspirine : risque hémorragique majoré."),
    (("apixaban", "warfarine"), ("énoxaparine", "enoxaparine", "héparine"), "Deux anticoagulants associés : risque hémorragique — vérifier le relais."),
    (("ramipril", "énalapril", "périndopril"), ("potassium", "spironolactone"), "IEC + potassium / épargneur potassique : risque d'hyperkaliémie."),
    (("tramadol",), ("sertraline", "paroxétine", "fluoxétine", "escitalopram"), "Tramadol + ISRS : risque de syndrome sérotoninergique."),
    (("bisoprolol", "aténolol"), ("vérapamil", "diltiazem"), "Bêtabloquant + inhibiteur calcique bradycardisant : risque de bradycardie."),
    (("tramadol", "morphine", "oxycodone"), ("diazépam", "lorazépam", "alprazolam", "zolpidem"), "Opioïde + benzodiazépine : risque de dépression respiratoire."),
    (("metformine",), ("produit de contraste iodé",), "Metformine + produit de contraste iodé : suspendre la metformine 48 h."),
]


def interactions(new_dci: str, current: list[str]) -> list[str]:
    """Messages d'interaction entre un médicament à prescrire et les traitements en cours."""
    n = (new_dci or "").lower()
    cur = [c.lower() for c in current if c]
    out = []
    for a, b, msg in INTERACTIONS:
        for x, y in ((a, b), (b, a)):
            if any(k in n for k in x):
                hit = next((c for c in cur if any(k in c for k in y)), None)
                if hit and msg not in out:
                    out.append(f"{msg} (avec {hit})")
    return out
