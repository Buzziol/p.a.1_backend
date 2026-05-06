from datetime import datetime, timedelta, timezone
from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity
from ..decorators.auth import role_required, jwt_required_custom
from ..models_db.models import (
    Clinic, User, RoleEnum, AuditLog, Patient, Appointment,
    AppointmentStatus, MedicalRecord, DoctorProfile,
)
from ..database.extensions import db
from ..utils.request_utils import get_json_body


class AdminController:
    @role_required("SUPER_ADMIN")
    def list_clinics(self):
        clinics = Clinic.query.order_by(Clinic.id.asc()).all()
        return jsonify([{
            "id": c.id,
            "name": c.name,
            "cnpj": c.cnpj,
            "phone": c.phone,
            "email": c.email,
            "is_active": c.is_active,
        } for c in clinics]), 200

    @role_required("SUPER_ADMIN")
    def create_clinic(self):
        data = get_json_body()
        if not data:
            return jsonify({"error": "Body JSON inválido ou vazio"}), 400
        if not data.get("name"):
            return jsonify({"error": "name é obrigatório"}), 400
        clinic = Clinic(
            name=data["name"],
            cnpj=data.get("cnpj"),
            phone=data.get("phone"),
            email=data.get("email"),
            is_active=True,
        )
        db.session.add(clinic)
        db.session.flush()
        actor_id = int(get_jwt_identity())
        db.session.add(AuditLog(
            clinic_id=clinic.id,
            user_id=actor_id,
            action="CREATE",
            entity_type="Clinic",
            entity_id=str(clinic.id),
            metadata_json=data,
            ip_address=request.remote_addr,
        ))
        db.session.commit()
        return jsonify({"id": clinic.id, "name": clinic.name}), 201

    @role_required("SUPER_ADMIN", "CLINIC_ADMIN")
    def list_users(self):
        actor = User.query.get(int(get_jwt_identity()))
        query = User.query
        if actor.role == RoleEnum.CLINIC_ADMIN:
            query = query.filter_by(clinic_id=actor.clinic_id)
        users = query.order_by(User.id.asc()).all()
        return jsonify([{
            "id": u.id,
            "clinic_id": u.clinic_id,
            "name": u.name,
            "email": u.email,
            "role": u.role.value,
            "is_active": u.is_active,
        } for u in users]), 200

    @role_required("SUPER_ADMIN", "CLINIC_ADMIN")
    def create_user(self):
        actor = User.query.get(int(get_jwt_identity()))
        data = get_json_body()
        if not data:
            return jsonify({"error": "Body JSON inválido ou vazio"}), 400
        required = ["name", "email", "password", "role"]
        if any(not data.get(k) for k in required):
            return jsonify({"error": "name, email, password, role obrigatórios"}), 400

        try:
            role_enum = RoleEnum(data["role"])
        except ValueError:
            return jsonify({"error": "role inválido"}), 400

        if User.query.filter_by(email=data["email"]).first():
            return jsonify({"error": "Email já cadastrado"}), 409

        clinic_id = data.get("clinic_id")
        if actor.role == RoleEnum.CLINIC_ADMIN:
            clinic_id = actor.clinic_id
            if role_enum == RoleEnum.SUPER_ADMIN:
                return jsonify({"error": "Forbidden"}), 403

        user = User(
            name=data["name"],
            email=data["email"],
            role=role_enum,
            clinic_id=clinic_id,
            is_active=True,
        )
        user.set_password(data["password"])
        db.session.add(user)
        db.session.flush()

        # Criar DoctorProfile automaticamente se role for DOCTOR
        if role_enum == RoleEnum.DOCTOR:
            dp = DoctorProfile(
                user_id=user.id,
                crm=data.get("crm", ""),
                phone=data.get("phone", ""),
            )
            db.session.add(dp)

        db.session.add(AuditLog(
            clinic_id=clinic_id,
            user_id=actor.id,
            action="CREATE",
            entity_type="User",
            entity_id=str(user.id),
            metadata_json={"email": user.email, "role": user.role.value},
            ip_address=request.remote_addr,
        ))
        db.session.commit()
        return jsonify({"id": user.id, "email": user.email}), 201

    @role_required("SUPER_ADMIN", "CLINIC_ADMIN")
    def list_audit_logs(self):
        actor = User.query.get(int(get_jwt_identity()))
        query = AuditLog.query
        if actor.role == RoleEnum.CLINIC_ADMIN:
            query = query.filter_by(clinic_id=actor.clinic_id)
        logs = query.order_by(AuditLog.id.desc()).limit(200).all()
        return jsonify([{
            "id": l.id,
            "clinic_id": l.clinic_id,
            "user_id": l.user_id,
            "action": l.action,
            "entity_type": l.entity_type,
            "entity_id": l.entity_id,
            "metadata_json": l.metadata_json,
            "ip_address": l.ip_address,
            "created_at": l.created_at.isoformat() + "Z",
        } for l in logs]), 200

    @jwt_required_custom
    def dashboard(self):
        """Retorna métricas para o dashboard baseado no role do usuário."""
        actor = User.query.get(int(get_jwt_identity()))
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        result = {}

        if actor.role == RoleEnum.SUPER_ADMIN:
            result["total_clinics"] = Clinic.query.filter_by(is_active=True).count()
            result["total_users"] = User.query.filter_by(is_active=True).count()
            result["total_patients"] = Patient.query.filter_by(is_active=True).count()
        else:
            clinic_id = actor.clinic_id
            result["total_patients"] = Patient.query.filter_by(
                clinic_id=clinic_id, is_active=True
            ).count()
            result["appointments_today"] = Appointment.query.filter(
                Appointment.clinic_id == clinic_id,
                Appointment.scheduled_at >= today_start,
                Appointment.scheduled_at < today_end,
                Appointment.status.notin_([AppointmentStatus.CANCELLED]),
            ).count()
            result["appointments_scheduled"] = Appointment.query.filter(
                Appointment.clinic_id == clinic_id,
                Appointment.status == AppointmentStatus.SCHEDULED,
            ).count()
            result["recent_records"] = MedicalRecord.query.filter_by(
                clinic_id=clinic_id,
            ).order_by(MedicalRecord.id.desc()).limit(5).count()

        if actor.role == RoleEnum.DOCTOR:
            dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
            if dp:
                result["my_appointments_today"] = Appointment.query.filter(
                    Appointment.clinic_id == actor.clinic_id,
                    Appointment.doctor_profile_id == dp.id,
                    Appointment.scheduled_at >= today_start,
                    Appointment.scheduled_at < today_end,
                    Appointment.status.notin_([AppointmentStatus.CANCELLED]),
                ).count()

        return jsonify(result), 200
