from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity
from ..decorators.auth import role_required
from ..database.extensions import db
from ..utils.request_utils import get_json_body
from ..models_db.models import MedicalRecord, User, RoleEnum, DoctorProfile, Patient, Clinic, AIAnalysis
from .ai_controller import serialize_ai_analysis


def _resolve_clinic_id(actor, data=None):
    if actor.clinic_id is not None:
        return actor.clinic_id
    if data:
        cid = data.get("clinic_id")
        if cid:
            return int(cid)
    clinic = Clinic.query.filter_by(is_active=True).first()
    return clinic.id if clinic else None


class MedicalRecordController:
    @role_required("DOCTOR")
    def create(self):
        actor = User.query.get(int(get_jwt_identity()))
        dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
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
        mr = MedicalRecord(
            clinic_id=clinic_id,
            patient_id=data["patient_id"],
            doctor_profile_id=dp.id,
            appointment_id=data["appointment_id"],
            anamnesis=data.get("anamnesis", ""),
            physical_exam=data.get("physical_exam", ""),
            diagnostic_hypothesis=data.get("diagnostic_hypothesis", ""),
            diagnosis=data.get("diagnosis", ""),
            conduct=data.get("conduct", ""),
            prescriptions=data.get("prescriptions", ""),
            exams_requested=data.get("exams_requested", ""),
            evolution=data.get("evolution", ""),
        )
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
            dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
            if not dp:
                return jsonify({"items": [], "total": 0}), 200
            q = q.filter_by(doctor_profile_id=dp.id)
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

        q = MedicalRecord.query.filter_by(patient_id=patient_id)
        if actor.role != RoleEnum.SUPER_ADMIN:
            q = q.filter_by(clinic_id=actor.clinic_id)
        if actor.role == RoleEnum.DOCTOR:
            dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
            if not dp:
                return jsonify([]), 200
            q = q.filter_by(doctor_profile_id=dp.id)

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
        if actor.role == RoleEnum.DOCTOR:
            dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
            if not dp or mr.doctor_profile_id != dp.id:
                return jsonify({"error": "Forbidden"}), 403
        patient = Patient.query.get(mr.patient_id)
        analyses = (
            AIAnalysis.query
            .filter_by(clinic_id=mr.clinic_id, medical_record_id=mr.id)
            .order_by(AIAnalysis.created_at.desc(), AIAnalysis.id.desc())
            .all()
        )
        return jsonify({
            "id": mr.id,
            "clinic_id": mr.clinic_id,
            "patient_id": mr.patient_id,
            "patient_name": patient.name if patient else "—",
            "doctor_profile_id": mr.doctor_profile_id,
            "appointment_id": mr.appointment_id,
            "anamnesis": mr.anamnesis,
            "physical_exam": mr.physical_exam,
            "diagnostic_hypothesis": mr.diagnostic_hypothesis,
            "diagnosis": mr.diagnosis,
            "conduct": mr.conduct,
            "prescriptions": mr.prescriptions,
            "exams_requested": mr.exams_requested,
            "evolution": mr.evolution,
            "ai_analyses": [serialize_ai_analysis(analysis) for analysis in analyses],
            "created_at": mr.created_at.isoformat() + "Z" if mr.created_at else None,
        }), 200

    @role_required("DOCTOR", "CLINIC_ADMIN")
    def ai_analyses(self, medical_record_id):
        actor = User.query.get(int(get_jwt_identity()))
        mr = MedicalRecord.query.get(medical_record_id)
        if not mr or (actor.role != RoleEnum.SUPER_ADMIN and mr.clinic_id != actor.clinic_id):
            return jsonify({"error": "Not found"}), 404
        if actor.role == RoleEnum.DOCTOR:
            dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
            if not dp or mr.doctor_profile_id != dp.id:
                return jsonify({"error": "Forbidden"}), 403

        analyses = (
            AIAnalysis.query
            .filter_by(clinic_id=mr.clinic_id, medical_record_id=mr.id)
            .order_by(AIAnalysis.created_at.desc(), AIAnalysis.id.desc())
            .all()
        )
        return jsonify([serialize_ai_analysis(analysis) for analysis in analyses]), 200

    @role_required("DOCTOR")
    def update(self, record_id):
        actor = User.query.get(int(get_jwt_identity()))
        dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
        mr = MedicalRecord.query.get(record_id)
        if not mr or (actor.clinic_id is not None and mr.clinic_id != actor.clinic_id):
            return jsonify({"error": "Not found"}), 404
        if not dp or mr.doctor_profile_id != dp.id:
            return jsonify({"error": "Forbidden"}), 403
        data = get_json_body()
        if not data:
            return jsonify({"error": "Body JSON inválido ou vazio"}), 400
        for field in ["anamnesis", "physical_exam", "diagnostic_hypothesis", "diagnosis", "conduct", "prescriptions", "exams_requested", "evolution"]:
            if field in data:
                setattr(mr, field, data[field])
        db.session.commit()
        return jsonify({"id": mr.id}), 200
