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
from app.models.conversation import Conversation, Message, SenderRole, ConversationCategory, ConversationStatus
from app.models.appointment import Appointment, AppointmentType, AppointmentStatus
from app.models.medical_record import MedicalRecord, RecordType
from app.models.notification import Notification, NotificationCategory, NotificationPriority

async def assign_active_prescription(target_email: str = "mohamedallagui22@gmail.com"):
    async with AsyncSessionLocal() as session:
        # 1. Find user & patient
        user_res = await session.execute(select(User).where(User.email == target_email))
        user = user_res.scalar_one_or_none()
        if not user:
            print(f"User {target_email} not found.")
            return

        patient_res = await session.execute(select(Patient).where(Patient.user_id == user.id))
        patient = patient_res.scalar_one_or_none()
        if not patient:
            patient = Patient(
                id=uuid.uuid4(),
                user_id=user.id,
                first_name="Mohamed",
                last_name="Allagui",
                date_of_birth=date(1985, 6, 15),
                gender=Gender.MALE,
                blood_group="O+",
                height_cm=178,
                weight_kg=78,
                allergies=["Penicillin"],
                chronic_conditions=["Hypertension"],
                emergency_contact_name="Leila Allagui",
                emergency_contact_phone="+216 98 765 432",
                address="Tunis, Tunisia"
            )
            session.add(patient)
            await session.flush()

        # 2. Find doctor
        dr_res = await session.execute(select(Doctor))
        doctor = dr_res.scalars().first()
        if not doctor:
            print("No doctor found in database.")
            return

        # 3. Check existing active prescription
        rx_res = await session.execute(
            select(Prescription).where(
                Prescription.patient_id == patient.id,
                Prescription.status == PrescriptionStatus.ACTIVE
            )
        )
        existing_rx = rx_res.scalar_one_or_none()
        if existing_rx:
            print(f"Patient {target_email} already has an active prescription: {existing_rx.id}")
            return

        today = date.today()

        # 4. Create Active Prescription
        prescription = Prescription(
            id=uuid.uuid4(),
            patient_id=patient.id,
            doctor_id=doctor.id,
            prescription_number=f"RX-{datetime.now().strftime('%Y%m%d')}-042",
            diagnosis="Essential Hypertension & Mild Hypercholesterolemia",
            notes="Take medications strictly as scheduled. Maintain low-sodium diet and 30 min daily walking.",
            start_date=today - timedelta(days=14),
            end_date=today + timedelta(days=76),
            status=PrescriptionStatus.ACTIVE
        )
        session.add(prescription)
        await session.flush()

        # 5. Medications
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

        # 6. Doses: Past 6 days for adherence history
        for days_ago in range(6, 0, -1):
            past_date = today - timedelta(days=days_ago)
            session.add(MedicationDose(
                prescription_item_id=med_amlodipine.id,
                patient_id=patient.id,
                scheduled_date=past_date,
                scheduled_time=time(8, 0),
                status=DoseStatus.TAKEN_ON_TIME,
                taken_at=datetime.combine(past_date, time(8, 10))
            ))
            session.add(MedicationDose(
                prescription_item_id=med_aspirin.id,
                patient_id=patient.id,
                scheduled_date=past_date,
                scheduled_time=time(13, 0),
                status=DoseStatus.TAKEN_ON_TIME,
                taken_at=datetime.combine(past_date, time(13, 20))
            ))
            session.add(MedicationDose(
                prescription_item_id=med_atorvastatin.id,
                patient_id=patient.id,
                scheduled_date=past_date,
                scheduled_time=time(20, 0),
                status=DoseStatus.TAKEN_ON_TIME,
                taken_at=datetime.combine(past_date, time(20, 15))
            ))

        # 7. Today's Doses
        # Dose 1 (Morning): Taken
        session.add(MedicationDose(
            prescription_item_id=med_amlodipine.id,
            patient_id=patient.id,
            scheduled_date=today,
            scheduled_time=time(8, 0),
            status=DoseStatus.TAKEN_ON_TIME,
            taken_at=datetime.combine(today, time(8, 5))
        ))
        # Dose 2 (Lunch): DUE (Ready for the user to tap "I Took It" in the app!)
        session.add(MedicationDose(
            prescription_item_id=med_aspirin.id,
            patient_id=patient.id,
            scheduled_date=today,
            scheduled_time=time(13, 0),
            status=DoseStatus.DUE
        ))
        # Dose 3 (Evening): SCHEDULED
        session.add(MedicationDose(
            prescription_item_id=med_atorvastatin.id,
            patient_id=patient.id,
            scheduled_date=today,
            scheduled_time=time(20, 0),
            status=DoseStatus.SCHEDULED
        ))

        # 8. Sport Plan
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
            instructions="Maintain a brisk walking pace of ~5 km/h. Wear comfortable shoes.",
            doctor_notes="Keep heart rate below 135 bpm.",
            start_date=prescription.start_date,
            end_date=prescription.end_date,
            status=PlanStatus.ACTIVE
        )
        session.add(sport_plan)
        await session.flush()

        session.add(SportActivity(
            id=uuid.uuid4(),
            sport_plan_id=sport_plan.id,
            patient_id=patient.id,
            scheduled_date=today,
            scheduled_time=time(17, 30),
            status=ActivityStatus.SCHEDULED
        ))

        # 9. Nutrition Plan
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
                "Raw almonds & walnuts"
            ],
            foods_to_avoid=[
                "Processed cured meats",
                "Added table salt & sodium bouillon",
                "Fried foods & trans fats",
                "Commercial pastries & sugary soda"
            ],
            meal_recommendations={
                "breakfast": "Rolled oats with berries and a handful of walnuts.",
                "lunch": "Grilled chicken or fish with mixed greens, olive oil dressing, and quinoa.",
                "dinner": "Steamed vegetables with grilled salmon and lentils."
            },
            hydration_ml_daily=2000,
            calories_target=2100,
            doctor_notes="Keep daily sodium intake below 2,000 mg.",
            start_date=prescription.start_date,
            end_date=prescription.end_date,
            status=NutritionPlanStatus.ACTIVE
        )
        session.add(nutrition_plan)

        # 10. Doctor Conversation
        conv = Conversation(
            id=uuid.uuid4(),
            patient_id=patient.id,
            doctor_id=doctor.id,
            subject="Cardiology Care Plan & Prescription Follow-up",
            category=ConversationCategory.MEDICATION,
            status=ConversationStatus.ACTIVE
        )
        session.add(conv)
        await session.flush()

        session.add(Message(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            sender_id=doctor.user_id,
            sender_role=SenderRole.DOCTOR,
            content="Bonjour Mohamed, your new prescription is active. Please log your doses daily and do 30 min of walking.",
            created_at=datetime.utcnow() - timedelta(hours=3),
            is_read=True
        ))

        # 11. Appointment
        appt = Appointment(
            id=uuid.uuid4(),
            patient_id=patient.id,
            doctor_id=doctor.id,
            appointment_type=AppointmentType.IN_PERSON,
            appointment_date=today + timedelta(days=14),
            appointment_time=time(10, 30),
            status=AppointmentStatus.CONFIRMED,
            clinic_name=doctor.clinic_name,
            clinic_address=doctor.clinic_address,
            reason="Cardiology Routine Follow-up",
            notes="Follow-up consultation to evaluate blood pressure control."
        )
        session.add(appt)

        # 12. Medical Record
        session.add(MedicalRecord(
            id=uuid.uuid4(),
            patient_id=patient.id,
            doctor_id=doctor.id,
            record_type=RecordType.LAB_RESULT,
            title="Complete Lipid Profile & Metabolic Panel",
            description="Lipid profile showing borderline LDL cholesterol. Liver and kidney function normal.",
            record_date=today - timedelta(days=14)
        ))

        # 13. Notifications
        session.add(Notification(
            id=uuid.uuid4(),
            user_id=user.id,
            title="Active Prescription Ready",
            body="Dr. Ahmed Ben Ali has issued your official care plan: 3 medications prescribed.",
            category=NotificationCategory.PRESCRIPTION,
            priority=NotificationPriority.HIGH,
            is_read=False,
            created_at=datetime.utcnow()
        ))
        session.add(Notification(
            id=uuid.uuid4(),
            user_id=user.id,
            title="Medication Reminder: Aspirin Protect 100mg",
            body="Your lunch dose is due. Tap to confirm intake.",
            category=NotificationCategory.MEDICATION,
            priority=NotificationPriority.URGENT,
            is_read=False,
            created_at=datetime.utcnow()
        ))

        await session.commit()
        print(f"Successfully assigned active prescription, doses, sport plan, nutrition plan, conversation, and appointments to {target_email}!")

if __name__ == "__main__":
    asyncio.run(assign_active_prescription())
