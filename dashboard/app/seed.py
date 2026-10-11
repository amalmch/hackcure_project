"""
Jeu de données de démonstration (section 5 du PROMPT) — données patients FICTIVES.
Idempotent : ne réinsère pas si les chambres existent déjà ; resynchronise toujours
l'état « legacy » (`state.patients`) depuis les admissions actives.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from . import state
from .auth import ROLES, hash_password
from .config import settings
from .db import session_scope
from .models import (
    Admission,
    Medication,
    MedicalDevice,
    MedicalReport,
    Patient,
    Prescription,
    PrescriptionLine,
    Room,
    RoomEquipment,
    Staff,
    Treatment,
    User,
    utcnow,
)

logger = logging.getLogger("hackcure.seed")

DEVICE_TYPES = ["iv_pump", "nutrition_pump", "transfusion", "bp", "ecg", "oxygen", "spo2", "thermometer", "glucometer"]
DEVICE_LABELS = {
    "glucometer": "Glucomètre (glycémie capillaire)",
    "iv_pump": "Pompe à perfusion",
    "nutrition_pump": "Pompe de nutrition",
    "transfusion": "Transfusion",
    "bp": "Tensiomètre",
    "ecg": "ECG",
    "oxygen": "Oxygène",
    "spo2": "Oxymètre SpO2",
    "thermometer": "Thermomètre",
}

# Comptes de démo : 1 utilisateur par rôle (mot de passe commun : DEMO_PASSWORD)
DEMO_USERS = [
    ("pharmacien", "pharmacist", "Leïla Haddad"),
    ("receptionniste", "receptionist", "Karim Jaziri"),
    ("infirmier", "nurse", "Sami Trabelsi"),
    ("medecin_garde", "duty_doctor", "Dr Nour Khelifi"),
    ("medecin", "general_doctor", "Dr Youssef Mansour"),
    ("owner", "owner", "Dr Amira Ben Ammar"),
    ("psychiatre", "psychiatrist", "Dr Yasmine Dridi"),
]


def _birth(age: int, month: int = 5, day: int = 14) -> date:
    return date(date.today().year - age, month, day)


PATIENTS = [
    # patient_id, display_name, âge, prénom, nom, sexe, allergies, groupe, risque chute, antécédents, motif
    ("patient_01", "Patient A", 72, "Mohamed", "Ben Salah", "M", "", "A+", "high",
     "HTA, diabète de type 2, arthrose des genoux, chute à domicile en 2025", "Pneumopathie communautaire"),
    ("patient_02", "Patient B", 68, "Fatma", "Gharbi", "F", "pénicilline", "O-", "medium",
     "Insuffisance cardiaque (FEVG 40 %), fibrillation atriale sous anticoagulant", "Décompensation cardiaque"),
    ("patient_03", "Patient C", 81, "Ali", "Mezghani", "M", "iode", "B+", "high",
     "BPCO stade III sous oxygène, dénutrition, troubles cognitifs légers, épilepsie vasculaire sous lévétiracétam", "Exacerbation de BPCO"),
    ("patient_04", "Patient D", 75, "Zohra", "Chaabane", "F", "AINS, aspirine", "AB+", "medium",
     "Ostéoporose, fracture du col fémoral opérée (J+4), anémie post-opératoire", "Suites de prothèse de hanche"),
]

MEDICATIONS = [
    # dci, brand, form, dosage, stock, threshold, expiry (jours), allergen_tags
    ("Paracétamol", "Doliprane", "comprimé", "1 g", 120, 30, 540, ""),
    ("Paracétamol", "Perfalgan", "solution injectable", "1 g/100 ml", 40, 15, 400, ""),
    ("Amoxicilline", "Clamoxyl", "gélule", "500 mg", 35, 10, 300, "pénicilline,bêta-lactamine"),
    ("Amoxicilline + acide clavulanique", "Augmentin", "comprimé", "1 g/125 mg", 8, 10, 250, "pénicilline,bêta-lactamine"),
    ("Ceftriaxone", "Rocéphine", "solution injectable", "1 g", 22, 8, 420, "bêta-lactamine,céphalosporine"),
    ("Furosémide", "Lasilix", "comprimé", "40 mg", 60, 15, 600, ""),
    ("Furosémide", "Lasilix inj.", "solution injectable", "20 mg/2 ml", 30, 10, 350, ""),
    ("Énoxaparine", "Lovenox", "solution injectable", "4000 UI", 48, 20, 280, ""),
    ("Apixaban", "Eliquis", "comprimé", "5 mg", 56, 14, 500, ""),
    ("Bisoprolol", "Cardensiel", "comprimé", "5 mg", 90, 20, 700, ""),
    ("Ramipril", "Triatec", "comprimé", "5 mg", 75, 20, 650, ""),
    ("Metformine", "Glucophage", "comprimé", "850 mg", 110, 30, 800, ""),
    ("Insuline glargine", "Lantus", "solution injectable", "100 UI/ml", 12, 6, 90, ""),
    ("Salbutamol", "Ventoline", "aérosol", "100 µg/dose", 25, 10, 480, ""),
    ("Ipratropium", "Atrovent", "solution pour nébulisation", "0,5 mg/2 ml", 40, 15, 200, ""),
    ("Prednisolone", "Solupred", "comprimé orodispersible", "20 mg", 45, 15, 380, ""),
    ("Oméprazole", "Mopral", "gélule", "20 mg", 100, 25, 720, ""),
    ("Tramadol", "Contramal", "gélule", "50 mg", 30, 15, 300, ""),
    ("Morphine", "Morphine chlorhydrate", "solution injectable", "10 mg/ml", 10, 5, 260, ""),
    ("Kétoprofène", "Profénid", "solution injectable", "100 mg", 18, 8, 45, "AINS"),
    ("Ibuprofène", "Advil", "comprimé", "400 mg", 60, 20, 500, "AINS"),
    ("Acide acétylsalicylique", "Kardégic", "sachet", "75 mg", 70, 20, 560, "aspirine,AINS"),
    ("Chlorure de sodium", "NaCl 0,9 %", "poche", "500 ml", 150, 40, 900, ""),
    ("Glucose", "G5 %", "poche", "500 ml", 80, 30, 850, ""),
    ("Métoclopramide", "Primpéran", "comprimé", "10 mg", 4, 10, 120, ""),
    ("Lévétiracétam", "Keppra", "comprimé", "500 mg", 60, 20, 600, ""),
    ("Insuline rapide", "NovoRapid", "solution injectable", "100 UI/ml", 14, 6, 120, ""),
    ("Glucose 30 %", "G30 %", "ampoule", "10 ml", 30, 10, 500, ""),
]

STAFF = [
    ("Sami Trabelsi", "nurse", True, "101"),
    ("Hela Bouzid", "nurse", True, None),
    ("Mourad Ayari", "nurse", False, None),
    ("Dr Nour Khelifi", "duty_doctor", True, None),
    ("Dr Youssef Mansour", "general_doctor", False, None),
    ("Leïla Haddad", "pharmacist", True, None),
    ("Karim Jaziri", "receptionist", True, None),
    ("Rim Sassi", "aide", True, None),
]


def seed_all() -> None:
    with session_scope() as session:
        if session.exec(select(Room)).first() is None:
            _seed_core(session)
            logger.info("Seed inséré : chambres, patients, admissions, pharmacie, personnel, utilisateurs")
        _ensure_users(session)
        session.flush()
        _ensure_devices(session)
        from .medical_history import ensure_history

        n = ensure_history(session)  # V2 : 5 à 15 ans d'historique fictif par patient (déterministe)
        if n:
            logger.info("Dossier médical : %d documents d'historique générés", n)
        sync_legacy_state(session)


def _seed_core(session: Session) -> None:
    now = utcnow()
    for code in ("101", "102", "103", "104"):
        session.add(Room(code=code, type="standard", is_real_instrumented=(code == "101"), wing="nord" if code in ("101", "102") else "sud"))
        session.add(RoomEquipment(room_code=code, type="window", state="closed"))
        session.add(RoomEquipment(room_code=code, type="heater", state="off"))
        session.add(RoomEquipment(room_code=code, type="ac", state="off"))
        session.add(RoomEquipment(room_code=code, type="light", state="off"))
        for t in DEVICE_TYPES:
            session.add(MedicalDevice(device_id=f"{code}-{t}", room_code=code, type=t, status="standby", label=DEVICE_LABELS[t]))

    meds: list[Medication] = []
    for dci, brand, form, dosage, stock, threshold, exp_days, tags in MEDICATIONS:
        m = Medication(dci=dci, brand=brand, form=form, dosage=dosage, stock=stock, threshold=threshold, expiry=date.today() + timedelta(days=exp_days), allergen_tags=tags)
        session.add(m)
        meds.append(m)
    session.flush()
    med_by_brand = {m.brand: m for m in meds}

    patients: list[Patient] = []
    for i, (pid, display, age, first, last, sex, allergies, group, fall_risk, history, _reason) in enumerate(PATIENTS, start=1):
        p = Patient(patient_id=pid, code=f"PAT-{i:04d}", display_name=display, first_name=first, last_name=last,
                    birth_date=_birth(age, 3 + i, 10 + i), sex=sex, allergies=allergies, blood_group=group, fall_risk=fall_risk, history=history)
        session.add(p)
        patients.append(p)
    session.flush()

    # Admissions actives (une par chambre)
    reasons = {row[0]: row[10] for row in PATIENTS}
    rooms = ["101", "102", "103", "104"]
    admissions: list[Admission] = []
    for p, code, days in zip(patients, rooms, (3, 5, 2, 4)):
        a = Admission(patient_id=p.id, room_code=code, admitted_at=now - timedelta(days=days), reason=reasons[p.patient_id], referring_doctor="Dr Youssef Mansour")
        session.add(a)
        admissions.append(a)
    session.flush()

    treatments = {
        0: [("Perfalgan", "1 g x3/j", "IV"), ("Rocéphine", "1 g/j", "IV"), ("Lovenox", "4000 UI/j", "SC"), ("Glucophage", "850 mg x2/j", "PO")],
        1: [("Lasilix inj.", "40 mg x2/j", "IV"), ("Eliquis", "5 mg x2/j", "PO"), ("Cardensiel", "5 mg/j", "PO"), ("NaCl 0,9 %", "500 ml/24 h", "IV")],
        2: [("Ventoline", "4 bouffées x4/j", "INH"), ("Atrovent", "0,5 mg x3/j", "INH"), ("Solupred", "40 mg/j", "PO"), ("G5 %", "500 ml/24 h", "IV")],
        3: [("Doliprane", "1 g x3/j", "PO"), ("Contramal", "50 mg x3/j si douleur", "PO"), ("Lovenox", "4000 UI/j", "SC"), ("Mopral", "20 mg/j", "PO")],
    }
    for idx, a in enumerate(admissions):
        for brand, poso, route in treatments[idx]:
            session.add(Treatment(admission_id=a.id, medication_id=med_by_brand[brand].id, posology=poso, route=route, start=a.admitted_at, prescriber="Dr Youssef Mansour"))

    # Deux anciennes admissions (historique) avec rapport signé et ordonnance signée
    old1 = Admission(patient_id=patients[0].id, room_code="103", admitted_at=now - timedelta(days=200), discharged_at=now - timedelta(days=194),
                     reason="Déséquilibre glycémique", referring_doctor="Dr Amira Ben Ammar")
    old2 = Admission(patient_id=patients[2].id, room_code="102", admitted_at=now - timedelta(days=90), discharged_at=now - timedelta(days=83),
                     reason="Exacerbation de BPCO (épisode précédent)", referring_doctor="Dr Nour Khelifi")
    session.add(old1)
    session.add(old2)
    session.flush()
    session.add(MedicalReport(
        admission_id=old1.id, author="Dr Amira Ben Ammar", title="Compte rendu d'hospitalisation",
        content=("Motif : déséquilibre glycémique (HbA1c 9,2 %).\n\nÉvolution : adaptation du traitement par metformine et introduction "
                 "d'une insuline basale. Glycémies capillaires stabilisées entre 1,1 et 1,6 g/l à J+5.\n\nConclusion : retour à domicile, "
                 "suivi diabétologique à 1 mois, éducation thérapeutique réalisée."),
        status="signed", created_at=old1.discharged_at, signed_at=old1.discharged_at))
    session.add(MedicalReport(
        admission_id=old2.id, author="Dr Nour Khelifi", title="Compte rendu d'hospitalisation",
        content=("Motif : exacerbation de BPCO avec hypoxémie (SpO2 86 % à l'admission).\n\nÉvolution : nébulisations, corticothérapie "
                 "orale 5 jours, oxygénothérapie 2 l/min. SpO2 93 % en air ambiant à la sortie.\n\nConclusion : sortie avec oxygène de "
                 "déambulation, réhabilitation respiratoire proposée."),
        status="signed", created_at=old2.discharged_at, signed_at=old2.discharged_at))
    for adm, lines in ((old1, [("Glucophage", "850 mg", "2 fois/j", 30, "PO"), ("Lantus", "12 UI", "1 fois/j le soir", 30, "SC")]),
                       (old2, [("Ventoline", "100 µg", "4 bouffées x4/j", 15, "INH"), ("Solupred", "40 mg", "1 fois/j", 5, "PO")])):
        pr = Prescription(admission_id=adm.id, prescriber=adm.referring_doctor, status="signed", created_at=adm.discharged_at, signed_at=adm.discharged_at, notes="Ordonnance de sortie")
        session.add(pr)
        session.flush()
        for brand, dosage, freq, days, route in lines:
            session.add(PrescriptionLine(prescription_id=pr.id, medication_id=med_by_brand[brand].id, dosage=dosage, frequency=freq, duration_days=days, route=route))

    for name, role, on_duty, room in STAFF:
        session.add(Staff(name=name, role=role, on_duty=on_duty, current_room=room))


def _ensure_devices(session: Session) -> None:
    """Ajoute les appareils apparus après la création de la base (V2 : glucomètre)."""
    existing = {d.device_id for d in session.exec(select(MedicalDevice)).all()}
    for room in session.exec(select(Room)).all():
        for t in DEVICE_TYPES:
            if f"{room.code}-{t}" not in existing:
                session.add(MedicalDevice(device_id=f"{room.code}-{t}", room_code=room.code, type=t, status="standby", label=DEVICE_LABELS[t]))


def _ensure_users(session: Session) -> None:
    existing = {u.username for u in session.exec(select(User)).all()}
    for username, role, full_name in DEMO_USERS:
        assert role in ROLES
        if username not in existing:
            session.add(User(username=username, hashed_password=hash_password(settings.demo_password), role=role, full_name=full_name))


def sync_legacy_state(session: Session) -> None:
    """Aligne `state.patients` (structure 3D existante) sur les admissions actives en base."""
    rows = session.exec(select(Admission, Patient).join(Patient, Patient.id == Admission.patient_id).where(Admission.discharged_at.is_(None))).all()
    seen: set[str] = set()
    for adm, p in rows:
        state.register_patient(p.patient_id, p.display_name, p.age, adm.room_code)
        seen.add(p.patient_id)
    for pid in list(state.patients):
        if pid not in seen:
            state.unregister_patient(pid)


def active_admission_for_room(session: Session, room_code: str) -> Admission | None:
    return session.exec(select(Admission).where(Admission.room_code == room_code, Admission.discharged_at.is_(None))).first()


def patient_for_admission(session: Session, adm: Admission) -> Patient | None:
    return session.get(Patient, adm.patient_id)
