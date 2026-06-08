from datetime import datetime, timezone

from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity
from ..decorators.auth import role_required
from ..database.extensions import db
from ..utils.request_utils import get_json_body
from ..models_db.models import Appointment, AppointmentStatus, MedicalRecord, User, RoleEnum, Patient, Clinic, AIAnalysis
from ..services.clinic_scope import (
    doctor_can_access_medical_record,
    doctor_can_access_patient,
    doctor_medical_record_access_filter,
    get_doctor_profile,
)
from .ai_controller import serialize_ai_analysis


LEGACY_CLINICAL_FIELDS = [
    "anamnesis",
    "physical_exam",
    "diagnostic_hypothesis",
    "diagnosis",
    "conduct",
    "prescriptions",
    "exams_requested",
    "evolution",
]

DERMATOLOGY_FIELDS = [
    "consultation_type",
    "consultation_type_other",
    "chief_complaint",
    "problem_onset",
    "clinical_evolution",
    "associated_symptoms",
    "symptom_other",
    "had_previous_treatment",
    "previous_treatments",
    "has_skin_cancer_history",
    "skin_cancer_history_description",
    "frequent_sun_exposure",
    "sunscreen_use",
    "skin_phototype",
    "has_specific_dermatological_lesion",
    "lesion_location",
    "lesion_description",
    "has_measurable_lesion",
    "lesion_size",
    "lesion_size_unit",
    "lesion_color",
    "lesion_color_other",
    "lesion_borders",
    "lesion_symptoms",
    "wants_image_attachment",
    "image_attachment_notes",
    "has_suspicious_lesion",
    "asymmetry",
    "irregular_borders",
    "varied_color",
    "diameter_greater_than_6mm",
    "recent_evolution_change",
    "suspicion_level",
    "has_requested_exams",
    "has_prescription",
    "needs_follow_up",
    "suggested_return_date",
    "return_guidance",
    "has_referral",
    "referral_target",
    "referral_reason",
    "general_observations",
]

CLINICAL_UPDATE_FIELDS = LEGACY_CLINICAL_FIELDS + DERMATOLOGY_FIELDS
NO_APPOINTMENT_IN_PROGRESS_MESSAGE = (
    "Não é possível criar prontuário: o paciente não possui consulta em andamento."
)

AUTOMATIC_DERMATOLOGY_FIELDS = [
    "attendance_datetime",
    "doctor_name",
    "doctor_crm",
    "doctor_signature",
    "record_datetime",
]


def _iso(value):
    return value.isoformat() + "Z" if value else None


def _parse_date(value, field_name):
    if value in (None, ""):
        return None, None
    try:
        return datetime.fromisoformat(str(value)).date(), None
    except (TypeError, ValueError):
        return None, f"{field_name} deve estar no formato ISO YYYY-MM-DD"


def _apply_clinical_fields(record, data):
    for field in CLINICAL_UPDATE_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if field == "suggested_return_date":
            value, error = _parse_date(value, field)
            if error:
                return error
        setattr(record, field, value)
    return None


def _doctor_signature(actor, doctor_profile):
    if not actor or not doctor_profile:
        return None
    return f"{actor.name} - CRM {doctor_profile.crm}"


def _resolve_clinic_id(actor, data=None):
    if actor.clinic_id is not None:
        return actor.clinic_id
    if data:
        cid = data.get("clinic_id")
        if cid:
            return int(cid)
    clinic = Clinic.query.filter_by(is_active=True).first()
    return clinic.id if clinic else None


def _serialize_medical_record(mr, patient=None, analyses=None):
    payload = {
        "id": mr.id,
        "clinic_id": mr.clinic_id,
        "patient_id": mr.patient_id,
        "patient_name": patient.name if patient else "â€”",
        "doctor_profile_id": mr.doctor_profile_id,
        "appointment_id": mr.appointment_id,
        "created_at": _iso(mr.created_at),
        "updated_at": _iso(mr.updated_at),
    }
    for field in LEGACY_CLINICAL_FIELDS + AUTOMATIC_DERMATOLOGY_FIELDS + DERMATOLOGY_FIELDS:
        value = getattr(mr, field)
        if field in ("attendance_datetime", "record_datetime"):
            value = _iso(value)
        elif field == "suggested_return_date":
            value = value.isoformat() if value else None
        payload[field] = value
    payload["ai_analyses"] = [serialize_ai_analysis(analysis) for analysis in analyses] if analyses else []
    return payload


