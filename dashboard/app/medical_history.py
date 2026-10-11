"""
Générateur d'historique médical FICTIF mais cohérent (V2, étape 2).

Pour chaque patient : 5 à 15 ans de consultations, hospitalisations, comptes rendus opératoires, biologie
(avec valeurs), imagerie, vaccinations, allergies, maladies chroniques, antécédents familiaux, traitements
au long cours, ordonnances et évaluations psychologiques — plusieurs dizaines de documents datés, avec
auteur, service et établissement.

Déterministe : la graine vient du code patient (même historique à chaque génération). Cohérent avec le
profil du patient (âge, pathologies et allergies déjà connues de la plateforme). Aucune donnée réelle.
"""

from __future__ import annotations

import json
import random
import zlib
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from .clinical import labs
from .models import LabResult, MedicalRecordEntry, Patient

FACILITIES = ["Clinique HackCure", "Hôpital Charles-Nicolle", "Centre médical El Manar", "Cabinet médical Lafayette", "Polyclinique Les Berges du Lac"]
DOCTORS = {
    "Médecine générale": ["Dr Sami Trabelsi", "Dr Leïla Ayari"], "Cardiologie": ["Dr Hichem Baccouche", "Dr Ines Chebbi"], "Pneumologie": ["Dr Karim Jaziri"],
    "Endocrinologie": ["Dr Rania Hamdi"], "Orthopédie": ["Dr Mehdi Ferjani"], "Rhumatologie": ["Dr Sonia Ghanmi"], "Gériatrie": ["Dr Nour Khelifi"],
    "Radiologie": ["Dr Walid Mabrouk"], "Laboratoire": ["Laboratoire d'analyses — biologiste de garde"], "Psychiatrie": ["Dr Yasmine Dridi"], "Urgences": ["Dr Anis Bouzid"],
    "Chirurgie": ["Dr Mehdi Ferjani", "Dr Fares Kooli"], "Néphrologie": ["Dr Amel Zribi"], "Ophtalmologie": ["Dr Selim Maalej"], "Vaccination": ["Infirmier(ère) de vaccination"],
}

