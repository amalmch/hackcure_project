import asyncio
import uuid
from datetime import datetime, date, time, timedelta
from sqlalchemy import select
from app.database import engine, Base, AsyncSessionLocal
from app.models.user import User, UserRole
from app.models.patient import Patient, Gender
from app.models.doctor import Doctor
from app.models.prescription import Prescription, PrescriptionStatus
from app.models.medication import PrescriptionItem, MedicationForm
from app.models.dose import MedicationDose, DoseStatus
from app.models.sport import SportPlan, SportActivity, ActivityType, Intensity, PlanStatus, ActivityStatus
from app.models.nutrition import NutritionPlan, NutritionPlanStatus
from app.models.pharmacy import Pharmacy, PharmacyInventory
from app.models.conversation import Conversation, Message, SenderRole, ConversationCategory, ConversationStatus
from app.models.appointment import Appointment, AppointmentType, AppointmentStatus
from app.models.medical_record import MedicalRecord, RecordType
from app.models.notification import Notification, NotificationCategory, NotificationPriority
from app.utils.security import get_password_hash

async def seed():
    # Ensure tables are created
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        # Check if already seeded
        existing = await session.execute(select(User).where(User.email == "mohamed@example.com"))
        if existing.scalar_one_or_none():
            print("Database already contains demo user 'mohamed@example.com'. Skipping seed.")
            return

        print("Seeding HackCure database with realistic healthcare demo data...")

        demo_password_hash = get_password_hash("Test123!@#")

        # 1. Users
        patient_user = User(
            id=uuid.uuid4(),
            email="mohamed@example.com",
            phone="+216 98 123 456",
            password_hash=demo_password_hash,
            role=UserRole.PATIENT,
            is_active=True,
            is_verified=True,
            language="en"
        )
        session.add(patient_user)

        doctor_user_1 = User(
            id=uuid.uuid4(),
            email="dr.ahmed@hackcure.org",
            phone="+216 71 888 999",
            password_hash=demo_password_hash,
            role=UserRole.DOCTOR,
            is_active=True,
            is_verified=True,
            language="fr"
        )
        session.add(doctor_user_1)

        doctor_user_2 = User(
            id=uuid.uuid4(),
            email="dr.leila@hackcure.org",
            phone="+216 71 777 666",
            password_hash=demo_password_hash,
            role=UserRole.DOCTOR,
            is_active=True,
            is_verified=True,
            language="en"
        )
        session.add(doctor_user_2)
        await session.flush()

        # 2. Patient Profile
        patient = Patient(
            id=uuid.uuid4(),
            user_id=patient_user.id,
            first_name="Mohamed",
            last_name="Trabelsi",
            date_of_birth=date(1981, 5, 14),
            gender=Gender.MALE,
            blood_type="O+",
            height_cm=178.0,
            weight_kg=79.5,
            allergies=["Penicillin", "Peanuts"],
            emergency_contact_name="Sarra Trabelsi",
            emergency_contact_phone="+216 98 654 321",
            address="Avenue Habib Bourguiba, Tunis",
            avatar_url="https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=150"
        )
        session.add(patient)

        # 3. Doctors
        dr_ahmed = Doctor(
            id=uuid.uuid4(),
            user_id=doctor_user_1.id,
            first_name="Ahmed",
            last_name="Ben Ali",
            specialty="Cardiology & Internal Medicine",
            license_number="TN-MED-44821",
            clinic_name="Centre Médical Les Berges du Lac",
            clinic_address="Rue du Lac Windermere, Les Berges du Lac, Tunis",
            clinic_phone="+216 71 888 999",
            avatar_url="https://images.unsplash.com/photo-1622253692010-333f2da6031d?w=150",
            bio="Senior Interventional Cardiologist with over 18 years of clinical experience in preventive cardiovascular care and hypertension management."
        )
        session.add(dr_ahmed)

        dr_leila = Doctor(
            id=uuid.uuid4(),
            user_id=doctor_user_2.id,
            first_name="Leila",
            last_name="Mansouri",
            specialty="Endocrinology & Nutrition",
            license_number="TN-MED-55109",
            clinic_name="Cabinet Médical Ennasr",
            clinic_address="Avenue Hédi Nouira, Ennasr 2, Ariana",
            clinic_phone="+216 71 777 666",
            avatar_url="https://images.unsplash.com/photo-1594824813637-640a375a2d61?w=150",
            bio="Specialist endocrinologist focused on therapeutic lifestyle modification, metabolic syndrome, and clinical nutritional care."
        )
        session.add(dr_leila)
        await session.flush()

        # 4. Prescription (Doctor's prescription is the SOURCE OF TRUTH)
        today = date.today()
        prescription = Prescription(
            id=uuid.uuid4(),
            patient_id=patient.id,
            doctor_id=dr_ahmed.id,
            prescription_number="RX-2026-08912",
            diagnosis="Essential Hypertension & Mild Hypercholesterolemia",
            notes="Take medications strictly as scheduled. Maintain low-sodium diet and daily walking.",
            start_date=today - timedelta(days=14),
            end_date=today + timedelta(days=76),
            status=PrescriptionStatus.ACTIVE
        )
        session.add(prescription)
        await session.flush()

        # 5. Prescription Items (Medications)
        med_amlodipine = PrescriptionItem(
            id=uuid.uuid4(),
            prescription_id=prescription.id,
            medication_name="Amlodipine Besylate",
            active_ingredient="Amlodipine",
            dosage="5 mg",
            form=MedicationForm.TABLET,
            frequency="Once daily",
            frequency_per_day=1,
            scheduled_times=["08:00"],
            duration_days=90,
            start_date=prescription.start_date,
            end_date=prescription.end_date,
            instructions="Take 1 tablet in the morning with a glass of water.",
            before_food=False,
            doctor_notes="Monitor blood pressure weekly."
        )
        session.add(med_amlodipine)

        med_aspirin = PrescriptionItem(
            id=uuid.uuid4(),
            prescription_id=prescription.id,
            medication_name="Aspirin Protect",
            active_ingredient="Acetylsalicylic acid",
            dosage="100 mg",
            form=MedicationForm.TABLET,
            frequency="Once daily",
            frequency_per_day=1,
            scheduled_times=["13:00"],
            duration_days=90,
            start_date=prescription.start_date,
            end_date=prescription.end_date,
            instructions="Take 1 tablet after lunch.",
            before_food=False,
            doctor_notes="Do not take on an empty stomach."
        )
        session.add(med_aspirin)

        med_atorvastatin = PrescriptionItem(
            id=uuid.uuid4(),
            prescription_id=prescription.id,
            medication_name="Atorvastatin Calcium",
            active_ingredient="Atorvastatin",
            dosage="20 mg",
            form=MedicationForm.TABLET,
            frequency="Once daily",
            frequency_per_day=1,
            scheduled_times=["20:00"],
            duration_days=90,
            start_date=prescription.start_date,
            end_date=prescription.end_date,
            instructions="Take 1 tablet in the evening before bedtime.",
            before_food=False,
            doctor_notes="Lipid profile check scheduled in 6 weeks."
        )
        session.add(med_atorvastatin)
        await session.flush()

        # 6. Doses for Past 6 Days (High adherence history)
        for days_ago in range(6, 0, -1):
            past_date = today - timedelta(days=days_ago)
            # Amlodipine
            session.add(MedicationDose(
                prescription_item_id=med_amlodipine.id,
                patient_id=patient.id,
                scheduled_date=past_date,
                scheduled_time=time(8, 0),
                status=DoseStatus.TAKEN_ON_TIME,
                taken_at=datetime.combine(past_date, time(8, 12))
            ))
            # Aspirin
            session.add(MedicationDose(
                prescription_item_id=med_aspirin.id,
                patient_id=patient.id,
                scheduled_date=past_date,
                scheduled_time=time(13, 0),
                status=DoseStatus.TAKEN_ON_TIME,
                taken_at=datetime.combine(past_date, time(13, 18))
            ))
            # Atorvastatin
            session.add(MedicationDose(
                prescription_item_id=med_atorvastatin.id,
                patient_id=patient.id,
                scheduled_date=past_date,
                scheduled_time=time(20, 0),
                status=DoseStatus.TAKEN_ON_TIME,
                taken_at=datetime.combine(past_date, time(20, 25))
            ))

        # Doses for Today
        # 1: Morning Amlodipine -> TAKEN_ON_TIME
        session.add(MedicationDose(
            prescription_item_id=med_amlodipine.id,
            patient_id=patient.id,
            scheduled_date=today,
            scheduled_time=time(8, 0),
            status=DoseStatus.TAKEN_ON_TIME,
            taken_at=datetime.combine(today, time(8, 5))
        ))
        # 2: Lunch Aspirin -> DUE
        session.add(MedicationDose(
            prescription_item_id=med_aspirin.id,
            patient_id=patient.id,
            scheduled_date=today,
            scheduled_time=time(13, 0),
            status=DoseStatus.DUE
        ))
        # 3: Evening Atorvastatin -> SCHEDULED
        session.add(MedicationDose(
            prescription_item_id=med_atorvastatin.id,
            patient_id=patient.id,
            scheduled_date=today,
            scheduled_time=time(20, 0),
            status=DoseStatus.SCHEDULED
        ))

        # 7. Sport Plan and Activities
        sport_plan = SportPlan(
            id=uuid.uuid4(),
            prescription_id=prescription.id,
            patient_id=patient.id,
            activity_name="Cardiovascular Aerobic Walking",
            activity_type=ActivityType.WALKING,
            duration_minutes=30,
            intensity=Intensity.MODERATE,
            frequency_per_week=5,
            scheduled_days=["Monday", "Tuesday", "Thursday", "Saturday", "Sunday"],
            scheduled_time=time(17, 30),
            instructions="Maintain a brisk walking pace of ~5 km/h. Wear comfortable athletic shoes.",
            doctor_notes="Keep heart rate below 135 bpm.",
            start_date=prescription.start_date,
            end_date=prescription.end_date,
            status=PlanStatus.ACTIVE
        )
        session.add(sport_plan)
        await session.flush()

        sport_act_today = SportActivity(
            id=uuid.uuid4(),
            sport_plan_id=sport_plan.id,
            patient_id=patient.id,
            scheduled_date=today,
            scheduled_time=time(17, 30),
            status=ActivityStatus.SCHEDULED
        )
        session.add(sport_act_today)

        sport_act_yesterday = SportActivity(
            id=uuid.uuid4(),
            sport_plan_id=sport_plan.id,
            patient_id=patient.id,
            scheduled_date=today - timedelta(days=1),
            scheduled_time=time(17, 30),
            status=ActivityStatus.COMPLETED,
            started_at=datetime.combine(today - timedelta(days=1), time(17, 32)),
            completed_at=datetime.combine(today - timedelta(days=1), time(18, 5)),
            duration_actual_minutes=33,
            notes="Felt good, heart rate remained steady at 118 bpm average."
        )
        session.add(sport_act_yesterday)

        # 8. Nutrition Plan
        nutrition_plan = NutritionPlan(
            id=uuid.uuid4(),
            prescription_id=prescription.id,
            patient_id=patient.id,
            plan_type="DASH & Mediterranean Cardiovascular Diet",
            recommended_foods=[
                "Fresh leafy greens (Spinach, Kale)",
                "Wild Salmon & Sardines",
                "Extra virgin olive oil",
                "Oatmeal & Whole grains",
                "Raw almonds & walnuts",
                "Garlic & Lemon"
            ],
            foods_to_avoid=[
                "Processed cured meats",
                "Added table salt & sodium bouillon",
                "Fried foods & trans fats",
                "Commercial pastries & sugary soda",
                "High-sodium canned products"
            ],
            meal_recommendations={
                "breakfast": "Rolled oats with blueberries and a handful of walnuts.",
                "lunch": "Grilled chicken or fish with mixed greens, olive oil dressing, and quinoa.",
                "dinner": "Steamed vegetables with grilled salmon and lentils."
            },
            hydration_ml_daily=2000,
            calories_target=2100,
            doctor_notes="Keep daily sodium intake below 2,000 mg.",
            dietitian_notes="Eat fruits whole rather than juices for dietary fiber.",
            start_date=prescription.start_date,
            end_date=prescription.end_date,
            status=NutritionPlanStatus.ACTIVE
        )
        session.add(nutrition_plan)

        # 9. Pharmacies & Inventories in Tunis
        pharmacy_1 = Pharmacy(
            id=uuid.uuid4(),
            name="Pharmacie Principale de Tunis",
            address="Avenue Habib Bourguiba, Centre Ville",
            city="Tunis",
            latitude=36.8008,
            longitude=10.1800,
            phone="+216 71 254 896",
            email="contact@pharmacieprincipale.tn",
            is_24h=True,
            is_active=True
        )
        session.add(pharmacy_1)

        pharmacy_2 = Pharmacy(
            id=uuid.uuid4(),
            name="Pharmacie du Lac 2",
            address="Rue de la Feuille d'Érable, Les Berges du Lac 2",
            city="Tunis",
            latitude=36.8370,
            longitude=10.2370,
            phone="+216 71 965 412",
            email="contact@pharmacielac2.tn",
            is_24h=False,
            is_active=True
        )
        session.add(pharmacy_2)

        pharmacy_3 = Pharmacy(
            id=uuid.uuid4(),
            name="Pharmacie Moderne Ennasr",
            address="Avenue Hédi Nouira, Ennasr 2",
            city="Ariana",
            latitude=36.8580,
            longitude=10.1550,
            phone="+216 70 832 100",
            email="contact@pharmaciemoderne.tn",
            is_24h=True,
            is_active=True
        )
        session.add(pharmacy_3)
        await session.flush()

        # Inventories
        for ph in [pharmacy_1, pharmacy_2, pharmacy_3]:
            session.add(PharmacyInventory(
                pharmacy_id=ph.id,
                medication_name="Amlodipine Besylate",
                active_ingredient="Amlodipine",
                dosage="5 mg",
                form="TABLET",
                is_available=True,
                quantity=45,
                price=12.500
            ))
            session.add(PharmacyInventory(
                pharmacy_id=ph.id,
                medication_name="Aspirin Protect",
                active_ingredient="Acetylsalicylic acid",
                dosage="100 mg",
                form="TABLET",
                is_available=True,
                quantity=80,
                price=6.200
            ))
            session.add(PharmacyInventory(
                pharmacy_id=ph.id,
                medication_name="Atorvastatin Calcium",
                active_ingredient="Atorvastatin",
                dosage="20 mg",
                form="TABLET",
                is_available=True,
                quantity=30,
                price=24.800
            ))

        # 10. Conversations & Messages
        conv = Conversation(
            id=uuid.uuid4(),
            patient_id=patient.id,
            doctor_id=dr_ahmed.id,
            subject="Medication Follow-up & Blood Pressure Log",
            category=ConversationCategory.MEDICATION,
            status=ConversationStatus.ACTIVE,
            last_message_at=datetime.utcnow() - timedelta(hours=2)
        )
        session.add(conv)
        await session.flush()

        session.add(Message(
            conversation_id=conv.id,
            sender_id=patient_user.id,
            sender_role=SenderRole.PATIENT,
            content="Hello Dr. Ben Ali, I have been taking my Amlodipine every morning as prescribed. My blood pressure this morning was 128/82 mmHg.",
            is_read=True,
            created_at=datetime.utcnow() - timedelta(hours=5)
        ))
        session.add(Message(
            conversation_id=conv.id,
            sender_id=doctor_user_1.id,
            sender_role=SenderRole.DOCTOR,
            content="Excellent progress Mohamed. 128/82 is right in our target range. Continue taking your doses at the exact times and keep up your daily walks.",
            is_read=False,
            created_at=datetime.utcnow() - timedelta(hours=2)
        ))

        # 11. Appointments
        session.add(Appointment(
            id=uuid.uuid4(),
            patient_id=patient.id,
            doctor_id=dr_ahmed.id,
            appointment_date=today + timedelta(days=5),
            appointment_time=time(10, 30),
            duration_minutes=30,
            appointment_type=AppointmentType.IN_PERSON,
            status=AppointmentStatus.CONFIRMED,
            clinic_name=dr_ahmed.clinic_name,
            clinic_address=dr_ahmed.clinic_address,
            reason="Cardiovascular Follow-up and Blood Pressure Review"
        ))
        session.add(Appointment(
            id=uuid.uuid4(),
            patient_id=patient.id,
            doctor_id=dr_leila.id,
            appointment_date=today + timedelta(days=19),
            appointment_time=time(15, 0),
            duration_minutes=45,
            appointment_type=AppointmentType.IN_PERSON,
            status=AppointmentStatus.SCHEDULED,
            clinic_name=dr_leila.clinic_name,
            clinic_address=dr_leila.clinic_address,
            reason="Metabolic Diet and Nutritional Consultation"
        ))

        # 12. Medical Records
        session.add(MedicalRecord(
            id=uuid.uuid4(),
            patient_id=patient.id,
            doctor_id=dr_ahmed.id,
            record_type=RecordType.DIAGNOSIS,
            title="Cardiology Consultation Report",
            description="Patient exhibits well-controlled primary hypertension on Amlodipine 5mg. Heart sounds normal, no peripheral edema.",
            record_date=today - timedelta(days=14),
            is_confidential=False
        ))
        session.add(MedicalRecord(
            id=uuid.uuid4(),
            patient_id=patient.id,
            doctor_id=dr_ahmed.id,
            record_type=RecordType.LAB_RESULT,
            title="Complete Lipid Profile & Serum Creatinine",
            description="Total Cholesterol: 210 mg/dL, LDL: 132 mg/dL, HDL: 48 mg/dL, Triglycerides: 150 mg/dL. Creatinine: 0.9 mg/dL (Normal).",
            record_date=today - timedelta(days=16),
            is_confidential=False
        ))

        # 13. Notifications
        session.add(Notification(
            id=uuid.uuid4(),
            user_id=patient_user.id,
            title="Medication Reminder: Aspirin Protect",
            body="It is time to take your 100 mg Aspirin Protect with lunch.",
            category=NotificationCategory.MEDICATION,
            priority=NotificationPriority.HIGH,
            is_read=False,
            created_at=datetime.utcnow() - timedelta(minutes=45)
        ))
        session.add(Notification(
            id=uuid.uuid4(),
            user_id=patient_user.id,
            title="New message from Dr. Ahmed Ben Ali",
            body="Dr. Ahmed Ben Ali responded to your medication update.",
            category=NotificationCategory.DOCTOR,
            priority=NotificationPriority.NORMAL,
            is_read=False,
            created_at=datetime.utcnow() - timedelta(hours=2)
        ))
        session.add(Notification(
            id=uuid.uuid4(),
            user_id=patient_user.id,
            title="Upcoming Appointment Confirmed",
            body="Your appointment with Dr. Ben Ali is confirmed for next Monday at 10:30 AM.",
            category=NotificationCategory.APPOINTMENT,
            priority=NotificationPriority.NORMAL,
            is_read=True,
            created_at=datetime.utcnow() - timedelta(days=1)
        ))

        await session.commit()
        print("SEED DATA SUCCESSFULLY POPULATED!")

if __name__ == "__main__":
    asyncio.run(seed())
