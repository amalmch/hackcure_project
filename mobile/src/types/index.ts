// ============================================================
// HackCure - Core TypeScript Types
// ============================================================

// --- Enums ---
export enum UserRole {
  PATIENT = 'PATIENT',
  DOCTOR = 'DOCTOR',
  PHARMACIST = 'PHARMACIST',
  ADMIN = 'ADMIN',
}

export enum Gender {
  MALE = 'MALE',
  FEMALE = 'FEMALE',
  OTHER = 'OTHER',
}

export enum DoseStatus {
  SCHEDULED = 'SCHEDULED',
  DUE = 'DUE',
  REMINDING = 'REMINDING',
  TAKEN_ON_TIME = 'TAKEN_ON_TIME',
  TAKEN_LATE = 'TAKEN_LATE',
  MISSED = 'MISSED',
  CANCELLED = 'CANCELLED',
}

export enum PrescriptionStatus {
  ACTIVE = 'ACTIVE',
  COMPLETED = 'COMPLETED',
  CANCELLED = 'CANCELLED',
  MODIFIED = 'MODIFIED',
}

export enum MedicationForm {
  TABLET = 'TABLET',
  CAPSULE = 'CAPSULE',
  SYRUP = 'SYRUP',
  INJECTION = 'INJECTION',
  CREAM = 'CREAM',
  DROPS = 'DROPS',
  INHALER = 'INHALER',
  OTHER = 'OTHER',
}

export enum SportActivityType {
  WALKING = 'WALKING',
  RUNNING = 'RUNNING',
  SWIMMING = 'SWIMMING',
  CYCLING = 'CYCLING',
  YOGA = 'YOGA',
  STRETCHING = 'STRETCHING',
  OTHER = 'OTHER',
}

export enum Intensity {
  LIGHT = 'LIGHT',
  MODERATE = 'MODERATE',
  VIGOROUS = 'VIGOROUS',
}

export enum SportActivityStatus {
  SCHEDULED = 'SCHEDULED',
  IN_PROGRESS = 'IN_PROGRESS',
  COMPLETED = 'COMPLETED',
  MISSED = 'MISSED',
  CANCELLED = 'CANCELLED',
}

export enum NutritionPlanStatus {
  ACTIVE = 'ACTIVE',
  COMPLETED = 'COMPLETED',
  CANCELLED = 'CANCELLED',
}

export enum ConversationCategory {
  MEDICATION = 'MEDICATION',
  SPORT = 'SPORT',
  NUTRITION = 'NUTRITION',
  APPOINTMENT = 'APPOINTMENT',
  MEDICAL_RECORD = 'MEDICAL_RECORD',
  OTHER = 'OTHER',
}

export enum ConversationStatus {
  ACTIVE = 'ACTIVE',
  CLOSED = 'CLOSED',
  ARCHIVED = 'ARCHIVED',
}

export enum MessageType {
  TEXT = 'TEXT',
  IMAGE = 'IMAGE',
  DOCUMENT = 'DOCUMENT',
}

export enum AppointmentType {
  IN_PERSON = 'IN_PERSON',
  TELECONSULTATION = 'TELECONSULTATION',
}

export enum AppointmentStatus {
  SCHEDULED = 'SCHEDULED',
  CONFIRMED = 'CONFIRMED',
  CANCELLED = 'CANCELLED',
  COMPLETED = 'COMPLETED',
  NO_SHOW = 'NO_SHOW',
}

export enum MedicalRecordType {
  DIAGNOSIS = 'DIAGNOSIS',
  LAB_RESULT = 'LAB_RESULT',
  IMAGING = 'IMAGING',
  PROCEDURE = 'PROCEDURE',
  VISIT_NOTE = 'VISIT_NOTE',
  DOCUMENT = 'DOCUMENT',
}

export enum NotificationCategory {
  MEDICATION = 'MEDICATION',
  DOCTOR = 'DOCTOR',
  PRESCRIPTION = 'PRESCRIPTION',
  APPOINTMENT = 'APPOINTMENT',
  PHARMACY = 'PHARMACY',
  SYSTEM = 'SYSTEM',
}

export enum NotificationPriority {
  LOW = 'LOW',
  NORMAL = 'NORMAL',
  HIGH = 'HIGH',
  URGENT = 'URGENT',
}

// --- Core Models ---

export interface User {
  id: string;
  email: string;
  phone?: string;
  role: UserRole;
  is_active: boolean;
  is_verified: boolean;
  language: string;
  created_at: string;
}

