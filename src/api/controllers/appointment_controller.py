from datetime import timedelta

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ..database.extensions import db
from ..decorators.auth import role_required
from ..models_db.models import Appointment, AppointmentStatus, AuditLog, DoctorProfile, Patient, RoleEnum, User
from ..services.scheduling import VALID_DURATIONS, doctor_belongs_to_clinic, naive, resolve_pending, validate_booking
from ..utils.date_validation import parse_iso_datetime
from ..utils.request_utils import get_json_body


def _serialize_appointment(appointment):
    profile = DoctorProfile.query.get(appointment.doctor_profile_id)
    doctor = User.query.get(profile.user_id) if profile else None
    patient = Patient.query.get(appointment.patient_id)
    return {
        "id": appointment.id, "patient_id": appointment.patient_id,
        "patient_name": patient.name if patient else None,
        "doctor_profile_id": appointment.doctor_profile_id,
        "doctor_id": doctor.id if doctor else None,
        "doctor_name": doctor.name if doctor else None,
        "scheduled_at": appointment.scheduled_at.isoformat(),
        "duration_minutes": appointment.duration_minutes or 30,
        "status": appointment.status.value, "notes": appointment.notes,
    }


def _clinic_id(actor, data=None):
    if actor.clinic_id is not None:
        return actor.clinic_id, None
    raw = (data or {}).get("clinic_id") or request.args.get("clinic_id")
    if not raw:
        return None, "clinic_id é obrigatório para SUPER_ADMIN"
    try:
        return int(raw), None
    except (TypeError, ValueError):
        return None, "clinic_id inválido"


def _audit(actor, appointment, action, metadata=None):
    db.session.add(AuditLog(
        clinic_id=appointment.clinic_id, user_id=actor.id, action=action,
        entity_type="Appointment", entity_id=str(appointment.id),
        metadata_json=metadata or {}, ip_address=request.remote_addr,
    ))


def _persistence_error(exc):
    db.session.rollback()
    if isinstance(exc, IntegrityError):
        return jsonify({"error": "Conflito de integridade da agenda"}), 409
    return jsonify({"error": "Não foi possível concluir a alteração da agenda"}), 500


