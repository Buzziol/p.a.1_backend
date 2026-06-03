from flask_jwt_extended import get_jwt_identity
from ..database.extensions import db
from ..models_db.models import Appointment, DoctorProfile, MedicalRecord, RoleEnum, User


def get_current_user():
    uid = int(get_jwt_identity())
    return User.query.get(uid)


def assert_clinic_scope(entity_clinic_id):
    user = get_current_user()
    if user.role == RoleEnum.SUPER_ADMIN:
        return True
    return user.clinic_id == entity_clinic_id


def get_doctor_profile(user):
    if not user or user.role != RoleEnum.DOCTOR:
        return None
    return DoctorProfile.query.filter_by(user_id=user.id).first()


def doctor_patient_appointment_exists(user, patient_id):
    dp = get_doctor_profile(user)
    if not dp:
        return False
    query = Appointment.query.filter(
        Appointment.patient_id == patient_id,
        Appointment.doctor_profile_id == dp.id,
    )
    if user.clinic_id is not None:
        query = query.filter(Appointment.clinic_id == user.clinic_id)
    return query.first() is not None


def doctor_patient_medical_record_exists(user, patient_id):
    dp = get_doctor_profile(user)
    if not dp:
        return False
    query = MedicalRecord.query.filter(
        MedicalRecord.patient_id == patient_id,
        doctor_medical_record_access_filter(user),
    )
    if user.clinic_id is not None:
        query = query.filter(MedicalRecord.clinic_id == user.clinic_id)
    return query.first() is not None


def doctor_can_access_patient(user, patient):
    if not user or not patient:
        return False
    if user.role != RoleEnum.DOCTOR:
        return True
    if user.clinic_id is not None and patient.clinic_id != user.clinic_id:
        return False
    return (
        doctor_patient_appointment_exists(user, patient.id)
        or doctor_patient_medical_record_exists(user, patient.id)
    )


def doctor_medical_record_access_filter(user):
    dp = get_doctor_profile(user)
    if not dp:
        return db.false()
    return db.or_(
        MedicalRecord.doctor_profile_id == dp.id,
        db.exists().where(
            db.and_(
                Appointment.patient_id == MedicalRecord.patient_id,
                Appointment.doctor_profile_id == dp.id,
                Appointment.clinic_id == MedicalRecord.clinic_id,
            )
        ),
        db.exists().where(
            db.and_(
                Appointment.id == MedicalRecord.appointment_id,
                Appointment.patient_id == MedicalRecord.patient_id,
                Appointment.doctor_profile_id == dp.id,
                Appointment.clinic_id == MedicalRecord.clinic_id,
            )
        ),
    )


def doctor_can_access_medical_record(user, medical_record):
    if not user or not medical_record:
        return False
    if user.role != RoleEnum.DOCTOR:
        return True
    dp = get_doctor_profile(user)
    if not dp:
        return False
    if user.clinic_id is not None and medical_record.clinic_id != user.clinic_id:
        return False
    return MedicalRecord.query.filter(
        MedicalRecord.id == medical_record.id,
        doctor_medical_record_access_filter(user),
    ).first() is not None
