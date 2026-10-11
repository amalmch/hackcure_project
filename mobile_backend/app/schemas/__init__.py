from app.schemas.auth import (
    UserLogin, UserCreate, UserResponse, LoginResponse, Token,
    RefreshTokenPayload, ForgotPasswordPayload, ResetPasswordPayload
)
from app.schemas.patient import PatientResponse, PatientUpdate, PatientCreate
from app.schemas.doctor import DoctorResponse, DoctorCreate
from app.schemas.medication import PrescriptionItemResponse
from app.schemas.prescription import PrescriptionResponse
from app.schemas.dose import DoseResponse, TakeDosePayload, MissDosePayload
from app.schemas.sport import SportPlanResponse, SportActivityResponse, CompleteActivityPayload
from app.schemas.nutrition import NutritionPlanResponse
from app.schemas.pharmacy import PharmacyResponse, MedicineAvailabilityResponse
from app.schemas.conversation import (
    ConversationResponse, MessageResponse,
    CreateConversationPayload, SendMessagePayload
)
from app.schemas.appointment import AppointmentResponse, CancelAppointmentPayload
from app.schemas.medical_record import MedicalRecordResponse
from app.schemas.notification import NotificationResponse, PaginatedNotificationResponse
from app.schemas.dashboard import DashboardDataResponse, AdherenceStatsResponse, DailyAdherence
from app.schemas.automation import (
    ReportExtractionPayload,
    PrescriptionExtractionPayload,
    DraftResponse,
    ApplyPayload,
    ApplyResult,
    TreatmentSummaryResponse
)