# Profils : mots-clés des antécédents → maladies chroniques, suivis, traitements, biologie de surveillance
CONDITIONS: dict[str, dict[str, Any]] = {
    "hta": {"label": "Hypertension artérielle", "service": "Cardiologie", "treat": [("Amlodipine", "5 mg/j"), ("Ramipril", "5 mg/j")], "labs": ["CREAT", "K", "NA"], "years": (9, 14),
            "follow": "Tension artérielle {sys}/{dia} mmHg au cabinet. Automesure tensionnelle conseillée. Régime peu salé rappelé."},
    "diab": {"label": "Diabète de type 2", "service": "Endocrinologie", "treat": [("Metformine", "850 mg x2/j")], "labs": ["HBA1C", "GLY", "CREAT", "LDL"], "years": (6, 11),
             "follow": "HbA1c à {hba1c} %. Examen des pieds normal. Fond d'œil à programmer. Règles hygiéno-diététiques revues."},
    "arthrose": {"label": "Gonarthrose bilatérale", "service": "Rhumatologie", "treat": [("Paracétamol", "1 g si douleur, max 3/j")], "labs": [], "years": (5, 9),
                 "follow": "Douleurs mécaniques des genoux, périmètre de marche {walk} m. Kinésithérapie prescrite."},
    "insuffisance cardiaque": {"label": "Insuffisance cardiaque à FEVG altérée", "service": "Cardiologie", "treat": [("Bisoprolol", "2,5 mg/j"), ("Furosémide", "40 mg/j")], "labs": ["BNP", "CREAT", "K", "NA"], "years": (4, 8),
                               "follow": "Dyspnée stade NYHA {nyha}. Poids {weight} kg, œdèmes des membres inférieurs {oedema}. FEVG estimée à {fevg} %."},
    "fibrillation": {"label": "Fibrillation atriale", "service": "Cardiologie", "treat": [("Apixaban", "5 mg x2/j")], "labs": ["CREAT", "HB", "PLAQ"], "years": (3, 7),
                     "follow": "Rythme irrégulier à {hr}/min, bien toléré. Score CHA2DS2-VASc à {chads}. Anticoagulation poursuivie, pas de saignement rapporté."},
    "bpco": {"label": "BPCO", "service": "Pneumologie", "treat": [("Tiotropium", "18 µg/j inhalé"), ("Salbutamol", "à la demande")], "labs": ["PH", "PCO2", "HB"], "years": (8, 14),
             "follow": "Dyspnée d'effort stade mMRC {mmrc}. VEMS à {vems} % de la théorique. {exac} exacerbation(s) dans l'année. Sevrage tabagique acquis."},
    "dénutrition": {"label": "Dénutrition protéino-énergétique", "service": "Gériatrie", "treat": [("Compléments nutritionnels oraux", "2/j")], "labs": ["ALB"], "years": (1, 3),
                    "follow": "Poids {weight} kg (perte de {loss} kg en 6 mois). Albuminémie basse. Enrichissement de l'alimentation, suivi diététique."},
    "cognitif": {"label": "Troubles cognitifs légers", "service": "Gériatrie", "treat": [], "labs": ["TSH"], "years": (1, 4),
                 "follow": "MMSE à {mmse}/30. Autonomie conservée pour les actes de la vie quotidienne. Stimulation cognitive conseillée, réévaluation à 6 mois."},
    "ostéoporose": {"label": "Ostéoporose", "service": "Rhumatologie", "treat": [("Acide alendronique", "70 mg/semaine"), ("Calcium + vitamine D", "1/j")], "labs": ["CREAT"], "years": (5, 10),
                    "follow": "T-score fémoral à {tscore}. Pas de nouvelle fracture. Prévention des chutes rappelée, supplémentation vitamino-calcique poursuivie."},
    "épilepsie": {"label": "Épilepsie vasculaire", "service": "Gériatrie", "treat": [("Lévétiracétam", "500 mg x2/j")], "labs": ["CREAT"], "years": (2, 5),
                  "follow": "Pas de crise depuis la dernière consultation. Observance du traitement vérifiée ; conduite à tenir en cas de crise réexpliquée à l'entourage."},
    "anémie": {"label": "Anémie", "service": "Médecine générale", "treat": [("Fer", "80 mg/j")], "labs": ["HB"], "years": (0, 1),
               "follow": "Hémoglobine à {hb} g/dL. Supplémentation martiale, contrôle dans un mois."},
}
FAMILY = ["Père : infarctus du myocarde à 62 ans.", "Mère : diabète de type 2.", "Mère : ostéoporose fracturaire.", "Frère : cancer colorectal à 68 ans.", "Père : accident vasculaire cérébral à 74 ans.",
          "Sœur : hypertension artérielle.", "Mère : maladie d'Alzheimer.", "Père : BPCO post-tabagique."]
SURGERIES = [("Cholécystectomie par cœlioscopie", "Lithiase vésiculaire symptomatique", "Chirurgie"), ("Cure de hernie inguinale", "Hernie inguinale droite", "Chirurgie"),
             ("Chirurgie de la cataracte (œil droit)", "Cataracte sénile", "Ophtalmologie"), ("Appendicectomie", "Appendicite aiguë", "Chirurgie"), ("Arthroscopie du genou", "Lésion méniscale dégénérative", "Orthopédie")]
IMAGING = [("Radiographie thoracique de face", "Pas de foyer parenchymateux. Silhouette cardiaque {cardio}. Culs-de-sac pleuraux libres."),
           ("Échographie abdominale", "Foie de taille normale, homogène. Vésicule {vesic}. Reins de taille normale, sans dilatation des cavités."),
           ("Radiographie des genoux en charge", "Pincement fémoro-tibial interne bilatéral, ostéophytose marginale. Pas de lésion osseuse suspecte."),
           ("Échocardiographie transthoracique", "Ventricule gauche {vg}, FEVG estimée à {fevg} %. Pas de valvulopathie significative."),
           ("Scanner thoracique", "Emphysème centrolobulaire prédominant aux sommets. Pas de nodule suspect. Pas d'épanchement."),
           ("Ostéodensitométrie", "T-score lombaire à {tl}, T-score fémoral à {tf}. Conclusion : {osteo}."),
           ("Radiographie du bassin", "Coxarthrose débutante bilatérale. Pas de fracture visible."), ("ECG 12 dérivations", "Rythme {rhythm}, fréquence {hr}/min, axe normal, pas de trouble de la repolarisation.")]