export interface Patient {
  id: string;
  user_id: string;
  first_name: string;
  last_name: string;
  date_of_birth?: string;
  gender?: Gender;
  blood_type?: string;
  height_cm?: number;
  weight_kg?: number;
  allergies?: string[];
  emergency_contact_name?: string;
  emergency_contact_phone?: string;
  address?: string;
  avatar_url?: string;
  created_at: string;
  updated_at: string;
}

export interface Doctor {
  id: string;
  user_id: string;
  first_name: string;
  last_name: string;
  specialty: string;
  license_number?: string;
  clinic_name?: string;
  clinic_address?: string;
  clinic_phone?: string;
  avatar_url?: string;
  bio?: string;
  created_at: string;
}

// --- Prescription ---

export interface Prescription {
  id: string;
  patient_id: string;
  doctor_id: string;
  prescription_number?: string;
  diagnosis?: string;
  notes?: string;
  start_date: string;
  end_date?: string;
  status: PrescriptionStatus;
  items: PrescriptionItem[];
  doctor?: Doctor;
  sport_plans?: SportPlan[];
  nutrition_plans?: NutritionPlan[];
  created_at: string;
  updated_at: string;
}

export interface PrescriptionItem {
  id: string;
  prescription_id: string;
  medication_name: string;
  active_ingredient?: string;
  dosage: string;
  form?: MedicationForm;
  frequency: string;
  frequency_per_day?: number;
  scheduled_times?: string[];
  duration_days?: number;
  start_date?: string;
  end_date?: string;
  instructions?: string;
  before_food?: boolean;
  doctor_notes?: string;
  quantity_prescribed?: number;
  refills_remaining?: number;
  created_at: string;
}

// --- Medication Dose ---

export interface MedicationDose {
  id: string;
  prescription_item_id: string;
  patient_id: string;
  scheduled_date: string;
  scheduled_time: string;
  status: DoseStatus;
  taken_at?: string;
  grace_period_minutes: number;
  reminder_count: number;
  max_reminders: number;
  reminder_interval_minutes: number;
  notes?: string;
  synced: boolean;
  idempotency_key?: string;
  prescription_item?: PrescriptionItem;
  created_at: string;
}

// --- Sport ---

export interface SportPlan {
  id: string;
  prescription_id: string;
  patient_id: string;
  activity_name: string;
  activity_type: SportActivityType;
  duration_minutes: number;
  intensity: Intensity;
  frequency_per_week: number;
  scheduled_days?: number[];
  scheduled_time?: string;
  instructions?: string;
  doctor_notes?: string;
  start_date: string;
  end_date?: string;
  status: string;
  created_at: string;
}

export interface SportActivity {
  id: string;
  sport_plan_id: string;
  patient_id: string;
  scheduled_date: string;
  scheduled_time?: string;
  status: SportActivityStatus;
  started_at?: string;
  completed_at?: string;
  duration_actual_minutes?: number;
  notes?: string;
  sport_plan?: SportPlan;
  created_at: string;
}

// --- Nutrition ---

export interface MealRecommendation {
  meal: string;
  description: string;
  foods: string[];
}

export interface NutritionPlan {
  id: string;
  prescription_id: string;
  patient_id: string;
  plan_type?: string;
  recommended_foods?: string[];
  foods_to_avoid?: string[];
  meal_recommendations?: MealRecommendation[];
  hydration_ml_daily?: number;
  calories_target?: number;
  doctor_notes?: string;
  dietitian_notes?: string;
  start_date: string;
  end_date?: string;
  status: NutritionPlanStatus;
  created_at: string;
}

// --- Pharmacy ---

export interface OpeningHours {
  [day: string]: { open: string; close: string };
}

export interface Pharmacy {
  id: string;
  name: string;
  address: string;
  city?: string;
  latitude: number;
  longitude: number;
  phone?: string;
  email?: string;
  opening_hours?: OpeningHours;
  is_24h: boolean;
  is_active: boolean;
  distance_km?: number | null;
  created_at: string;
}

export interface PharmacyInventory {
  id: string;
  pharmacy_id: string;
  medication_name: string;
  active_ingredient?: string;
  dosage: string;
  form?: string;
  is_available: boolean;
  quantity?: number;
  price?: number;
  last_updated: string;
}

export interface MedicineAvailability {
  pharmacy: Pharmacy;
  inventory: PharmacyInventory;
}

