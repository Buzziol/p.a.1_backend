from datetime import datetime
from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity
from ..decorators.auth import role_required
from ..models_db.models import Appointment, AppointmentStatus, User, RoleEnum, DoctorProfile, ScheduleBlock
from ..database.extensions import db


class AppointmentController:
    def _has_conflict(self, clinic_id, doctor_profile_id, scheduled_at, exclude_id=None):
        q = Appointment.query.filter_by(clinic_id=clinic_id, doctor_profile_id=doctor_profile_id, scheduled_at=scheduled_at)
        if exclude_id:
            q = q.filter(Appointment.id != exclude_id)
        q = q.filter(Appointment.status.in_([AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED, AppointmentStatus.IN_PROGRESS]))
        return q.first() is not None

    def _is_blocked(self, clinic_id, doctor_profile_id, scheduled_at):
        return ScheduleBlock.query.filter(
            ScheduleBlock.clinic_id == clinic_id,
            ScheduleBlock.doctor_profile_id == doctor_profile_id,
            ScheduleBlock.start_time <= scheduled_at,
            ScheduleBlock.end_time >= scheduled_at
        ).first() is not None

    @role_required("CLINIC_ADMIN", "RECEPTIONIST")
    def create(self):
        actor = User.query.get(int(get_jwt_identity()))
        data = request.get_json(silent=True) or {}
        required = ["patient_id", "doctor_profile_id", "scheduled_at"]
        if any(not data.get(k) for k in required):
            return jsonify({"error": "Campos obrigatórios ausentes"}), 400
        dt = datetime.fromisoformat(data["scheduled_at"])
        if self._has_conflict(actor.clinic_id, data["doctor_profile_id"], dt):
            return jsonify({"error": "Conflito de agenda"}), 409
        if self._is_blocked(actor.clinic_id, data["doctor_profile_id"], dt):
            return jsonify({"error": "Horário bloqueado"}), 409
        ap = Appointment(clinic_id=actor.clinic_id, patient_id=data["patient_id"], doctor_profile_id=data["doctor_profile_id"], scheduled_at=dt, status=AppointmentStatus.SCHEDULED, notes=data.get("notes"), created_by=actor.id)
        db.session.add(ap)
        db.session.commit()
        return jsonify({"id": ap.id, "status": ap.status.value}), 201

    @role_required("CLINIC_ADMIN", "RECEPTIONIST")
    def list(self):
        actor = User.query.get(int(get_jwt_identity()))
        rows = Appointment.query.filter_by(clinic_id=actor.clinic_id).order_by(Appointment.scheduled_at.desc()).all()
        return jsonify([{"id": a.id, "patient_id": a.patient_id, "doctor_profile_id": a.doctor_profile_id, "scheduled_at": a.scheduled_at.isoformat(), "status": a.status.value} for a in rows]), 200

    @role_required("DOCTOR")
    def doctor_list(self):
        actor = User.query.get(int(get_jwt_identity()))
        dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
        if not dp:
            return jsonify([]), 200
        rows = Appointment.query.filter_by(clinic_id=actor.clinic_id, doctor_profile_id=dp.id).order_by(Appointment.scheduled_at.desc()).all()
        return jsonify([{"id": a.id, "patient_id": a.patient_id, "scheduled_at": a.scheduled_at.isoformat(), "status": a.status.value} for a in rows]), 200

    @role_required("CLINIC_ADMIN", "RECEPTIONIST", "DOCTOR")
    def update_status(self, appointment_id):
        actor = User.query.get(int(get_jwt_identity()))
        ap = Appointment.query.get(appointment_id)
        if not ap or (actor.role != RoleEnum.SUPER_ADMIN and ap.clinic_id != actor.clinic_id):
            return jsonify({"error": "Not found"}), 404
        if actor.role == RoleEnum.DOCTOR:
            dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
            if not dp or ap.doctor_profile_id != dp.id:
                return jsonify({"error": "Forbidden"}), 403
        data = request.get_json(silent=True) or {}
        try:
            ap.status = AppointmentStatus(data.get("status"))
        except Exception:
            return jsonify({"error": "status inválido"}), 400
        db.session.commit()
        return jsonify({"id": ap.id, "status": ap.status.value}), 200

    @role_required("CLINIC_ADMIN", "RECEPTIONIST")
    def reschedule(self, appointment_id):
        actor = User.query.get(int(get_jwt_identity()))
        ap = Appointment.query.get(appointment_id)
        if not ap or ap.clinic_id != actor.clinic_id:
            return jsonify({"error": "Not found"}), 404
        dt = datetime.fromisoformat((request.get_json(silent=True) or {}).get("scheduled_at"))
        if self._has_conflict(actor.clinic_id, ap.doctor_profile_id, dt, exclude_id=ap.id):
            return jsonify({"error": "Conflito de agenda"}), 409
        if self._is_blocked(actor.clinic_id, ap.doctor_profile_id, dt):
            return jsonify({"error": "Horário bloqueado"}), 409
        ap.scheduled_at = dt
        ap.status = AppointmentStatus.RESCHEDULED
        db.session.commit()
        return jsonify({"id": ap.id, "status": ap.status.value}), 200

    @role_required("CLINIC_ADMIN")
    def cancel(self, appointment_id):
        actor = User.query.get(int(get_jwt_identity()))
        ap = Appointment.query.get(appointment_id)
        if not ap or ap.clinic_id != actor.clinic_id:
            return jsonify({"error": "Not found"}), 404
        ap.status = AppointmentStatus.CANCELLED
        db.session.commit()
        return jsonify({"id": ap.id, "status": ap.status.value}), 200
