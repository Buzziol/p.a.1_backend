import enum
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from ..database.extensions import db
from .base import TimestampMixin


def _utcnow():
    return datetime.now(timezone.utc)


class RoleEnum(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    CLINIC_ADMIN = "CLINIC_ADMIN"
    DOCTOR = "DOCTOR"
    RECEPTIONIST = "RECEPTIONIST"


class Clinic(TimestampMixin, db.Model):
    __tablename__ = "clinics"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    cnpj = db.Column(db.String(32), unique=True, nullable=True)
    phone = db.Column(db.String(32))
    email = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class Unit(TimestampMixin, db.Model):
    __tablename__ = "units"
    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinics.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    address = db.Column(db.String(255))
    cep = db.Column(db.String(16))
    phone = db.Column(db.String(32))
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class User(TimestampMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinics.id"), nullable=True, index=True)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum(RoleEnum), nullable=False, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class DoctorProfile(TimestampMixin, db.Model):
    __tablename__ = "doctor_profiles"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    crm = db.Column(db.String(32), nullable=False)
    phone = db.Column(db.String(32))


class Specialty(TimestampMixin, db.Model):
    __tablename__ = "specialties"
    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinics.id"), nullable=True, index=True)
    name = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class DoctorSpecialty(db.Model):
    __tablename__ = "doctor_specialties"
    id = db.Column(db.Integer, primary_key=True)
    doctor_profile_id = db.Column(db.Integer, db.ForeignKey("doctor_profiles.id"), nullable=False)
    specialty_id = db.Column(db.Integer, db.ForeignKey("specialties.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())


class DoctorClinic(db.Model):
    __tablename__ = "doctor_clinics"
    id = db.Column(db.Integer, primary_key=True)
    doctor_profile_id = db.Column(db.Integer, db.ForeignKey("doctor_profiles.id"), nullable=False)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinics.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinics.id"), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(100), nullable=False)
    entity_id = db.Column(db.String(64), nullable=False)
    metadata_json = db.Column(db.JSON, nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())


class Patient(TimestampMixin, db.Model):
    __tablename__ = "patients"
    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinics.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    cpf = db.Column(db.String(20), nullable=False)
    address = db.Column(db.String(255), nullable=False)
    cep = db.Column(db.String(16), nullable=False)
    phone = db.Column(db.String(32), nullable=False)
    sex = db.Column(db.String(32), nullable=True)
    mother_name = db.Column(db.String(255), nullable=True)
    birthplace = db.Column(db.String(255), nullable=True)
    street = db.Column(db.String(255), nullable=True)
    address_number = db.Column(db.String(32), nullable=True)
    address_complement = db.Column(db.String(255), nullable=True)
    neighborhood = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(255), nullable=True)
    state = db.Column(db.String(64), nullable=True)
    birth_date = db.Column(db.Date, nullable=False)
    blood_type = db.Column(db.String(8), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    marital_status = db.Column(db.String(64), nullable=False)
    has_health_insurance = db.Column(db.Boolean, nullable=False, default=False)
    health_insurance_name = db.Column(db.String(255), nullable=True)
    health_insurance_plan = db.Column(db.String(255), nullable=True)
    health_insurance_card_number = db.Column(db.String(64), nullable=True)
    health_insurance_valid_until = db.Column(db.Date, nullable=True)
    health_insurance_notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    __table_args__ = (db.UniqueConstraint('clinic_id', 'cpf', name='uq_patient_clinic_cpf'),)


class AppointmentStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    RESCHEDULED = "RESCHEDULED"


class Appointment(TimestampMixin, db.Model):
    __tablename__ = "appointments"
    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    doctor_profile_id = db.Column(db.Integer, db.ForeignKey("doctor_profiles.id"), nullable=False, index=True)
    scheduled_at = db.Column(db.DateTime, nullable=False, index=True)
    status = db.Column(db.Enum(AppointmentStatus), nullable=False, default=AppointmentStatus.SCHEDULED)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)


class ScheduleBlock(db.Model):
    __tablename__ = "schedule_blocks"
    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinics.id"), nullable=False, index=True)
    doctor_profile_id = db.Column(db.Integer, db.ForeignKey("doctor_profiles.id"), nullable=False, index=True)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())


class MedicalRecord(TimestampMixin, db.Model):
    __tablename__ = "medical_records"
    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    doctor_profile_id = db.Column(db.Integer, db.ForeignKey("doctor_profiles.id"), nullable=False, index=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), nullable=False, index=True)
    anamnesis = db.Column(db.Text, nullable=False, default="")
    physical_exam = db.Column(db.Text, nullable=False, default="")
    diagnostic_hypothesis = db.Column(db.Text, nullable=False, default="")
    diagnosis = db.Column(db.Text, nullable=False, default="")
    conduct = db.Column(db.Text, nullable=False, default="")
    prescriptions = db.Column(db.Text, nullable=False, default="")
    exams_requested = db.Column(db.Text, nullable=False, default="")
    evolution = db.Column(db.Text, nullable=False, default="")
    attendance_datetime = db.Column(db.DateTime, nullable=True)
    doctor_name = db.Column(db.String(255), nullable=True)
    doctor_crm = db.Column(db.String(32), nullable=True)
    consultation_type = db.Column(db.String(64), nullable=True)
    consultation_type_other = db.Column(db.String(255), nullable=True)
    chief_complaint = db.Column(db.Text, nullable=True)
    problem_onset = db.Column(db.String(255), nullable=True)
    clinical_evolution = db.Column(db.Text, nullable=True)
    associated_symptoms = db.Column(db.JSON, nullable=True)
    symptom_other = db.Column(db.String(255), nullable=True)
    had_previous_treatment = db.Column(db.Boolean, nullable=True)
    previous_treatments = db.Column(db.Text, nullable=True)
    has_skin_cancer_history = db.Column(db.Boolean, nullable=True)
    skin_cancer_history_description = db.Column(db.Text, nullable=True)
    frequent_sun_exposure = db.Column(db.Boolean, nullable=True)
    sunscreen_use = db.Column(db.String(64), nullable=True)
    skin_phototype = db.Column(db.String(64), nullable=True)
    has_specific_dermatological_lesion = db.Column(db.Boolean, nullable=True)
    lesion_location = db.Column(db.Text, nullable=True)
    lesion_description = db.Column(db.Text, nullable=True)
    has_measurable_lesion = db.Column(db.Boolean, nullable=True)
    lesion_size = db.Column(db.String(64), nullable=True)
    lesion_size_unit = db.Column(db.String(16), nullable=True)
    lesion_color = db.Column(db.String(64), nullable=True)
    lesion_color_other = db.Column(db.String(255), nullable=True)
    lesion_borders = db.Column(db.String(64), nullable=True)
    lesion_symptoms = db.Column(db.JSON, nullable=True)
    wants_image_attachment = db.Column(db.Boolean, nullable=True)
    image_attachment_notes = db.Column(db.Text, nullable=True)
    has_suspicious_lesion = db.Column(db.Boolean, nullable=True)
    asymmetry = db.Column(db.Boolean, nullable=True)
    irregular_borders = db.Column(db.Boolean, nullable=True)
    varied_color = db.Column(db.Boolean, nullable=True)
    diameter_greater_than_6mm = db.Column(db.Boolean, nullable=True)
    recent_evolution_change = db.Column(db.Boolean, nullable=True)
    suspicion_level = db.Column(db.String(64), nullable=True)
    has_requested_exams = db.Column(db.Boolean, nullable=True)
    has_prescription = db.Column(db.Boolean, nullable=True)
    needs_follow_up = db.Column(db.Boolean, nullable=True)
    suggested_return_date = db.Column(db.Date, nullable=True)
    return_guidance = db.Column(db.Text, nullable=True)
    has_referral = db.Column(db.Boolean, nullable=True)
    referral_target = db.Column(db.String(255), nullable=True)
    referral_reason = db.Column(db.Text, nullable=True)
    general_observations = db.Column(db.Text, nullable=True)
    doctor_signature = db.Column(db.String(255), nullable=True)
    record_datetime = db.Column(db.DateTime, nullable=True)
    ai_analyses = db.relationship(
        "AIAnalysis",
        back_populates="medical_record",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )


class Document(db.Model):
    __tablename__ = "documents"
    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinics.id"), nullable=False, index=True)
    medical_record_id = db.Column(db.Integer, db.ForeignKey("medical_records.id"), nullable=False, index=True)
    file_path = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(100), nullable=False)
    document_category = db.Column(db.String(32), nullable=False, default="OTHER_DOCUMENT")
    uploaded_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())


