from datetime import timedelta
from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity
from ..decorators.auth import role_required
from ..models_db.models import Appointment, AppointmentStatus, User, RoleEnum, DoctorProfile, ScheduleBlock, Clinic, Patient
from ..database.extensions import db
from ..utils.request_utils import get_json_body
from ..utils.date_validation import parse_iso_datetime


def _serialize_appointment(a: Appointment) -> dict:
    dp = DoctorProfile.query.get(a.doctor_profile_id) if a.doctor_profile_id else None
    doctor_user = User.query.get(dp.user_id) if dp else None
    patient = Patient.query.get(a.patient_id) if a.patient_id else None
    return {
        "id": a.id,
        "patient_id": a.patient_id,
        "patient_name": patient.name if patient else None,
        "doctor_profile_id": a.doctor_profile_id,
        "doctor_id": doctor_user.id if doctor_user else None,
        "doctor_name": doctor_user.name if doctor_user else None,
        "scheduled_at": a.scheduled_at.isoformat(),
        "status": a.status.value,
        "notes": a.notes,
    }


def _resolve_clinic_id(actor, data=None):
    if actor.clinic_id is not None:
        return actor.clinic_id
    if data:
        cid = data.get("clinic_id")
        if cid:
            return int(cid)
    clinic = Clinic.query.filter_by(is_active=True).first()
    return clinic.id if clinic else None


