"""
Modèle de données SQLModel (section 5 du PROMPT).
SQLite par défaut, SQL Server si DATABASE_URL est défini.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel
from sqlalchemy import Column

from .crypto import EncryptedStr


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─── Lieux et équipements ─────────────────────────────────────────────────────
class Room(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)  # "101".."104"
    type: str = "standard"
    is_real_instrumented: bool = False
    wing: str = "nord"


class RoomEquipment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    room_code: str = Field(index=True)
    type: str  # window | heater | ac | light
    state: str = "off"  # open|closed|on|off
    value: Optional[float] = None
    last_command_by: Optional[str] = None
    updated_at: datetime = Field(default_factory=utcnow)


class MedicalDevice(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: str = Field(index=True, unique=True)  # "101-iv_pump"
    room_code: str = Field(index=True)
    type: str  # iv_pump|nutrition_pump|transfusion|bp|ecg|oxygen|spo2|thermometer
    status: str = "standby"  # running|paused|alarm|off|standby
    label: str = ""
    last_seen: Optional[datetime] = None


# ─── Patients ────────────────────────────────────────────────────────────────
class Patient(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_id: str = Field(index=True, unique=True)  # "patient_01" (identifiant 3D existant)
    code: str = Field(index=True, unique=True)  # "PAT-0001"
    display_name: str  # "Patient A" (étiquette 3D existante)
    first_name: str = Field(sa_column=Column(EncryptedStr, nullable=False))  # V3 : chiffré au repos (AES-256-GCM) si DATA_ENCRYPTION_KEY
    last_name: str = Field(sa_column=Column(EncryptedStr, nullable=False))
    birth_date: date
    sex: str = "M"  # M | F
    allergies: str = ""  # séparées par des virgules
    blood_group: str = "O+"
    fall_risk: str = "medium"  # low | medium | high
    history: str = ""  # antécédents
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def age(self) -> int:
        today = date.today()
        return today.year - self.birth_date.year - ((today.month, today.day) < (self.birth_date.month, self.birth_date.day))

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def allergy_list(self) -> list[str]:
        return [a.strip().lower() for a in self.allergies.split(",") if a.strip()]


class Admission(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    room_code: str = Field(index=True)
    admitted_at: datetime = Field(default_factory=utcnow)
    discharged_at: Optional[datetime] = None
    reason: str = ""
    referring_doctor: str = ""

    @property
    def active(self) -> bool:
        return self.discharged_at is None


# ─── Mesures ─────────────────────────────────────────────────────────────────
class VitalReading(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: str = Field(index=True)
    admission_id: Optional[int] = Field(default=None, index=True)
    room_code: str = Field(index=True)
    metric: str = Field(index=True)  # hr, spo2, sys, dia, map, tempC, rateMlH, volumeLeftMl, flowLMin...
    value: float
    unit: str = ""
    ts: datetime = Field(default_factory=utcnow, index=True)


class EnvironmentReading(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    room_code: str = Field(index=True)
    metric: str  # tempC, humidity, motion, doorOpen, skinTempC
    value: float
    ts: datetime = Field(default_factory=utcnow, index=True)


class PatientStateSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    admission_id: Optional[int] = Field(default=None, index=True)
    room_code: str = Field(index=True)
    posture: str = "lying_bed"
    activity: str = "awake_bed"
    zone: str = "bed"
    expression: str = "neutral"
    skin_temp_c: Optional[float] = None
    persons: int = 1
    source: str = "sim"
    ts: datetime = Field(default_factory=utcnow, index=True)


# ─── Risques et plans d'action ───────────────────────────────────────────────
class Risk(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    admission_id: Optional[int] = Field(default=None, index=True)
    room_code: str = Field(index=True)
    type: str = Field(index=True)  # fall, unaccompanied_bed_exit, fever, sepsis_trend, iv_empty, ...
    title: str = ""
    severity: str = "medium"  # low|medium|high|critical
    status: str = "open"  # open|in_progress|resolved|escalated
    source_agent: str = "RiskAgent"
    explanation: str = ""
    news2: Optional[int] = None
    dedup_key: str = Field(default="", index=True)
    detected_at: datetime = Field(default_factory=utcnow)
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    escalated_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    notes: str = ""
    handled_by: str = "local"  # local | n8n
    n8n_resume_url: Optional[str] = None  # URL de reprise du nœud Wait (acquittement « Je prends en charge »)


class ActionPlan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    risk_id: int = Field(foreign_key="risk.id", index=True)
    summary: str = ""
    created_by: str = "RiskAgent"
    llm_provider: str = "mock"
    created_at: datetime = Field(default_factory=utcnow)


class ActionStep(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="actionplan.id", index=True)
    order: int = 0
    text: str
    suggested_by_ai: bool = True
    done: bool = False
    done_by: Optional[str] = None
    done_at: Optional[datetime] = None


class StaffVisit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    room_code: str = Field(index=True)
    admission_id: Optional[int] = Field(default=None, index=True)
    risk_id: Optional[int] = Field(default=None, index=True)
    started_at: datetime = Field(default_factory=utcnow)
    ended_at: Optional[datetime] = None
    persons: int = 2
    staff_name: Optional[str] = None


# ─── Personnes ───────────────────────────────────────────────────────────────
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    hashed_password: str
    role: str  # pharmacist|receptionist|nurse|duty_doctor|general_doctor|owner
    full_name: str = ""
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class Staff(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    role: str  # nurse|duty_doctor|general_doctor|pharmacist|receptionist|aide
    on_duty: bool = False
    phone: str = ""
    current_room: Optional[str] = None


# ─── Pharmacie ───────────────────────────────────────────────────────────────
class Medication(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    dci: str = Field(index=True)  # dénomination commune internationale
    brand: str = ""
    form: str = "comprimé"  # comprimé|gélule|solution injectable|sirop|poche|...
    dosage: str = ""
    unit: str = "boîte"
    stock: int = 0
    threshold: int = 5
    expiry: Optional[date] = None
    allergen_tags: str = ""  # ex. "pénicilline,bêta-lactamine"

    @property
    def low_stock(self) -> bool:
        return self.stock <= self.threshold

    def expiring_within(self, days: int = 60) -> bool:
        return self.expiry is not None and (self.expiry - date.today()).days <= days


class Treatment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    admission_id: int = Field(foreign_key="admission.id", index=True)
    medication_id: int = Field(foreign_key="medication.id")
    posology: str = ""
    route: str = "PO"  # PO|IV|SC|IM|INH
    start: datetime = Field(default_factory=utcnow)
    end: Optional[datetime] = None
    prescriber: str = ""


# ─── Documents ───────────────────────────────────────────────────────────────
class MedicalReport(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    admission_id: int = Field(foreign_key="admission.id", index=True)
    author: str = ""
    title: str = "Rapport médical"
    content: str = ""
    status: str = "draft"  # draft|signed
    ai_draft: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    signed_at: Optional[datetime] = None


class Prescription(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    admission_id: int = Field(foreign_key="admission.id", index=True)
    prescriber: str = ""
    status: str = "draft"  # draft|signed
    notes: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    signed_at: Optional[datetime] = None


class PrescriptionLine(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    prescription_id: int = Field(foreign_key="prescription.id", index=True)
    medication_id: int = Field(foreign_key="medication.id")
    dosage: str = ""
    frequency: str = ""
    duration_days: int = 5
    route: str = "PO"
    allergy_warning: bool = False


class ShiftReport(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    shift_start: datetime
    shift_end: datetime
    author: str = "ReportAgent"
    content: str = ""  # markdown
    status: str = "draft"  # draft|validated
    validated_by: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    validated_at: Optional[datetime] = None


class MoodObservation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    admission_id: Optional[int] = Field(default=None, index=True)
    room_code: str = Field(index=True)
    mood: str = "neutral"  # calm|anxious|pain|sad|agitated|neutral|happy
    source: str = "VisionAgent"
    note: str = ""
    ts: datetime = Field(default_factory=utcnow, index=True)


# ─── Journalisation ──────────────────────────────────────────────────────────
class Notification(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    level: str = "info"  # info|warning|critical
    title: str
    body: str = ""
    room_code: Optional[str] = Field(default=None, index=True)
    risk_id: Optional[int] = Field(default=None, index=True)
    target_role: str = "nurse"  # nurse|duty_doctor|all
    channels: str = "in_app"  # "in_app,telegram"
    telegram_sent: bool = False
    read: bool = False
    created_at: datetime = Field(default_factory=utcnow, index=True)


class AgentLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    agent: str = Field(index=True)
    room_code: Optional[str] = Field(default=None, index=True)
    input: str = ""
    reasoning: str = ""
    output: str = ""
    status: str = "ok"  # ok|error|skipped
    risk_id: Optional[int] = Field(default=None, index=True)
    duration_ms: int = 0
    ts: datetime = Field(default_factory=utcnow, index=True)


class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user: str = Field(index=True)
    role: str = ""
    action: str  # create|update|delete|sign|login|command|resolve...
    entity: str = ""
    entity_id: Optional[str] = None
    details: str = ""
    ts: datetime = Field(default_factory=utcnow, index=True)
    ip: str = ""  # V3 (non-répudiation) : adresse du poste d'où vient l'action


# ─── V2 : dossier médical, biologie, parcours fièvre ─────────────────────────
class MedicalRecordEntry(SQLModel, table=True):
    """Un document du dossier médical (consultation, hospitalisation, biologie, imagerie, intervention…)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    patient_pk: int = Field(foreign_key="patient.id", index=True)
    admission_id: Optional[int] = Field(default=None, foreign_key="admission.id")
    type: str = Field(index=True)  # consultation|hospitalisation|operation|biologie|imagerie|vaccination|allergie|chronique|familial|traitement|ordonnance|psychologie|intervention
    date: datetime = Field(index=True)
    title: str = ""
    author: str = ""
    service: str = ""
    facility: str = ""
    summary: str = ""
    content: str = Field(default="", sa_column=Column(EncryptedStr, nullable=False, default=""))  # V3 : chiffré au repos
    data_json: str = "{}"  # contenu structuré
    attachments_json: str = "[]"
    source: str = "historique"  # historique (généré) | plateforme (créé pendant le séjour)
    status: str = "signed"  # draft | signed
    created_at: datetime = Field(default_factory=utcnow)


