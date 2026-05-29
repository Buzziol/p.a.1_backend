from datetime import datetime
from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity
from ..decorators.auth import role_required
from ..models_db.models import Patient, User, RoleEnum, DoctorProfile, Appointment, Clinic
from ..database.extensions import db
from ..utils.request_utils import get_json_body


def _resolve_clinic_id(actor, data=None):
    if actor.clinic_id is not None:
        return actor.clinic_id
    if data:
        cid = data.get("clinic_id")
        if cid:
            return int(cid)
    clinic = Clinic.query.filter_by(is_active=True).first()
    return clinic.id if clinic else None


class PatientController:
    @role_required("CLINIC_ADMIN", "RECEPTIONIST")
    def create_patient(self):
        actor = User.query.get(int(get_jwt_identity()))
        data = get_json_body()
        if not data:
            return jsonify({"error": "Body JSON inválido ou vazio"}), 400
        required = ["name", "cpf", "address", "cep", "phone", "birth_date", "blood_type", "email", "marital_status"]
        missing = [k for k in required if not data.get(k)]
        if missing:
            return jsonify({"error": f"Campos obrigatórios ausentes: {', '.join(missing)}"}), 400
        clinic_id = _resolve_clinic_id(actor, data)
        if not clinic_id:
            return jsonify({"error": "Nenhuma clínica disponível"}), 400
        if Patient.query.filter_by(clinic_id=clinic_id, cpf=data["cpf"]).first():
            return jsonify({"error": "CPF já cadastrado nesta clínica"}), 409
        patient = Patient(
            clinic_id=clinic_id,
            name=data["name"],
            cpf=data["cpf"],
            address=data["address"],
            cep=data["cep"],
            phone=data["phone"],
            birth_date=datetime.fromisoformat(data["birth_date"]).date(),
            blood_type=data["blood_type"],
            email=data["email"],
            marital_status=data["marital_status"],
            is_active=True,
        )
        db.session.add(patient)
        db.session.commit()
        return jsonify({"id": patient.id, "name": patient.name}), 201

    @role_required("CLINIC_ADMIN", "RECEPTIONIST", "DOCTOR")
    def list_patients(self):
        actor = User.query.get(int(get_jwt_identity()))
        q = Patient.query.filter_by(is_active=True)
        if actor.clinic_id is not None:
            q = q.filter_by(clinic_id=actor.clinic_id)
        search = request.args.get("search", "").strip()
        if search:
            q = q.filter(
                db.or_(
                    Patient.name.ilike(f"%{search}%"),
                    Patient.cpf.ilike(f"%{search}%"),
                    Patient.email.ilike(f"%{search}%"),
                )
            )
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        per_page = min(per_page, 100)
        pagination = q.order_by(Patient.name.asc()).paginate(page=page, per_page=per_page, error_out=False)
        return jsonify({
            "items": [{
                "id": p.id,
                "name": p.name,
                "cpf": p.cpf,
                "phone": p.phone,
                "email": p.email,
                "birth_date": p.birth_date.isoformat() if p.birth_date else None,
            } for p in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "pages": pagination.pages,
        }), 200

    @role_required("CLINIC_ADMIN", "RECEPTIONIST", "DOCTOR")
    def get_patient(self, patient_id):
        actor = User.query.get(int(get_jwt_identity()))
        p = Patient.query.get(patient_id)
        if not p or (actor.clinic_id is not None and p.clinic_id != actor.clinic_id):
            return jsonify({"error": "Not found"}), 404
        return jsonify({
            "id": p.id,
            "clinic_id": p.clinic_id,
            "name": p.name,
            "cpf": p.cpf,
            "address": p.address,
            "cep": p.cep,
            "phone": p.phone,
            "birth_date": p.birth_date.isoformat() if p.birth_date else None,
            "blood_type": p.blood_type,
            "email": p.email,
            "marital_status": p.marital_status,
            "is_active": p.is_active,
        }), 200

    @role_required("CLINIC_ADMIN", "RECEPTIONIST")
    def update_patient(self, patient_id):
        actor = User.query.get(int(get_jwt_identity()))
        p = Patient.query.get(patient_id)
        if not p or (actor.clinic_id is not None and p.clinic_id != actor.clinic_id):
            return jsonify({"error": "Not found"}), 404
        data = get_json_body()
        if not data:
            return jsonify({"error": "Body JSON inválido ou vazio"}), 400
        for field in ["name", "address", "cep", "phone", "blood_type", "email", "marital_status"]:
            if field in data:
                setattr(p, field, data[field])
        if "birth_date" in data:
            p.birth_date = datetime.fromisoformat(data["birth_date"]).date()
        db.session.commit()
        return jsonify({"id": p.id, "name": p.name}), 200

    @role_required("CLINIC_ADMIN")
    def delete_patient(self, patient_id):
        actor = User.query.get(int(get_jwt_identity()))
        p = Patient.query.get(patient_id)
        if not p or (actor.clinic_id is not None and p.clinic_id != actor.clinic_id):
            return jsonify({"error": "Not found"}), 404
        p.is_active = False
        db.session.commit()
        return jsonify({"message": "Paciente desativado"}), 200

    @role_required("DOCTOR")
    def my_patients(self):
        """Retorna pacientes que possuem consultas com este médico."""
        actor = User.query.get(int(get_jwt_identity()))
        dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
        if not dp:
            return jsonify([]), 200
        patient_ids = (
            db.session.query(Appointment.patient_id)
            .filter(
                Appointment.clinic_id == actor.clinic_id,
                Appointment.doctor_profile_id == dp.id,
            )
            .distinct()
            .subquery()
        )
        patients = Patient.query.filter(
            Patient.id.in_(patient_ids),
            Patient.is_active == True,
        ).order_by(Patient.name.asc()).all()
        return jsonify([{
            "id": p.id,
            "name": p.name,
            "cpf": p.cpf,
            "phone": p.phone,
            "email": p.email,
        } for p in patients]), 200