class AppointmentController:
    def _can_transition(self, old_status, new_status):
        if new_status == AppointmentStatus.NO_SHOW:
            return True
        transitions = {
            AppointmentStatus.SCHEDULED: {AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED},
            AppointmentStatus.CONFIRMED: {AppointmentStatus.IN_PROGRESS, AppointmentStatus.CANCELLED},
            AppointmentStatus.IN_PROGRESS: {AppointmentStatus.COMPLETED},
            AppointmentStatus.RESCHEDULED: {AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED},
        }
        return new_status in transitions.get(old_status, set())

    @role_required("CLINIC_ADMIN", "RECEPTIONIST")
    def create(self):
        actor = User.query.get(int(get_jwt_identity()))
        data = get_json_body() or {}
        required = ("patient_id", "doctor_profile_id", "scheduled_at")
        if any(data.get(key) in (None, "") for key in required):
            return jsonify({"error": "patient_id, doctor_profile_id e scheduled_at são obrigatórios"}), 400
        clinic_id, error = _clinic_id(actor, data)
        if error:
            return jsonify({"error": error}), 400
        try:
            patient_id = int(data["patient_id"]); doctor_id = int(data["doctor_profile_id"])
        except (TypeError, ValueError):
            return jsonify({"error": "IDs devem ser numéricos"}), 400
        patient = Patient.query.filter_by(id=patient_id, clinic_id=clinic_id, is_active=True).first()
        if not patient:
            return jsonify({"error": "Paciente não encontrado"}), 404
        if not doctor_belongs_to_clinic(doctor_id, clinic_id):
            return jsonify({"error": "Médico não encontrado"}), 404
        scheduled_at, error = parse_iso_datetime(data["scheduled_at"], "scheduled_at")
        if error or scheduled_at is None:
            return jsonify({"error": error or "scheduled_at é obrigatório"}), 400
        scheduled_at = naive(scheduled_at)
        if data.get("duration_minutes") in (None, ""):
            return jsonify({"error": "duration_minutes é obrigatório"}), 400
        try:
            duration = int(data["duration_minutes"])
        except (TypeError, ValueError):
            return jsonify({"error": "duration_minutes deve ser numérico"}), 400
        if duration not in VALID_DURATIONS:
            return jsonify({"error": "duration_minutes deve ser 30 ou 60"}), 422
        ok, status, message = validate_booking(clinic_id, doctor_id, scheduled_at, duration)
        if not ok:
            return jsonify({"error": message}), status
        try:
            appointment = Appointment(
                clinic_id=clinic_id, patient_id=patient_id, doctor_profile_id=doctor_id,
                scheduled_at=scheduled_at, duration_minutes=duration, status=AppointmentStatus.SCHEDULED,
                notes=data.get("notes"), created_by=actor.id,
            )
            db.session.add(appointment); db.session.flush()
            ok, status, message = validate_booking(clinic_id, doctor_id, scheduled_at, duration, exclude_id=appointment.id)
            if not ok:
                db.session.rollback(); return jsonify({"error": message}), status
            _audit(actor, appointment, "CREATE", {"duration_minutes": duration})
            db.session.commit()
            return jsonify(_serialize_appointment(appointment)), 201
        except SQLAlchemyError as exc:
            return _persistence_error(exc)

    @role_required("CLINIC_ADMIN", "RECEPTIONIST", "DOCTOR")
    def list(self):
        actor = User.query.get(int(get_jwt_identity()))
        if actor.clinic_id is None and not request.args.get("clinic_id"):
            # Preserve the existing global SUPER_ADMIN read semantics. Mutations
            # and clinic-specific reads still require an explicit clinic_id.
            query = Appointment.query
        else:
            clinic_id, error = _clinic_id(actor)
            if error:
                return jsonify({"error": error}), 400
            query = Appointment.query.filter_by(clinic_id=clinic_id)
        if actor.role == RoleEnum.DOCTOR:
            profile = DoctorProfile.query.filter_by(user_id=actor.id).first()
            if not profile: return jsonify([]), 200
            query = query.filter_by(doctor_profile_id=profile.id)
        date_filter = request.args.get("date")
        doctor_id = request.args.get("doctor_id", type=int)
        status_filter = request.args.get("status")
        patient_id = request.args.get("patient_id", type=int)
        if date_filter:
            day, parse_error = parse_iso_datetime(date_filter, "date")
            if parse_error: return jsonify({"error": parse_error}), 400
            query = query.filter(Appointment.scheduled_at >= day, Appointment.scheduled_at < day + timedelta(days=1))
        if doctor_id and actor.role != RoleEnum.DOCTOR: query = query.filter_by(doctor_profile_id=doctor_id)
        if patient_id: query = query.filter_by(patient_id=patient_id)
        if status_filter:
            try: query = query.filter(Appointment.status == AppointmentStatus(status_filter))
            except ValueError: return jsonify({"error": "status inválido"}), 400
        return jsonify([_serialize_appointment(row) for row in query.order_by(Appointment.scheduled_at.desc()).all()]), 200

    @role_required("DOCTOR")
    def doctor_list(self):
        return self.list()

    @role_required("DOCTOR")
    def doctor_day(self):
        if not request.args.get("date"):
            return jsonify({"error": "date é obrigatório (YYYY-MM-DD)"}), 400
        return self.list()

    @role_required("CLINIC_ADMIN", "RECEPTIONIST", "DOCTOR")
    def update_status(self, appointment_id):
        actor = User.query.get(int(get_jwt_identity()))
        appointment = self._scoped_appointment(actor, appointment_id)
        if not appointment: return jsonify({"error": "Not found"}), 404
        if actor.role == RoleEnum.DOCTOR:
            profile = DoctorProfile.query.filter_by(user_id=actor.id).first()
            if not profile or appointment.doctor_profile_id != profile.id: return jsonify({"error": "Forbidden"}), 403
        data = get_json_body() or {}
        try: new_status = AppointmentStatus(data.get("status"))
        except (TypeError, ValueError): return jsonify({"error": "status inválido"}), 400
        if not self._can_transition(appointment.status, new_status):
            return jsonify({"error": f"Transição inválida: {appointment.status.value} -> {new_status.value}"}), 422
        try:
            appointment.status = new_status
            if new_status in (AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW):
                if resolve_pending(appointment.id, actor.id, "appointment_status"):
                    _audit(actor, appointment, "RESOLVE_PENDING", {"reason": "appointment_status"})
            _audit(actor, appointment, "STATUS_UPDATE", {"status": new_status.value})
            db.session.commit()
            return jsonify(_serialize_appointment(appointment)), 200
        except SQLAlchemyError as exc:
            return _persistence_error(exc)

    @role_required("CLINIC_ADMIN", "RECEPTIONIST")
    def reschedule(self, appointment_id):
        actor = User.query.get(int(get_jwt_identity()))
        appointment = self._scoped_appointment(actor, appointment_id)
        if not appointment: return jsonify({"error": "Not found"}), 404
        data = get_json_body() or {}
        scheduled_at, error = parse_iso_datetime(data.get("scheduled_at"), "scheduled_at")
        if error or scheduled_at is None: return jsonify({"error": error or "scheduled_at é obrigatório"}), 400
        try: duration = int(data.get("duration_minutes", appointment.duration_minutes or 30))
        except (TypeError, ValueError): return jsonify({"error": "duration_minutes deve ser 30 ou 60"}), 422
        scheduled_at = naive(scheduled_at)
        ok, status, message = validate_booking(appointment.clinic_id, appointment.doctor_profile_id, scheduled_at, duration, exclude_id=appointment.id)
        if not ok: return jsonify({"error": message}), status
        try:
            appointment.scheduled_at = scheduled_at; appointment.duration_minutes = duration; appointment.status = AppointmentStatus.RESCHEDULED
            resolve_pending(appointment.id, actor.id, "rescheduled")
            _audit(actor, appointment, "RESCHEDULE", {"scheduled_at": scheduled_at.isoformat(), "duration_minutes": duration})
            db.session.flush()
            ok, status, message = validate_booking(appointment.clinic_id, appointment.doctor_profile_id, scheduled_at, duration, exclude_id=appointment.id)
            if not ok: db.session.rollback(); return jsonify({"error": message}), status
            db.session.commit()
            return jsonify(_serialize_appointment(appointment)), 200
        except SQLAlchemyError as exc:
            return _persistence_error(exc)

    @role_required("CLINIC_ADMIN")
    def cancel(self, appointment_id):
        actor = User.query.get(int(get_jwt_identity()))
        appointment = self._scoped_appointment(actor, appointment_id)
        if not appointment: return jsonify({"error": "Not found"}), 404
        try:
            appointment.status = AppointmentStatus.CANCELLED
            resolve_pending(appointment.id, actor.id, "cancelled")
            _audit(actor, appointment, "CANCEL")
            db.session.commit()
            return jsonify(_serialize_appointment(appointment)), 200
        except SQLAlchemyError as exc:
            return _persistence_error(exc)

    def _scoped_appointment(self, actor, appointment_id):
        query = Appointment.query.filter_by(id=appointment_id)
        clinic_id, error = _clinic_id(actor)
        if error: return None
        return query.filter_by(clinic_id=clinic_id).first()