VACCINES = ["Grippe saisonnière", "Covid-19 (rappel)", "Pneumocoque (VPC13 puis VPP23)", "dTP (rappel)", "Zona"]
PSY = ["Entretien d'évaluation : thymie stable, pas d'idée noire. Sommeil correct. Bonne insertion familiale.",
       "Consultation après hospitalisation : anxiété réactionnelle modérée, inquiétudes sur l'autonomie. Soutien psychologique proposé, pas de traitement médicamenteux.",
       "Évaluation gériatrique : humeur légèrement triste depuis le deuil du conjoint, sans critère d'épisode dépressif caractérisé. Réévaluation à 3 mois."]


def _seed(code: str) -> int:
    return zlib.crc32(code.encode("utf-8"))


def _dt(d: date, rnd: random.Random) -> datetime:
    return datetime(d.year, d.month, d.day, rnd.randint(8, 17), rnd.choice([0, 15, 30, 45]), tzinfo=timezone.utc)


def conditions_of(patient: Patient) -> list[str]:
    hist = (patient.history or "").lower()
    return [k for k in CONDITIONS if k in hist]


def generate(patient: Patient, today: Optional[date] = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Renvoie (documents, résultats biologiques) ; chaque résultat référence son document par `entry_index`."""
    today = today or date.today()
    rnd = random.Random(_seed(patient.code))
    conds = conditions_of(patient)
    span = rnd.randint(9, 15) if conds else rnd.randint(5, 8)
    start = date(today.year - span, rnd.randint(1, 12), rnd.randint(1, 26))
    gp = rnd.choice(DOCTORS["Médecine générale"])
    docs: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    def add(d: date, type_: str, title: str, service: str, content: str, summary: str = "", author: Optional[str] = None, facility: Optional[str] = None, data: Optional[dict] = None) -> int:
        if d >= today:
            d = today - timedelta(days=rnd.randint(20, 60))
        docs.append({"date": _dt(d, rnd), "type": type_, "title": title, "service": service, "author": author or rnd.choice(DOCTORS.get(service, [gp])),
                     "facility": facility or (rnd.choice(FACILITIES) if type_ != "consultation" or service != "Médecine générale" else "Cabinet médical Lafayette"),
                     "summary": summary or content[:140], "content": content, "data": data or {}})
        return len(docs) - 1

    name = f"{patient.first_name} {patient.last_name}"
    add(start, "consultation", "Première consultation — ouverture du dossier", "Médecine générale",
        f"Première consultation de {name}, {'né' if patient.sex == 'M' else 'née'} le {patient.birth_date.strftime('%d/%m/%Y')}. Interrogatoire complet, examen clinique sans particularité notable. "
        f"Groupe sanguin {patient.blood_group}. Allergies déclarées : {patient.allergies or 'aucune'}. Vaccinations à mettre à jour.", author=gp)

    # antécédents familiaux, allergies
    for line in rnd.sample(FAMILY, 2):
        add(start + timedelta(days=rnd.randint(0, 20)), "familial", "Antécédents familiaux", "Médecine générale", line, author=gp)
    for allergy in patient.allergy_list:
        d = start + timedelta(days=rnd.randint(60, 900))
        add(d, "allergie", f"Allergie : {allergy}", "Médecine générale",
            f"Réaction à {allergy} : éruption urticarienne généralisée {rnd.choice(['2 heures', '30 minutes', 'le lendemain'])} après la prise, sans signe de gravité respiratoire. "
            f"Allergie inscrite au dossier : éviction stricte, carte d'allergie remise au patient.", summary=f"Allergie documentée à {allergy} (urticaire).", author=gp, data={"allergen": allergy})

    # maladies chroniques : diagnostic, traitement au long cours, suivi régulier, biologie de surveillance
    state = {"hba1c": 8.1, "sys": 158, "dia": 92, "fevg": 45, "weight": rnd.randint(58, 82), "vems": 52, "hb": 11.4, "bnp": 620, "creat": rnd.randint(68, 92), "mmse": 26, "tscore": -2.9}
    for key in conds:
        c = CONDITIONS[key]
        years_ago = min(span - 1, rnd.randint(*c["years"])) if c["years"][1] else 0
        d0 = date(today.year - years_ago, rnd.randint(1, 12), rnd.randint(1, 26))
        add(d0, "chronique", f"Diagnostic : {c['label']}", c["service"], f"Diagnostic de {c['label'].lower()} retenu après bilan clinique et paraclinique. Prise en charge au long cours initiée, éducation thérapeutique débutée.",
            summary=f"{c['label']} — diagnostic et début du suivi.", data={"condition": c["label"]})
        for dci, poso in c["treat"]:
            add(d0 + timedelta(days=rnd.randint(0, 30)), "traitement", f"Traitement au long cours : {dci}", c["service"], f"{dci} {poso}. Indication : {c['label'].lower()}. Tolérance à surveiller, renouvellement trimestriel.",
                summary=f"{dci} {poso}", data={"dci": dci, "posology": poso, "active": True, "condition": c["label"]})
        n_follow = max(2, min(12, years_ago * rnd.choice([1, 2])))
        for i in range(n_follow):
            d = d0 + timedelta(days=int((today - d0).days * (i + 1) / (n_follow + 1)) + rnd.randint(-12, 12))
            state["hba1c"] = round(max(6.4, state["hba1c"] - rnd.uniform(0.0, 0.25)), 1)
            state["sys"], state["dia"] = max(128, state["sys"] - rnd.randint(0, 4)), max(76, state["dia"] - rnd.randint(0, 2))
            state["fevg"] = max(38, state["fevg"] - rnd.choice([0, 0, 1]))
            state["vems"] = max(38, state["vems"] - rnd.choice([0, 1, 2]))
            txt = c["follow"].format(sys=state["sys"], dia=state["dia"], hba1c=state["hba1c"], walk=rnd.choice([300, 500, 800]), nyha=rnd.choice(["II", "II", "III"]), weight=state["weight"],
                                     oedema=rnd.choice(["absents", "discrets"]), fevg=state["fevg"], hr=rnd.randint(68, 96), chads=rnd.randint(3, 4), mmrc=rnd.choice([2, 3]), vems=state["vems"],
                                     exac=rnd.choice([0, 1, 2]), loss=rnd.randint(3, 6), mmse=state["mmse"], tscore=state["tscore"], hb=state["hb"])
            add(d, "consultation", f"Suivi — {c['label']}", c["service"], txt + " Traitement reconduit.", summary=txt[:140])
            if c["labs"] and i % 2 == 0:
                idx = add(d - timedelta(days=rnd.randint(2, 8)), "biologie", f"Bilan de suivi — {c['label']}", "Laboratoire", "", author="Laboratoire d'analyses — biologiste de garde")
                vals = labs.simulate(c["labs"], "normal", seed=rnd.randint(0, 10**6))
                for v in vals:  # valeurs cohérentes avec la maladie
                    if v["code"] == "HBA1C":
                        v["value"] = state["hba1c"]
                    elif v["code"] == "GLY":
                        v["value"] = round(0.9 + (state["hba1c"] - 5.5) * 0.28, 2)
                    elif v["code"] == "BNP":
                        state["bnp"] = max(280, state["bnp"] + rnd.randint(-90, 60))
                        v["value"] = float(state["bnp"])
                    elif v["code"] == "CREAT":
                        state["creat"] = min(118, state["creat"] + rnd.choice([0, 1, 2]))
                        v["value"] = float(state["creat"])
                    elif v["code"] == "HB" and key in ("anémie", "bpco"):
                        v["value"] = state["hb"] if key == "anémie" else round(rnd.uniform(14.5, 16.8), 1)
                    elif v["code"] == "ALB":
                        v["value"] = float(rnd.randint(28, 33))
                    elif v["code"] == "PCO2":
                        v["value"] = float(rnd.randint(44, 52))
                    v["abnormal"] = labs.is_abnormal(v["code"], v["value"])
                _lab_doc(docs[idx], vals)
                results += [{**v, "entry_index": idx} for v in vals]

    # médecine générale : consultations intercurrentes, bilans annuels, ordonnances de renouvellement, vaccins
    for year in range(start.year, today.year + 1):
        for _ in range(rnd.randint(1, 3)):
            d = date(year, rnd.randint(1, 12), rnd.randint(1, 26))
            if d <= start:
                continue
            motif, txt = rnd.choice([
                ("Rhinopharyngite", "Rhinorrhée et toux depuis 3 jours, apyrétique. Auscultation pulmonaire libre. Traitement symptomatique."),
                ("Lombalgie commune", "Douleur lombaire mécanique sans irradiation ni déficit. Antalgiques de palier 1, maintien de l'activité."),
                ("Renouvellement et contrôle", f"Patient en bon état général. TA {rnd.randint(124, 148)}/{rnd.randint(72, 88)} mmHg, FC {rnd.randint(62, 84)}/min. Traitements bien tolérés."),
                ("Gastro-entérite aiguë", "Diarrhée et nausées depuis 48 h, pas de signe de déshydratation. Réhydratation orale, régime adapté."),
                ("Bilan de chute", "Chute mécanique à domicile sans perte de connaissance. Pas de fracture clinique. Évaluation du risque de chute, aménagement du domicile conseillé."),
                ("Infection urinaire basse", "Brûlures mictionnelles, bandelette positive. Traitement adapté aux allergies connues du patient."),
            ])
            add(d, "consultation", f"Consultation — {motif}", "Médecine générale", txt, author=gp)
        d = date(year, rnd.randint(2, 11), rnd.randint(1, 26))
        if d > start:
            idx = add(d, "biologie", "Bilan biologique annuel", "Laboratoire", "", author="Laboratoire d'analyses — biologiste de garde")
            vals = labs.simulate(["HB", "LEUCO", "PLAQ", "CREAT", "NA", "K", "GLY", "LDL", "ASAT", "ALAT", "TSH", "CRP"], "normal", seed=rnd.randint(0, 10**6))
            if "diab" in conds:
                next(v for v in vals if v["code"] == "GLY").update(value=round(0.9 + (state["hba1c"] - 5.5) * 0.28, 2), abnormal=True)
            _lab_doc(docs[idx], vals)
            results += [{**v, "entry_index": idx} for v in vals]
        active = [f"{dci} {poso}" for k in conds for dci, poso in CONDITIONS[k]["treat"]]
        if active and date(year, 6, 1) > start:
            add(date(year, rnd.randint(1, 12), rnd.randint(1, 26)), "ordonnance", f"Ordonnance de renouvellement {year}", "Médecine générale",
                "Renouvellement pour 3 mois :\n" + "\n".join(f"- {a}" for a in active), summary=f"{len(active)} médicament(s) renouvelé(s)", author=gp, data={"lines": active})
        if date(year, 10, 15) > start:
            add(date(year, 10, rnd.randint(5, 28)), "vaccination", "Vaccination — Grippe saisonnière", "Vaccination", f"Vaccin antigrippal saison {year}-{year + 1}, voie intramusculaire, deltoïde gauche. Pas de réaction immédiate.",
                summary="Grippe saisonnière", data={"vaccine": "Grippe saisonnière"})
    for vac in rnd.sample(VACCINES[1:], 3):
        add(date(rnd.randint(start.year, today.year - 1), rnd.randint(1, 12), rnd.randint(1, 26)), "vaccination", f"Vaccination — {vac}", "Vaccination", f"{vac} : injection réalisée, lot enregistré, carnet de vaccination mis à jour.", summary=vac, data={"vaccine": vac})

    # imagerie
    for title, body in rnd.sample(IMAGING, rnd.randint(4, 6)):
        d = date(rnd.randint(start.year, today.year), rnd.randint(1, 12), rnd.randint(1, 26))
        txt = body.format(cardio=rnd.choice(["normale", "modérément élargie"]), vesic=rnd.choice(["alithiasique", "lithiasique, non compliquée"]), vg=rnd.choice(["non dilaté", "discrètement dilaté"]),
                          fevg=state["fevg"], tl=round(rnd.uniform(-3.1, -1.4), 1), tf=state["tscore"], osteo=rnd.choice(["ostéoporose", "ostéopénie"]), rhythm=rnd.choice(["sinusal", "irrégulier"]), hr=rnd.randint(62, 92))
        add(d, "imagerie", title, "Radiologie", f"Indication : bilan de suivi.\nRésultat : {txt}\nConclusion : examen comparé aux précédents, pas d'élément aigu.", summary=txt[:140])

    # hospitalisations et interventions
    for title, indic, service in rnd.sample(SURGERIES, rnd.randint(1, 2)):
        d = date(rnd.randint(start.year, today.year - 1), rnd.randint(1, 12), rnd.randint(1, 24))
        stay = rnd.randint(1, 4)
        add(d, "hospitalisation", f"Hospitalisation — {indic}", service, f"Admission programmée pour {indic.lower()}. Séjour de {stay} jour(s). Suites simples. Sortie à domicile avec ordonnance et consignes.",
            summary=f"Séjour de {stay} jour(s) pour {indic.lower()}.", facility="Clinique HackCure", data={"days": stay, "reason": indic})
        add(d + timedelta(days=1), "operation", f"Compte rendu opératoire — {title}", service,
            f"Indication : {indic}.\nAnesthésie : {rnd.choice(['générale', 'locorégionale'])}. Antibioprophylaxie adaptée aux allergies ({patient.allergies or 'aucune allergie connue'}).\n"
            f"Geste : {title.lower()} réalisée sans incident. Pertes sanguines négligeables. Durée : {rnd.randint(35, 95)} min.\nSuites : réveil sans complication, reprise de l'alimentation le jour même.",
            summary=f"{title} — sans incident.", facility="Clinique HackCure")
    for key in conds[:2]:
        c = CONDITIONS[key]
        d = date(rnd.randint(max(start.year, today.year - 4), today.year - 1), rnd.randint(1, 12), rnd.randint(1, 24))
        stay = rnd.randint(3, 9)
        add(d, "hospitalisation", f"Hospitalisation — décompensation ({c['label']})", c["service"],
            f"Hospitalisation de {stay} jours pour décompensation de {c['label'].lower()}. Évolution favorable sous traitement. Traitement de fond adapté à la sortie, consultation de contrôle à un mois.",
            summary=f"{stay} jours pour {c['label'].lower()}.", facility="Clinique HackCure", data={"days": stay, "reason": c["label"]})

    # psychologie
    for txt in rnd.sample(PSY, rnd.randint(1, 2)):
        add(date(rnd.randint(max(start.year, today.year - 5), today.year), rnd.randint(1, 12), rnd.randint(1, 26)), "psychologie", "Évaluation psychologique", "Psychiatrie", txt)

    order = sorted(range(len(docs)), key=lambda i: docs[i]["date"])
    remap = {old: new for new, old in enumerate(order)}
    docs = [docs[i] for i in order]
    for r in results:
        r["entry_index"] = remap[r["entry_index"]]
    return docs, results


def _lab_doc(doc: dict[str, Any], vals: list[dict[str, Any]]) -> None:
    abn = [v for v in vals if v["abnormal"]]
    doc["content"] = "\n".join(f"- {v['label']} : {v['value'] if v['value'] is not None else v['text']} {v['unit']}".rstrip() + (f" (normes {labs.norm_text(v['code'])})" if v["value"] is not None else "") + (" ⚠" if v["abnormal"] else "") for v in vals)
    doc["summary"] = (f"{len(abn)} valeur(s) hors normes : " + ", ".join(f"{v['label']} {v['value']} {v['unit']}" for v in abn[:4])) if abn else "Toutes les valeurs sont dans les normes."
    doc["data"] = {"results": vals}


def ensure_history(session: Session) -> int:
    """Génère l'historique des patients qui n'en ont pas encore. Renvoie le nombre de documents créés."""
    created = 0
    for p in session.exec(select(Patient)).all():
        if session.exec(select(MedicalRecordEntry.id).where(MedicalRecordEntry.patient_pk == p.id, MedicalRecordEntry.source == "historique").limit(1)).first():
            continue
        docs, results = generate(p)
        rows = []
        for d in docs:
            row = MedicalRecordEntry(patient_pk=p.id, type=d["type"], date=d["date"], title=d["title"], author=d["author"], service=d["service"], facility=d["facility"], summary=d["summary"],
                                     content=d["content"], data_json=json.dumps(d["data"], ensure_ascii=False), source="historique")
            session.add(row)
            rows.append(row)
        session.flush()
        for r in results:
            row = rows[r["entry_index"]]
            session.add(LabResult(patient_pk=p.id, entry_id=row.id, code=r["code"], label=r["label"], value=r["value"], text=r["text"], unit=r["unit"], ref_low=r["ref_low"], ref_high=r["ref_high"],
                                  abnormal=r["abnormal"], date=row.date))
        created += len(rows)
    session.commit()
    return created