class AppointmentController:
    SLOT_MINUTES = 30

    def _interval(self, scheduled_at):
        return scheduled_at, scheduled_at + timedelta(minutes=self.SLOT_MINUTES)

    def _has_conflict(self, clinic_id, doctor_profile_id, scheduled_at, exclude_id=None):
        start, end = self._interval(scheduled_at)
        # Filtra no SQL pelo intervalo de data para evitar carregar tudo em memória
        slot_start = start - timedelta(minutes=self.SLOT_MINUTES)
        query = Appointment.query.filter(
            Appointment.clinic_id == clinic_id,
            Appointment.doctor_profile_id == doctor_profile_id,
            Appointment.scheduled_at >= slot_start,
            Appointment.scheduled_at < end,
            Appointment.status.in_([
                AppointmentStatus.SCHEDULED,
                AppointmentStatus.CONFIRMED,
                AppointmentStatus.IN_PROGRESS,
                AppointmentStatus.RESCHEDULED,
            ]),
        )
        if exclude_id:
            query = query.filter(Appointment.id != exclude_id)
        return query.first() is not None

    def _is_blocked(self, clinic_id, doctor_profile_id, scheduled_at):
        start, end = self._interval(scheduled_at)
        return ScheduleBlock.query.filter(
            ScheduleBlock.clinic_id == clinic_id,
            ScheduleBlock.doctor_profile_id == doctor_profile_id,
            ScheduleBlock.start_time < end,
            ScheduleBlock.end_time > start,
        ).first() is not None

    def _can_transition(self, old_status, new_status):
        if new_status == AppointmentStatus.NO_SHOW:
            return True
        transitions = {
            AppointmentStatus.SCHEDULED: {AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED},
            AppointmentStatus.CONFIRMED: {AppointmentStatus.IN_PROGRESS, AppointmentStatus.CANCELLED},
            AppointmentStatus.IN_PROGRESS: {AppointmentStatus.COMPLETED},
        }
        return new_status in transitions.get(old_status, set())

    @role_required("CLINIC_ADMIN", "RECEPTIONIST")
    def create(self):
        actor = User.query.get(int(get_jwt_identity()))
        data = get_json_body()
        if not data:
            return jsonify({"error": "Body JSON inválido ou vazio"}), 400
        required = ["patient_id", "doctor_profile_id", "scheduled_at"]
        if any(not data.get(k) for k in required):
            return jsonify({"error": "Campos obrigatórios ausentes"}), 400
        clinic_id = _resolve_clinic_id(actor, data)
        if not clinic_id:
            return jsonify({"error": "Nenhuma clínica disponível"}), 400
        dt, error = parse_iso_datetime(data["scheduled_at"], "scheduled_at")
        if error:
            return jsonify({"error": error}), 400
        if self._has_conflict(clinic_id, data["doctor_profile_id"], dt):
            return jsonify({"error": "Conflito de agenda"}), 409
        if self._is_blocked(clinic_id, data["doctor_profile_id"], dt):
            return jsonify({"error": "Horário bloqueado"}), 409
        ap = Appointment(clinic_id=clinic_id, patient_id=data["patient_id"], doctor_profile_id=data["doctor_profile_id"], scheduled_at=dt, status=AppointmentStatus.SCHEDULED, notes=data.get("notes"), created_by=actor.id)
        db.session.add(ap)
        db.session.commit()
        return jsonify({"id": ap.id, "status": ap.status.value}), 201

    @role_required("CLINIC_ADMIN", "RECEPTIONIST", "DOCTOR")
    def list(self):
        actor = User.query.get(int(get_jwt_identity()))
        q = Appointment.query
        if actor.clinic_id is not None:
            q = q.filter_by(clinic_id=actor.clinic_id)
        if actor.role == RoleEnum.DOCTOR:
            dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
            if not dp:
                return jsonify([]), 200
            q = q.filter(Appointment.doctor_profile_id == dp.id)
        date_filter = request.args.get("date")
        doctor_id = request.args.get("doctor_id", type=int)
        status = request.args.get("status")
        if date_filter:
            day, error = parse_iso_datetime(date_filter, "date")
            if error:
                return jsonify({"error": error}), 400
            q = q.filter(Appointment.scheduled_at >= day, Appointment.scheduled_at < day + timedelta(days=1))
        if doctor_id and actor.role != RoleEnum.DOCTOR:
            q = q.filter(Appointment.doctor_profile_id == doctor_id)
        if status:
            try:
                q = q.filter(Appointment.status == AppointmentStatus(status))
            except Exception:
                return jsonify({"error": "status inválido"}), 400
        rows = q.order_by(Appointment.scheduled_at.desc()).all()
        return jsonify([_serialize_appointment(a) for a in rows]), 200

    @role_required("DOCTOR")
    def doctor_list(self):
        actor = User.query.get(int(get_jwt_identity()))
        dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
        if not dp:
            return jsonify([]), 200
        q = Appointment.query.filter_by(doctor_profile_id=dp.id)
        if actor.clinic_id is not None:
            q = q.filter_by(clinic_id=actor.clinic_id)
        rows = q.order_by(Appointment.scheduled_at.desc()).all()
        return jsonify([_serialize_appointment(a) for a in rows]), 200

    @role_required("DOCTOR")
    def doctor_day(self):
        actor = User.query.get(int(get_jwt_identity()))
        dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
        if not dp:
            return jsonify([]), 200
        date_str = request.args.get("date")
        if not date_str:
            return jsonify({"error": "date é obrigatório (YYYY-MM-DD)"}), 400
        day, error = parse_iso_datetime(date_str, "date")
        if error:
            return jsonify({"error": error}), 400
        q = Appointment.query.filter(
            Appointment.doctor_profile_id == dp.id,
            Appointment.scheduled_at >= day,
            Appointment.scheduled_at < day + timedelta(days=1),
        )
        if actor.clinic_id is not None:
            q = q.filter(Appointment.clinic_id == actor.clinic_id)
        rows = q.order_by(Appointment.scheduled_at.asc()).all()
        return jsonify([_serialize_appointment(a) for a in rows]), 200

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
        data = get_json_body()
        if not data:
            return jsonify({"error": "Body JSON inválido ou vazio"}), 400
        try:
            new_status = AppointmentStatus(data.get("status"))
        except Exception:
            return jsonify({"error": "status inválido"}), 400
        if not self._can_transition(ap.status, new_status):
            return jsonify({"error": f"Transição inválida: {ap.status.value} -> {new_status.value}"}), 422
        ap.status = new_status
        db.session.commit()
        return jsonify({"id": ap.id, "status": ap.status.value}), 200

    @role_required("CLINIC_ADMIN", "RECEPTIONIST")
    def reschedule(self, appointment_id):
        actor = User.query.get(int(get_jwt_identity()))
        ap = Appointment.query.get(appointment_id)
        if not ap or (actor.clinic_id is not None and ap.clinic_id != actor.clinic_id):
            return jsonify({"error": "Not found"}), 404
        data = get_json_body()
        if not data:
            return jsonify({"error": "Body JSON inválido ou vazio"}), 400
        dt, error = parse_iso_datetime(data.get("scheduled_at"), "scheduled_at")
        if error:
            return jsonify({"error": error}), 400
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
        if not ap or (actor.clinic_id is not None and ap.clinic_id != actor.clinic_id):
            return jsonify({"error": "Not found"}), 404
        ap.status = AppointmentStatus.CANCELLED
        db.session.commit()
        return jsonify({"id": ap.id, "status": ap.status.value}), 200
