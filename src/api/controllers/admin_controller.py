from datetime import datetime, timedelta, timezone
from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity
from ..decorators.auth import role_required, jwt_required_custom
from ..models_db.models import (
    Clinic, User, RoleEnum, AuditLog, Patient, Appointment,
    AppointmentStatus, DoctorProfile,
)
from ..database.extensions import db
from ..utils.request_utils import get_json_body


TODAY_STATUSES = (
    AppointmentStatus.SCHEDULED,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.IN_PROGRESS,
)
SCHEDULED_STATUSES = (
    AppointmentStatus.SCHEDULED,
    AppointmentStatus.CONFIRMED,
)
WEEKLY_STATUSES = (
    AppointmentStatus.SCHEDULED,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.IN_PROGRESS,
    AppointmentStatus.COMPLETED,
)
WEEKDAY_LABELS = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")


def _today():
    return datetime.now(timezone.utc).date()


def _empty_dashboard():
    return {
        "active_clinics": 0,
        "active_users": 0,
        "total_patients": 0,
        "appointments_today": 0,
        "appointments_scheduled": 0,
        "completed_month": 0,
        "my_appointments_today": 0,
        "weekly_appointments": _empty_weekly_appointments(),
    }


def _empty_weekly_appointments():
    return [{"day": day, "count": 0} for day in WEEKDAY_LABELS]


def _date_filter(query, column, target_date):
    return query.filter(db.func.date(column) == target_date.isoformat())


def _month_filter(query, column, target_date):
    return query.filter(
        db.extract("year", column) == target_date.year,
        db.extract("month", column) == target_date.month,
    )


def _week_bounds(target_date):
    week_start = target_date - timedelta(days=target_date.weekday())
    return week_start, week_start + timedelta(days=6)


def _weekly_appointments(query, target_date):
    week_start, week_end = _week_bounds(target_date)
    rows = query.filter(
        Appointment.status.in_(WEEKLY_STATUSES),
        db.func.date(Appointment.scheduled_at) >= week_start.isoformat(),
        db.func.date(Appointment.scheduled_at) <= week_end.isoformat(),
    ).with_entities(Appointment.scheduled_at).all()

    counts_by_date = {week_start + timedelta(days=i): 0 for i in range(7)}
    for row in rows:
        scheduled_at = row.scheduled_at
        scheduled_date = scheduled_at.date() if scheduled_at else None
        if scheduled_date in counts_by_date:
            counts_by_date[scheduled_date] += 1

    return [
        {"day": WEEKDAY_LABELS[i], "count": int(counts_by_date[week_start + timedelta(days=i)])}
        for i in range(7)
    ]


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

    @role_required("SUPER_ADMIN", "CLINIC_ADMIN", "RECEPTIONIST")
    def list_users(self):
        actor = User.query.get(int(get_jwt_identity()))
        query = User.query
        if actor.role in (RoleEnum.CLINIC_ADMIN, RoleEnum.RECEPTIONIST):
            query = query.filter_by(clinic_id=actor.clinic_id)
        users = query.order_by(User.id.asc()).all()
        result = []
        for u in users:
            row = {
                "id": u.id,
                "clinic_id": u.clinic_id,
                "name": u.name,
                "email": u.email,
                "role": u.role.value,
                "is_active": u.is_active,
                "doctor_profile_id": None,
            }
            if u.role == RoleEnum.DOCTOR:
                dp = DoctorProfile.query.filter_by(user_id=u.id).first()
                row["doctor_profile_id"] = dp.id if dp else None
            result.append(row)
        return jsonify(result), 200

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
        if role_enum != RoleEnum.SUPER_ADMIN and not clinic_id:
            return jsonify({"error": "clinic_id obrigatório para usuários não SUPER_ADMIN"}), 400

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
        target_date = _today()
        result = _empty_dashboard()

        appointment_query = Appointment.query
        patient_query = Patient.query.filter(Patient.is_active.is_(True))

        if actor.role == RoleEnum.SUPER_ADMIN:
            result["active_clinics"] = Clinic.query.filter(Clinic.is_active.is_(True)).count()
            result["active_users"] = User.query.filter(User.is_active.is_(True)).count()
        else:
            clinic_id = actor.clinic_id
            appointment_query = appointment_query.filter(Appointment.clinic_id == clinic_id)
            patient_query = patient_query.filter(Patient.clinic_id == clinic_id)
            if actor.role == RoleEnum.DOCTOR:
                dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
                if dp:
                    appointment_query = appointment_query.filter(Appointment.doctor_profile_id == dp.id)
                    patient_query = Patient.query.join(
                        Appointment,
                        Patient.id == Appointment.patient_id,
                    ).filter(
                        Patient.is_active.is_(True),
                        Appointment.doctor_profile_id == dp.id,
                    )
                    if actor.clinic_id is not None:
                        patient_query = patient_query.filter(Patient.clinic_id == actor.clinic_id)
                else:
                    appointment_query = appointment_query.filter(False)
                    patient_query = patient_query.filter(False)

        result["total_patients"] = patient_query.with_entities(
            db.func.count(db.distinct(Patient.id))
        ).scalar() or 0
        result["appointments_today"] = _date_filter(
            appointment_query.filter(Appointment.status.in_(TODAY_STATUSES)),
            Appointment.scheduled_at,
            target_date,
        ).count()
        result["appointments_scheduled"] = appointment_query.filter(
            Appointment.status.in_(SCHEDULED_STATUSES),
        ).count()
        result["completed_month"] = _month_filter(
            appointment_query.filter(Appointment.status == AppointmentStatus.COMPLETED),
            Appointment.scheduled_at,
            target_date,
        ).count()
        result["weekly_appointments"] = _weekly_appointments(appointment_query, target_date)

        if actor.role == RoleEnum.DOCTOR:
            result["my_appointments_today"] = result["appointments_today"]

        return jsonify(result), 200
