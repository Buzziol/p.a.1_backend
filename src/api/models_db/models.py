import enum
from werkzeug.security import generate_password_hash, check_password_hash
from ..database.extensions import db
from .base import TimestampMixin


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
    birth_date = db.Column(db.Date, nullable=False)
    blood_type = db.Column(db.String(8), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    marital_status = db.Column(db.String(64), nullable=False)
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
