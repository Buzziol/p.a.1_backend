from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity
from ..decorators.auth import role_required
from ..database.extensions import db
from ..utils.request_utils import get_json_body
from ..models_db.models import MedicalRecord, User, RoleEnum, DoctorProfile


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
        mr = MedicalRecord(
            clinic_id=actor.clinic_id,
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
    def get(self, record_id):
        actor = User.query.get(int(get_jwt_identity()))
        mr = MedicalRecord.query.get(record_id)
        if not mr or (actor.role != RoleEnum.SUPER_ADMIN and mr.clinic_id != actor.clinic_id):
            return jsonify({"error": "Not found"}), 404
        if actor.role == RoleEnum.DOCTOR:
            dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
            if not dp or mr.doctor_profile_id != dp.id:
                return jsonify({"error": "Forbidden"}), 403
        return jsonify({
            "id": mr.id,
            "clinic_id": mr.clinic_id,
            "patient_id": mr.patient_id,
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
        }), 200

    @role_required("DOCTOR")
    def update(self, record_id):
        actor = User.query.get(int(get_jwt_identity()))
        dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
        mr = MedicalRecord.query.get(record_id)
        if not mr or mr.clinic_id != actor.clinic_id:
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
