from datetime import datetime
from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity
from ..decorators.auth import role_required
from ..models_db.models import Patient, User, RoleEnum
from ..database.extensions import db


class PatientController:
    @role_required("CLINIC_ADMIN", "RECEPTIONIST")
    def create_patient(self):
        actor = User.query.get(int(get_jwt_identity()))
        data = request.get_json(silent=True) or {}
        required = ["name", "cpf", "address", "cep", "phone", "birth_date", "blood_type", "email", "marital_status"]
        if any(not data.get(k) for k in required):
            return jsonify({"error": "Campos obrigatórios ausentes"}), 400
        if Patient.query.filter_by(clinic_id=actor.clinic_id, cpf=data["cpf"]).first():
            return jsonify({"error": "CPF já cadastrado nesta clínica"}), 409
        patient = Patient(clinic_id=actor.clinic_id, name=data["name"], cpf=data["cpf"], address=data["address"], cep=data["cep"], phone=data["phone"], birth_date=datetime.fromisoformat(data["birth_date"]).date(), blood_type=data["blood_type"], email=data["email"], marital_status=data["marital_status"], is_active=True)
        db.session.add(patient)
        db.session.commit()
        return jsonify({"id": patient.id, "name": patient.name}), 201

    @role_required("CLINIC_ADMIN", "RECEPTIONIST", "DOCTOR")
    def list_patients(self):
        actor = User.query.get(int(get_jwt_identity()))
        q = Patient.query.filter_by(clinic_id=actor.clinic_id, is_active=True)
        return jsonify([{"id": p.id, "name": p.name, "cpf": p.cpf, "phone": p.phone, "email": p.email} for p in q.order_by(Patient.id.desc()).all()]), 200

    @role_required("CLINIC_ADMIN", "DOCTOR")
    def get_patient(self, patient_id):
        actor = User.query.get(int(get_jwt_identity()))
        p = Patient.query.get(patient_id)
        if not p or p.clinic_id != actor.clinic_id:
            return jsonify({"error": "Not found"}), 404
        return jsonify({"id": p.id, "clinic_id": p.clinic_id, "name": p.name, "cpf": p.cpf, "address": p.address, "cep": p.cep, "phone": p.phone, "birth_date": p.birth_date.isoformat(), "blood_type": p.blood_type, "email": p.email, "marital_status": p.marital_status, "is_active": p.is_active}), 200

    @role_required("CLINIC_ADMIN", "RECEPTIONIST")
    def update_patient(self, patient_id):
        actor = User.query.get(int(get_jwt_identity()))
        p = Patient.query.get(patient_id)
        if not p or p.clinic_id != actor.clinic_id:
            return jsonify({"error": "Not found"}), 404
        data = request.get_json(silent=True) or {}
        for field in ["name", "address", "cep", "phone", "blood_type", "email", "marital_status"]:
            if field in data:
                setattr(p, field, data[field])
        db.session.commit()
        return jsonify({"id": p.id, "name": p.name}), 200

    @role_required("CLINIC_ADMIN")
    def delete_patient(self, patient_id):
        actor = User.query.get(int(get_jwt_identity()))
        p = Patient.query.get(patient_id)
        if not p or p.clinic_id != actor.clinic_id:
            return jsonify({"error": "Not found"}), 404
        p.is_active = False
        db.session.commit()
        return jsonify({"message": "Paciente desativado"}), 200

    @role_required("DOCTOR")
    def my_patients(self):
        return jsonify([]), 200