class DoctorAgreementEnum(str, enum.Enum):
    YES = "YES"
    NO = "NO"
    PARTIAL = "PARTIAL"


class AIAnalysis(db.Model):
    __tablename__ = "ai_analyses"
    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinics.id"), nullable=False, index=True)
    medical_record_id = db.Column(db.Integer, db.ForeignKey("medical_records.id"), nullable=False, index=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=False, index=True)
    ai_diagnosis = db.Column(db.String(64), nullable=False)
    probability = db.Column(db.Float, nullable=False)
    confidence_level = db.Column(db.String(32), nullable=False)
    recommendation = db.Column(db.Text, nullable=False)
    model_version = db.Column(db.String(64), nullable=False)
    disclaimer = db.Column(db.Text, nullable=False)
    doctor_agreement = db.Column(db.Enum(DoctorAgreementEnum), nullable=True)
    doctor_final_assessment = db.Column(db.Text, nullable=True)
    doctor_notes = db.Column(db.Text, nullable=True)
    validated_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    medical_record = db.relationship("MedicalRecord", back_populates="ai_analyses")
    document = db.relationship("Document")


class RefreshToken(db.Model):
    __tablename__ = "refresh_tokens"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    token = db.Column(db.String(512), unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    user = db.relationship("User", backref=db.backref("refresh_tokens", lazy="dynamic"))

    @classmethod
    def create(cls, user_id: int, expires_in_days: int = 30) -> "RefreshToken":
        import secrets
        from datetime import datetime, timedelta
        token = secrets.token_urlsafe(48)
        rt = cls(
            user_id=user_id,
            token=token,
            expires_at=datetime.utcnow() + timedelta(days=expires_in_days),
        )
        db.session.add(rt)
        db.session.flush()
        return rt

    def is_valid(self) -> bool:
        from datetime import datetime
        return not self.revoked and self.expires_at > datetime.utcnow()

    def revoke(self):
        self.revoked = True