// --- Conversation & Messages ---

export interface Conversation {
  id: string;
  patient_id: string;
  doctor_id: string;
  subject?: string;
  category: ConversationCategory;
  status: ConversationStatus;
  last_message_at?: string;
  doctor?: Doctor;
  last_message?: Message;
  unread_count?: number;
  created_at: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  sender_id: string;
  sender_role: 'PATIENT' | 'DOCTOR';
  content: string;
  message_type: MessageType;
  is_read: boolean;
  read_at?: string;
  created_at: string;
  pending?: boolean;
  failed?: boolean;
}

// --- Appointments ---

export interface Appointment {
  id: string;
  patient_id: string;
  doctor_id: string;
  appointment_date: string;
  appointment_time: string;
  duration_minutes: number;
  appointment_type: AppointmentType;
  status: AppointmentStatus;
  clinic_name?: string;
  clinic_address?: string;
  reason?: string;
  notes?: string;
  cancellation_reason?: string;
  doctor?: Doctor;
  created_at: string;
}

// --- Medical Records ---

export interface MedicalRecord {
  id: string;
  patient_id: string;
  doctor_id?: string;
  record_type: MedicalRecordType;
  title: string;
  description?: string;
  record_date: string;
  data?: Record<string, unknown>;
  file_url?: string;
  file_type?: string;
  is_confidential: boolean;
  doctor?: Doctor;
  created_at: string;
}

// --- Notifications ---

export interface AppNotification {
  id: string;
  user_id: string;
  title: string;
  body?: string;
  category: NotificationCategory;
  priority: NotificationPriority;
  is_read: boolean;
  read_at?: string;
  data?: Record<string, unknown>;
  created_at: string;
}

// --- Dashboard ---

export interface DashboardData {
  today_doses: MedicationDose[];
  medication_progress: {
    total: number;
    taken: number;
    missed: number;
    pending: number;
    percentage: number;
  };
  sport_progress: {
    total: number;
    completed: number;
    percentage: number;
  };
  today_sport_activities: SportActivity[];
  next_dose?: MedicationDose | null;
  next_appointment?: Appointment;
  unread_notifications_count: number;
  active_prescriptions_count: number;
  recent_sport_activity?: SportActivity | null;
  adherence: AdherenceStats;
}

// --- Adherence ---

export interface AdherenceStats {
  daily: {
    total: number;
    taken_on_time: number;
    taken_late: number;
    missed: number;
    pending: number;
    percentage: number;
  };
  weekly: {
    total: number;
    taken_on_time: number;
    taken_late: number;
    missed: number;
    percentage: number;
    daily_breakdown: {
      date: string;
      percentage: number;
      total: number;
      taken: number;
    }[];
  };
  monthly: {
    total: number;
    taken_on_time: number;
    taken_late: number;
    missed: number;
    percentage: number;
  };
}

// --- API Response ---

export interface ApiResponse<T> {
  data: T;
  message?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  limit: number;
  pages: number;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

// --- Offline ---

export interface PendingDoseRecord {
  dose_id: string;
  taken_at: string;
  idempotency_key: string;
  created_at: string;
}

export interface PendingMessage {
  conversation_id: string;
  content: string;
  local_id: string;
  created_at: string;
}

// --- Treatment Summary & Automation ---

export interface TreatmentSummary {
  id: string;
  patient_id: string;
  version: number;
  is_current: boolean;
  diagnosis?: string;
  treatment_goals?: string[];
  precautions?: string[];
  warnings?: string[];
  follow_up_dates?: string[];
  consultation_reason?: string;
  doctor_conclusion?: string;
  patient_summary?: string;
  sport_recommendations?: {
    recommande?: string[];
    a_eviter?: string[];
    frequence?: string;
    intensite?: string;
    duree?: string;
    restrictions?: string[];
    jours?: string[];
  };
  nutrition_recommendations?: {
    a_privilegier?: string[];
    a_limiter?: string[];
    conseils?: string;
    regime_type?: string;
    hydratation_ml?: number;
    calories_cible?: number;
    repas?: Record<string, string>;
  };
  created_at: string;
  updated_at?: string;
}

export interface DraftDocument {
  document_source_id: string;
  document_type: 'DOCTOR_REPORT' | 'PRESCRIPTION';
  status: string;
  version: number;
  extracted_data: any;
  confidence_scores?: Record<string, number>;
  low_confidence_fields: string[];
  created_at: string;
}

