from datetime import timedelta

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity

from ..decorators.auth import role_required
from ..models_db.models import (
    Appointment, DoctorProfile, Patient, ReschedulePending,
    ReschedulePendingStatus, User,
)
from ..services.scheduling import generate_slots, utcnow_naive


SUGGESTION_SEARCH_DAYS = 60
SUGGESTION_LIMIT = 10


def _clinic_id(actor):
    if actor.clinic_id is not None: return actor.clinic_id, None
    raw = request.args.get("clinic_id")
    if not raw: return None, "clinic_id é obrigatório para SUPER_ADMIN"
    try: return int(raw), None
    except ValueError: return None, "clinic_id inválido"


def _serialize(row):
    appointment = Appointment.query.get(row.appointment_id)
    patient = Patient.query.get(appointment.patient_id) if appointment else None
    profile = DoctorProfile.query.get(appointment.doctor_profile_id) if appointment else None
    doctor = User.query.get(profile.user_id) if profile else None
    return {
        "id": row.id, "appointment_id": row.appointment_id, "status": row.status.value,
        "source": row.source, "reason": row.reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "patient": {"id": patient.id, "name": patient.name} if patient else None,
        "doctor": {"profile_id": profile.id, "name": doctor.name} if profile and doctor else None,
        "scheduled_at": appointment.scheduled_at.isoformat() if appointment else None,
        "duration_minutes": (appointment.duration_minutes or 30) if appointment else None,
        "appointment_status": appointment.status.value if appointment else None,
    }


class ReschedulePendingController:
    @role_required("CLINIC_ADMIN", "RECEPTIONIST")
    def list(self):
        actor = User.query.get(int(get_jwt_identity())); clinic_id, error = _clinic_id(actor)
        if error: return jsonify({"error": error}), 400
        query = ReschedulePending.query.filter_by(clinic_id=clinic_id)
        status = request.args.get("status", ReschedulePendingStatus.PENDING.value)
        try: query = query.filter_by(status=ReschedulePendingStatus(status))
        except ValueError: return jsonify({"error": "status inválido"}), 400
        doctor_id = request.args.get("doctor_profile_id", type=int)
        if doctor_id:
            query = query.join(Appointment, Appointment.id == ReschedulePending.appointment_id).filter(
                Appointment.doctor_profile_id == doctor_id
            )
        return jsonify([_serialize(row) for row in query.order_by(ReschedulePending.created_at.asc()).all()]), 200

    @role_required("CLINIC_ADMIN", "RECEPTIONIST")
    def count(self):
        actor = User.query.get(int(get_jwt_identity())); clinic_id, error = _clinic_id(actor)
        if error: return jsonify({"error": error}), 400
        count = ReschedulePending.query.filter_by(
            clinic_id=clinic_id, status=ReschedulePendingStatus.PENDING
        ).count()
        return jsonify({"count": count}), 200

    @role_required("CLINIC_ADMIN", "RECEPTIONIST")
    def suggestions(self, pending_id):
        actor = User.query.get(int(get_jwt_identity())); clinic_id, error = _clinic_id(actor)
        if error: return jsonify({"error": error}), 400
        pending = ReschedulePending.query.filter_by(
            id=pending_id, clinic_id=clinic_id, status=ReschedulePendingStatus.PENDING
        ).first()
        if not pending: return jsonify({"error": "Pendência não encontrada"}), 404
        appointment = Appointment.query.filter_by(id=pending.appointment_id, clinic_id=clinic_id).first()
        if not appointment: return jsonify({"error": "Consulta não encontrada"}), 404
        today = utcnow_naive().date()
        slots = generate_slots(
            clinic_id, appointment.doctor_profile_id, today,
            today + timedelta(days=SUGGESTION_SEARCH_DAYS),
            appointment.duration_minutes or 30, exclude_appointment_id=appointment.id,
            limit=SUGGESTION_LIMIT + 1,
        )
        slots = [slot for slot in slots if slot["start"] != appointment.scheduled_at.isoformat()][:SUGGESTION_LIMIT]
        return jsonify({
            "items": slots, "search_days": SUGGESTION_SEARCH_DAYS,
            "limit": SUGGESTION_LIMIT,
        }), 200
