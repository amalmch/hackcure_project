from pydantic import BaseModel, Field
from typing import Optional, List, Any
from uuid import UUID
from datetime import datetime, date

# --- Report Extraction Schema ---
class SportRecommendation(BaseModel):
    recommande: List[str] = []
    a_eviter: List[str] = []
    frequence: Optional[str] = None
    intensite: Optional[str] = None
    duree: Optional[str] = None
    restrictions: List[str] = []
    jours: List[str] = []

class NutritionRecommendation(BaseModel):
    a_privilegier: List[str] = []
    a_limiter: List[str] = []
    conseils: Optional[str] = None
    regime_type: Optional[str] = None
    hydratation_ml: Optional[int] = None
    calories_cible: Optional[int] = None
    repas: Optional[dict] = None

class MedicationExtracted(BaseModel):
    nom: str
    principe_actif: Optional[str] = None
    posologie: str
    forme: Optional[str] = None  # comprimé, gélule, sirop, etc.
    frequence: Optional[str] = None
    heures_prises: List[str] = []  # ["08:00", "20:00"]
    duree_jours: Optional[int] = None
    date_debut: Optional[str] = None
    date_fin: Optional[str] = None
    instructions: Optional[str] = None
    avant_repas: Optional[bool] = None
    quantite: Optional[int] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

class ReportExtractionPayload(BaseModel):
    patient_id: UUID
    document_source_id: Optional[UUID] = None
    motif_consultation: Optional[str] = None
    diagnostic: Optional[str] = None
    conclusion: Optional[str] = None
    objectifs_traitement: List[str] = []
    precautions: List[str] = []
    alertes: List[str] = []
    dates_suivi: List[str] = []
    sport: Optional[SportRecommendation] = None
    nutrition: Optional[NutritionRecommendation] = None
    medicaments: List[MedicationExtracted] = []
    resume_patient: Optional[str] = None
    confidence_scores: Optional[dict] = None
    texte_brut: Optional[str] = None

class PrescriptionExtractionPayload(BaseModel):
    patient_id: UUID
    document_source_id: Optional[UUID] = None
    prescription_number: Optional[str] = None
    doctor_name: Optional[str] = None
    diagnosis: Optional[str] = None
    notes: Optional[str] = None
    date_debut: Optional[str] = None
    date_fin: Optional[str] = None
    medicaments: List[MedicationExtracted] = []
    confidence_scores: Optional[dict] = None

class DraftResponse(BaseModel):
    document_source_id: UUID
    document_type: str
    status: str
    version: int
    extracted_data: Any
    confidence_scores: Optional[dict] = None
    low_confidence_fields: List[str] = []
    created_at: datetime

    model_config = {"from_attributes": True}

class ApplyPayload(BaseModel):
    document_source_ids: List[UUID]
    confirmed_by: str = "patient"

class ApplyResult(BaseModel):
    success: bool
    prescription_id: Optional[UUID] = None
    treatment_summary_id: Optional[UUID] = None
    doses_generated: int = 0
    sport_plans_created: int = 0
    nutrition_plans_created: int = 0
    old_reminders_cancelled: int = 0
    audit_log_ids: List[UUID] = []
    warnings: List[str] = []

class TreatmentSummaryResponse(BaseModel):
    id: UUID
    patient_id: UUID
    version: int
    is_current: bool
    diagnosis: Optional[str] = None
    treatment_goals: Optional[List[str]] = None
    precautions: Optional[List[str]] = None
    warnings: Optional[List[str]] = None
    follow_up_dates: Optional[List[str]] = None
    consultation_reason: Optional[str] = None
    doctor_conclusion: Optional[str] = None
    patient_summary: Optional[str] = None
    sport_recommendations: Optional[dict] = None
    nutrition_recommendations: Optional[dict] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    model_config = {"from_attributes": True}