class LabResult(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_pk: int = Field(foreign_key="patient.id", index=True)
    entry_id: Optional[int] = Field(default=None, foreign_key="medicalrecordentry.id", index=True)
    code: str = Field(index=True)  # CRP, LEUCO…
    label: str = ""
    value: Optional[float] = None
    text: str = ""  # résultat qualitatif
    unit: str = ""
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    abnormal: bool = False
    date: datetime = Field(index=True)


class FeverPathway(SQLModel, table=True):
    """Parcours fièvre : bilan clinique → bilan biologique → confort → traitement / résolution."""

    id: Optional[int] = Field(default=None, primary_key=True)
    risk_id: int = Field(foreign_key="risk.id", index=True)
    admission_id: Optional[int] = Field(default=None, foreign_key="admission.id")
    patient_pk: Optional[int] = Field(default=None, foreign_key="patient.id")
    room_code: str = Field(index=True)
    stage: str = "clinical_exam"  # clinical_exam | lab_proposed | lab_ordered | lab_results | resolved
    criterion: str = ""
    core_temp: Optional[float] = None
    qsofa: int = 0
    news2: Optional[int] = None
    checklist_json: str = "[]"
    labs_json: str = "[]"
    results_json: str = "[]"
    ai_json: str = "{}"
    exam_done_by: Optional[str] = None
    exam_done_at: Optional[datetime] = None
    labs_validated_by: Optional[str] = None
    labs_validated_at: Optional[datetime] = None
    results_due_at: Optional[datetime] = None
    results_at: Optional[datetime] = None
    comfort_note: str = ""
    record_entry_id: Optional[int] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    closed_at: Optional[datetime] = None


# ─── V2 étape 4 : diagnostics live, fil médecin ↔ infirmier, ordonnance de traitement, plan d'administration ──
class DiagnosticHypothesis(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_pk: int = Field(foreign_key="patient.id", index=True)
    admission_id: Optional[int] = Field(default=None, foreign_key="admission.id")
    room_code: str = Field(default="", index=True)
    code: str = Field(index=True)
    label: str = ""
    score: float = 0.0
    probability: str = "faible"  # faible | modérée | élevée
    pros_json: str = "[]"
    cons_json: str = "[]"
    exams_json: str = "[]"
    status: str = "active"  # active | confirmed | rejected | inactive (plus d'élément en faveur)
    note: str = ""
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CareMessage(SQLModel, table=True):
    """Fil de communication médecin ↔ infirmier, par patient."""

    id: Optional[int] = Field(default=None, primary_key=True)
    patient_pk: int = Field(foreign_key="patient.id", index=True)
    room_code: str = ""
    author: str = ""
    author_name: str = ""
    role: str = ""
    kind: str = "message"  # message | decision | ai
    body: str = ""
    mentions: str = ""  # rôles mentionnés, séparés par des virgules
    hypothesis_id: Optional[int] = None
    created_at: datetime = Field(default_factory=utcnow, index=True)


class TreatmentOrder(SQLModel, table=True):
    """Ordonnance de traitement HOSPITALIÈRE (distincte de l'ordonnance de sortie `Prescription`)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    admission_id: int = Field(foreign_key="admission.id", index=True)
    patient_pk: int = Field(foreign_key="patient.id", index=True)
    room_code: str = ""
    prescriber: str = ""
    prescriber_name: str = ""
    indication: str = ""
    status: str = "draft"  # draft | active | stopped
    created_at: datetime = Field(default_factory=utcnow)
    signed_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None


class TreatmentOrderLine(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="treatmentorder.id", index=True)
    medication_id: int = Field(foreign_key="medication.id")
    dci: str = ""
    dose: str = ""
    route: str = "PO"
    times: str = ""  # horaires « 08:00,14:00,20:00 » ; vide pour une prise conditionnelle
    duration_days: int = 3
    prn: bool = False  # « si besoin » : prise déclenchée par une condition
    condition_metric: str = ""  # tempC | pain | sys | spo2 | glucose
    condition_op: str = ">"
    condition_value: Optional[float] = None
    min_interval_h: float = 6.0
    allergy_alert: str = ""
    interaction_alert: str = ""


class MedicationDose(SQLModel, table=True):
    """Une prise du plan d'administration horodaté."""

    id: Optional[int] = Field(default=None, primary_key=True)
    line_id: int = Field(foreign_key="treatmentorderline.id", index=True)
    order_id: int = Field(foreign_key="treatmentorder.id", index=True)
    admission_id: int = Field(foreign_key="admission.id")
    patient_pk: int = Field(foreign_key="patient.id", index=True)
    room_code: str = Field(default="", index=True)
    medication_id: int = Field(foreign_key="medication.id")
    label: str = ""
    due_at: datetime = Field(index=True)
    status: str = Field(default="scheduled", index=True)  # scheduled | given | not_given | cancelled
    conditional: bool = False
    given_at: Optional[datetime] = None
    given_by: Optional[str] = None
    note: str = ""
    reason: str = ""
    reminded_at: Optional[datetime] = None
    relaunched_at: Optional[datetime] = None
    escalated_at: Optional[datetime] = None


# ─── V2 étape 7 : psychologie ─────────────────────────────────────────────────
class PsychQuestionnaire(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_pk: int = Field(foreign_key="patient.id", index=True)
    admission_id: Optional[int] = Field(default=None, foreign_key="admission.id", index=True)
    room_code: str = ""
    token: str = Field(index=True, unique=True)  # lien de la page tablette
    status: str = "pending"  # pending | completed
    answers_json: str = Field(default="{}", sa_column=Column(EncryptedStr, nullable=False, default="{}"))  # V3 : chiffré au repos
    scores_json: str = "{}"
    q9_positive: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    completed_at: Optional[datetime] = None


class PsychScore(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_pk: int = Field(foreign_key="patient.id", index=True)
    admission_id: Optional[int] = Field(default=None, foreign_key="admission.id", index=True)
    room_code: str = Field(default="", index=True)
    wellbeing: int = 100  # 0–100
    level: str = "faible"  # niveau de risque global : faible | modéré | élevé
    detail_json: str = "{}"  # par trouble : score, niveau, facteurs ; conduite à tenir ; explication IA
    ts: datetime = Field(default_factory=utcnow, index=True)


class PsychPrescription(SQLModel, table=True):
    """Prescription psychothérapeutique (psychiatre) : type de suivi, fréquence, objectifs, consignes à l'équipe."""

    id: Optional[int] = Field(default=None, primary_key=True)
    patient_pk: int = Field(foreign_key="patient.id", index=True)
    admission_id: Optional[int] = Field(default=None, foreign_key="admission.id")
    type: str = ""
    frequency: str = ""
    goals: str = ""
    instructions: str = ""
    author: str = ""
    author_name: str = ""
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


# ─── V2 étape 8 : prédiction des crises ───────────────────────────────────────
class Prediction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_pk: int = Field(foreign_key="patient.id", index=True)
    admission_id: Optional[int] = Field(default=None, foreign_key="admission.id")
    room_code: str = Field(default="", index=True)
    key: str = Field(index=True)  # seizure | sepsis | cardiac | deterioration | diabetes
    risk: int = 0  # 0–100
    level: str = "faible"  # faible | modéré | élevé | critique
    window_json: str = ""  # {min_minutes, max_minutes, text}
    confidence: str = "faible"
    factors_json: str = "[]"
    ai_json: str = ""
    ts: datetime = Field(default_factory=utcnow, index=True)


# ─── V2 étape 5 : ambulances ──────────────────────────────────────────────────
class AmbulanceMission(SQLModel, table=True):
    """Fiche d'intervention d'une ambulance : patient, urgence, position, ETA, chambre réservée."""

    id: Optional[int] = Field(default=None, primary_key=True)
    ambulance_code: str = "AMB-01"
    patient_pk: Optional[int] = Field(default=None, foreign_key="patient.id")
    patient_id: str = ""
    patient_name: str = ""
    age: Optional[int] = None
    sex: str = ""
    reason: str = ""
    emergency_type: str = "other"  # trauma | cardio | stroke | respiratory | obstetric | infection | other
    severity: int = 2  # 1 urgence vitale … 3 urgence relative
    vitals_json: str = "{}"  # constantes transmises par l'équipe de l'ambulance
    mode: str = "sim"  # sim (trajet simulé) | gps (téléphone)
    status: str = Field(default="en_route", index=True)  # en_route | arrived | admitted | cancelled
    departed_at: datetime = Field(default_factory=utcnow, index=True)
    eta_at: Optional[datetime] = None
    arrived_at: Optional[datetime] = None
    reserved_room: Optional[str] = None
    lat: float = 0.0
    lon: float = 0.0
    heading: float = 0.0
    speed_kmh: float = 0.0
    remaining_m: float = 0.0
    progress: float = 0.0
    route_json: str = "[]"
    route_label: str = ""
    track_token: str = Field(default="", index=True)
    preparation_json: str = "{}"
    ai_json: str = ""
    admission_id: Optional[int] = None
    time_scale: float = 0.0  # accélération du trajet simulé pour cette mission (0 = réglage global AMBULANCE_TIME_SCALE)