class MedicalRecordController:
    @role_required("DOCTOR")
    def create(self):
        actor = User.query.get(int(get_jwt_identity()))
        dp = get_doctor_profile(actor)
        if not dp:
            return jsonify({"error": "Doctor profile não encontrado"}), 400
        data = get_json_body()
        if not data:
            return jsonify({"error": "Body JSON inválido ou vazio"}), 400
        required = ["patient_id", "appointment_id"]
        if any(not data.get(k) for k in required):
            return jsonify({"error": "patient_id e appointment_id são obrigatórios"}), 400
        clinic_id = _resolve_clinic_id(actor, data)
        if not clinic_id:
            return jsonify({"error": "Nenhuma clínica disponível"}), 400
        appointment = Appointment.query.get(data["appointment_id"])
        if (
            not appointment
            or appointment.clinic_id != clinic_id
            or appointment.doctor_profile_id != dp.id
            or appointment.patient_id != data["patient_id"]
        ):
            return jsonify({"error": "Consulta nÃ£o encontrada para este mÃ©dico e paciente"}), 404
        if appointment.status != AppointmentStatus.IN_PROGRESS:
            return jsonify({"error": NO_APPOINTMENT_IN_PROGRESS_MESSAGE}), 409
        now = datetime.now(timezone.utc)
        mr = MedicalRecord(
            clinic_id=clinic_id,
            patient_id=appointment.patient_id,
            doctor_profile_id=dp.id,
            appointment_id=appointment.id,
            attendance_datetime=appointment.scheduled_at,
            doctor_name=actor.name,
            doctor_crm=dp.crm,
            doctor_signature=_doctor_signature(actor, dp),
            record_datetime=now,
        )
        error = _apply_clinical_fields(mr, data)
        if error:
            return jsonify({"error": error}), 400
        db.session.add(mr)
        db.session.commit()
        return jsonify({"id": mr.id}), 201

    @role_required("DOCTOR", "CLINIC_ADMIN")
    def list(self):
        actor = User.query.get(int(get_jwt_identity()))
        q = MedicalRecord.query
        if actor.clinic_id is not None:
            q = q.filter_by(clinic_id=actor.clinic_id)
        if actor.role == RoleEnum.DOCTOR:
            dp = get_doctor_profile(actor)
            if not dp:
                return jsonify({"items": [], "total": 0}), 200
            q = q.filter(doctor_medical_record_access_filter(actor))
        patient_id = request.args.get("patient_id", type=int)
        if patient_id:
            q = q.filter_by(patient_id=patient_id)
        records = q.order_by(MedicalRecord.id.desc()).limit(50).all()
        items = []
        for mr in records:
            patient = Patient.query.get(mr.patient_id)
            items.append({
                "id": mr.id,
                "patient_id": mr.patient_id,
                "patient_name": patient.name if patient else "—",
                "appointment_id": mr.appointment_id,
                "diagnosis": mr.diagnosis[:80] if mr.diagnosis else "",
                "created_at": mr.created_at.isoformat() + "Z" if mr.created_at else None,
            })
        return jsonify({"items": items, "total": len(items)}), 200

    @role_required("DOCTOR", "CLINIC_ADMIN")
    def list_by_patient(self, patient_id):
        actor = User.query.get(int(get_jwt_identity()))
        patient = Patient.query.get(patient_id)
        if not patient or (actor.role != RoleEnum.SUPER_ADMIN and patient.clinic_id != actor.clinic_id):
            return jsonify({"error": "Not found"}), 404
        if actor.role == RoleEnum.DOCTOR and not doctor_can_access_patient(actor, patient):
            return jsonify({"error": "Not found"}), 404

        q = MedicalRecord.query.filter_by(patient_id=patient_id)
        if actor.role != RoleEnum.SUPER_ADMIN:
            q = q.filter_by(clinic_id=actor.clinic_id)
        if actor.role == RoleEnum.DOCTOR:
            dp = get_doctor_profile(actor)
            if not dp:
                return jsonify([]), 200
            q = q.filter(doctor_medical_record_access_filter(actor))

        records = q.order_by(MedicalRecord.id.desc()).all()
        return jsonify([{
            "id": mr.id,
            "patient_id": mr.patient_id,
            "appointment_id": mr.appointment_id,
            "doctor_profile_id": mr.doctor_profile_id,
            "diagnosis": mr.diagnosis,
            "created_at": mr.created_at.isoformat() + "Z" if mr.created_at else None,
        } for mr in records]), 200

    @role_required("DOCTOR", "CLINIC_ADMIN")
    def get(self, record_id):
        actor = User.query.get(int(get_jwt_identity()))
        mr = MedicalRecord.query.get(record_id)
        if not mr or (actor.role != RoleEnum.SUPER_ADMIN and mr.clinic_id != actor.clinic_id):
            return jsonify({"error": "Not found"}), 404
        if actor.role == RoleEnum.DOCTOR and not doctor_can_access_medical_record(actor, mr):
            return jsonify({"error": "Forbidden"}), 403
        patient = Patient.query.get(mr.patient_id)
        analyses = (
            AIAnalysis.query
            .filter_by(clinic_id=mr.clinic_id, medical_record_id=mr.id)
            .order_by(AIAnalysis.created_at.desc(), AIAnalysis.id.desc())
            .all()
        )
        return jsonify(_serialize_medical_record(mr, patient=patient, analyses=analyses)), 200

    @role_required("DOCTOR", "CLINIC_ADMIN")
    def ai_analyses(self, medical_record_id):
        actor = User.query.get(int(get_jwt_identity()))
        mr = MedicalRecord.query.get(medical_record_id)
        if not mr or (actor.role != RoleEnum.SUPER_ADMIN and mr.clinic_id != actor.clinic_id):
            return jsonify({"error": "Not found"}), 404
        if actor.role == RoleEnum.DOCTOR and not doctor_can_access_medical_record(actor, mr):
            return jsonify({"error": "Forbidden"}), 403

        analyses = (
            AIAnalysis.query
            .filter_by(clinic_id=mr.clinic_id, medical_record_id=mr.id)
            .order_by(AIAnalysis.created_at.desc(), AIAnalysis.id.desc())
            .all()
        )
        return jsonify([serialize_ai_analysis(analysis) for analysis in analyses]), 200

    @role_required("DOCTOR", "CLINIC_ADMIN")
    def update(self, record_id):
        actor = User.query.get(int(get_jwt_identity()))
        mr = MedicalRecord.query.get(record_id)
        if not mr or (actor.clinic_id is not None and mr.clinic_id != actor.clinic_id):
            return jsonify({"error": "Not found"}), 404
        if not doctor_can_access_medical_record(actor, mr):
            return jsonify({"error": "Forbidden"}), 403
        data = get_json_body()
        if not data:
            return jsonify({"error": "Body JSON inválido ou vazio"}), 400
        error = _apply_clinical_fields(mr, data)
        if error:
            return jsonify({"error": error}), 400
        db.session.commit()
        return jsonify({"id": mr.id}), 200
