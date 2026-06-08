from datetime import timedelta
from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity
from ..decorators.auth import role_required
from ..models_db.models import ScheduleBlock, User, RoleEnum, DoctorProfile, Appointment, AppointmentStatus, Clinic
from ..database.extensions import db
from ..utils.request_utils import get_json_body
from ..utils.date_validation import parse_iso_datetime


def _resolve_clinic_id(actor, data=None):
    if actor.clinic_id is not None:
        return actor.clinic_id
    if data:
        cid = data.get("clinic_id")
        if cid:
            return int(cid)
    clinic = Clinic.query.filter_by(is_active=True).first()
    return clinic.id if clinic else None


class ScheduleBlockController:
    def _has_block_overlap(self, clinic_id, doctor_profile_id, start, end):
        return ScheduleBlock.query.filter(
            ScheduleBlock.clinic_id == clinic_id,
            ScheduleBlock.doctor_profile_id == doctor_profile_id,
            ScheduleBlock.start_time < end,
            ScheduleBlock.end_time > start,
        ).first() is not None

    def _has_appointment_overlap(self, clinic_id, doctor_profile_id, start, end):
        slot_start = start - timedelta(minutes=30)
        return Appointment.query.filter(
            Appointment.clinic_id == clinic_id,
            Appointment.doctor_profile_id == doctor_profile_id,
            Appointment.scheduled_at >= slot_start,
            Appointment.scheduled_at < end,
            Appointment.status.in_([
                AppointmentStatus.SCHEDULED,
                AppointmentStatus.CONFIRMED,
                AppointmentStatus.IN_PROGRESS,
                AppointmentStatus.RESCHEDULED,
            ])
        ).first() is not None


    @role_required("DOCTOR", "CLINIC_ADMIN")
    def create(self):
        actor = User.query.get(int(get_jwt_identity()))
        data = get_json_body()
        if not data:
            return jsonify({"error": "Body JSON inválido ou vazio"}), 400
        doctor_profile_id = data.get("doctor_profile_id")
        if actor.role == RoleEnum.DOCTOR:
            dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
            doctor_profile_id = dp.id if dp else None
        if not doctor_profile_id:
            return jsonify({"error": "doctor_profile_id obrigatório"}), 400
        clinic_id = _resolve_clinic_id(actor, data)
        if not clinic_id:
            return jsonify({"error": "Nenhuma clínica disponível"}), 400
        start, error = parse_iso_datetime(data.get("start_time"), "start_time")
        if error:
            return jsonify({"error": error}), 400
        end, error = parse_iso_datetime(data.get("end_time"), "end_time")
        if error:
            return jsonify({"error": error}), 400
        if end <= start:
            return jsonify({"error": "Intervalo inválido"}), 400
        if self._has_block_overlap(clinic_id, doctor_profile_id, start, end):
            return jsonify({"error": "Conflito com bloqueio existente"}), 409
        if self._has_appointment_overlap(clinic_id, doctor_profile_id, start, end):
            return jsonify({"error": "Conflito com consulta existente"}), 409
        block = ScheduleBlock(clinic_id=clinic_id, doctor_profile_id=doctor_profile_id, start_time=start, end_time=end, reason=data.get("reason"))
        db.session.add(block)
        db.session.commit()
        return jsonify({"id": block.id}), 201

    @role_required("DOCTOR", "CLINIC_ADMIN")
    def list(self):
        actor = User.query.get(int(get_jwt_identity()))
        q = ScheduleBlock.query
        if actor.clinic_id is not None:
            q = q.filter_by(clinic_id=actor.clinic_id)
        if actor.role == RoleEnum.DOCTOR:
            dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
            if not dp:
                return jsonify([]), 200
            q = q.filter_by(doctor_profile_id=dp.id)
        rows = q.order_by(ScheduleBlock.start_time.desc()).all()
        return jsonify([{"id": b.id, "doctor_profile_id": b.doctor_profile_id, "start_time": b.start_time.isoformat(), "end_time": b.end_time.isoformat(), "reason": b.reason} for b in rows]), 200

    @role_required("DOCTOR", "CLINIC_ADMIN")
    def delete(self, block_id):
        actor = User.query.get(int(get_jwt_identity()))
        b = ScheduleBlock.query.get(block_id)
        if not b or (actor.clinic_id is not None and b.clinic_id != actor.clinic_id):
            return jsonify({"error": "Not found"}), 404
        if actor.role == RoleEnum.DOCTOR:
            dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
            if not dp or b.doctor_profile_id != dp.id:
                return jsonify({"error": "Forbidden"}), 403
        db.session.delete(b)
        db.session.commit()
        return jsonify({"message": "Bloqueio removido"}), 200
