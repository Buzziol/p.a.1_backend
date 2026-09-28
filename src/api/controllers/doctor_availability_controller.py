from datetime import date, time

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ..database.extensions import db
from ..decorators.auth import role_required
from ..models_db.models import AuditLog, DoctorAvailability, DoctorProfile, RoleEnum, User
from ..services.scheduling import (
    MAX_SLOT_RANGE_DAYS,
    VALID_DURATIONS,
    doctor_belongs_to_clinic,
    ensure_pending,
    future_invalid_appointments,
    generate_slots,
)
from ..utils.request_utils import get_json_body


def _parse_time(value, name):
    try:
        parsed = time.fromisoformat(str(value))
        if parsed.second or parsed.microsecond:
            return None, f"{name} deve usar HH:MM"
        return parsed, None
    except (TypeError, ValueError):
        return None, f"{name} deve usar HH:MM"


def _serialize(row):
    return {
        "id": row.id,
        "clinic_id": row.clinic_id,
        "doctor_profile_id": row.doctor_profile_id,
        "weekday": row.weekday,
        "start_time": row.start_time.strftime("%H:%M"),
        "end_time": row.end_time.strftime("%H:%M"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
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


def _target_doctor(actor, data, clinic_id):
    if actor.role == RoleEnum.DOCTOR:
        profile = DoctorProfile.query.filter_by(user_id=actor.id).first()
        if not profile:
            return None, "Perfil médico não encontrado"
        supplied = data.get("doctor_profile_id")
        if supplied is not None:
            try:
                if int(supplied) != profile.id:
                    return None, "Médico não pode administrar disponibilidade de outro médico"
            except (TypeError, ValueError):
                return None, "Médico não pode administrar disponibilidade de outro médico"
        return profile.id, None
    try:
        doctor_id = int(data.get("doctor_profile_id"))
    except (TypeError, ValueError):
        return None, "doctor_profile_id é obrigatório"
    if not doctor_belongs_to_clinic(doctor_id, clinic_id):
        return None, "Médico não encontrado"
    return doctor_id, None


def _audit(actor, clinic_id, action, row, metadata=None):
    entity_id = row if isinstance(row, int) else row.id
    db.session.add(AuditLog(
        clinic_id=clinic_id,
        user_id=actor.id,
        action=action,
        entity_type="DoctorAvailability",
        entity_id=str(entity_id),
        metadata_json=metadata or {},
        ip_address=request.remote_addr,
    ))


def _persistence_error(exc):
    db.session.rollback()
    if isinstance(exc, IntegrityError):
        return jsonify({"error": "Conflito de integridade da agenda"}), 409
    return jsonify({"error": "Não foi possível concluir a alteração da agenda"}), 500


class DoctorAvailabilityController:
    @role_required("DOCTOR", "CLINIC_ADMIN")
    def list(self):
        actor = User.query.get(int(get_jwt_identity()))
        clinic_id, error = _clinic_id(actor)
        if error:
            return jsonify({"error": error}), 400
        if actor.role == RoleEnum.DOCTOR:
            profile = DoctorProfile.query.filter_by(user_id=actor.id).first()
            if not profile:
                return jsonify([]), 200
            doctor_id = profile.id
        else:
            doctor_id = request.args.get("doctor_profile_id", type=int)
        query = DoctorAvailability.query.filter_by(clinic_id=clinic_id)
        if doctor_id:
            if not doctor_belongs_to_clinic(doctor_id, clinic_id):
                return jsonify({"error": "Médico não encontrado"}), 404
            query = query.filter_by(doctor_profile_id=doctor_id)
        return jsonify([_serialize(r) for r in query.order_by(
            DoctorAvailability.doctor_profile_id,
            DoctorAvailability.weekday,
            DoctorAvailability.start_time,
        ).all()]), 200

    @role_required("DOCTOR", "CLINIC_ADMIN")
    def create(self):
        actor = User.query.get(int(get_jwt_identity()))
        data = get_json_body() or {}
        clinic_id, error = _clinic_id(actor, data)
        if error:
            return jsonify({"error": error}), 400
        doctor_id, error = _target_doctor(actor, data, clinic_id)
        if error:
            return jsonify({"error": error}), 403 if actor.role == RoleEnum.DOCTOR else 404
        try:
            weekday = int(data.get("weekday"))
        except (TypeError, ValueError):
            return jsonify({"error": "weekday deve ser um número ISO de 1 a 7"}), 422
        start, error = _parse_time(data.get("start_time"), "start_time")
        if error:
            return jsonify({"error": error}), 422
        end, error = _parse_time(data.get("end_time"), "end_time")
        if error:
            return jsonify({"error": error}), 422
        if weekday not in range(1, 8) or end <= start:
            return jsonify({"error": "Faixa semanal inválida; não atravesse a meia-noite"}), 422
        if self._overlap(clinic_id, doctor_id, weekday, start, end):
            return jsonify({"error": "Faixa sobrepõe uma disponibilidade existente"}), 409
        try:
            row = DoctorAvailability(
                clinic_id=clinic_id, doctor_profile_id=doctor_id, weekday=weekday,
                start_time=start, end_time=end, created_by=actor.id, updated_by=actor.id,
            )
            db.session.add(row)
            db.session.flush()
            _audit(actor, clinic_id, "CREATE", row, _serialize(row))
            db.session.commit()
            return jsonify({**_serialize(row), "affected_appointments": 0}), 201
        except SQLAlchemyError as exc:
            return _persistence_error(exc)

    @role_required("DOCTOR", "CLINIC_ADMIN")
    def update(self, availability_id):
        actor = User.query.get(int(get_jwt_identity()))
        data = get_json_body() or {}
        row, response = self._owned_row(actor, availability_id, data)
        if response:
            return response
        try:
            weekday = int(data.get("weekday", row.weekday))
        except (TypeError, ValueError):
            return jsonify({"error": "weekday deve ser um número ISO de 1 a 7"}), 422
        start, error = _parse_time(data.get("start_time", row.start_time.strftime("%H:%M")), "start_time")
        if error:
            return jsonify({"error": error}), 422
        end, error = _parse_time(data.get("end_time", row.end_time.strftime("%H:%M")), "end_time")
        if error:
            return jsonify({"error": error}), 422
        if weekday not in range(1, 8) or end <= start:
            return jsonify({"error": "Faixa semanal inválida; não atravesse a meia-noite"}), 422
        if self._overlap(row.clinic_id, row.doctor_profile_id, weekday, start, end, row.id):
            return jsonify({"error": "Faixa sobrepõe uma disponibilidade existente"}), 409
        try:
            row.weekday, row.start_time, row.end_time, row.updated_by = weekday, start, end, actor.id
            db.session.flush()
            affected = self._create_pendings(row, actor, "AVAILABILITY_UPDATED", "Disponibilidade alterada")
            _audit(actor, row.clinic_id, "UPDATE", row, {"affected_appointments": affected})
            db.session.commit()
            return jsonify({**_serialize(row), "affected_appointments": affected}), 200
        except SQLAlchemyError as exc:
            return _persistence_error(exc)

    @role_required("DOCTOR", "CLINIC_ADMIN")
    def delete(self, availability_id):
        actor = User.query.get(int(get_jwt_identity()))
        row, response = self._owned_row(actor, availability_id, {})
        if response:
            return response
        clinic_id, doctor_id, entity_id = row.clinic_id, row.doctor_profile_id, row.id
        try:
            db.session.delete(row)
            db.session.flush()
            affected = 0
            for appointment in future_invalid_appointments(clinic_id, doctor_id):
                ensure_pending(
                    appointment, "AVAILABILITY_REMOVED", "Disponibilidade removida", actor.id,
                    "DOCTOR_AVAILABILITY", entity_id,
                )
                affected += 1
            _audit(actor, clinic_id, "DELETE", entity_id, {"affected_appointments": affected})
            db.session.commit()
            return jsonify({"message": "Disponibilidade removida", "affected_appointments": affected}), 200
        except SQLAlchemyError as exc:
            return _persistence_error(exc)

    @role_required("DOCTOR", "CLINIC_ADMIN", "RECEPTIONIST")
    def slots(self):
        actor = User.query.get(int(get_jwt_identity()))
        clinic_id, error = _clinic_id(actor)
        if error:
            return jsonify({"error": error}), 400
        try:
            doctor_id = int(request.args.get("doctor_profile_id"))
            duration = int(request.args.get("duration_minutes"))
            date_from = date.fromisoformat(request.args.get("date_from", ""))
            date_to = date.fromisoformat(request.args.get("date_to", ""))
        except (TypeError, ValueError):
            return jsonify({"error": "doctor_profile_id, date_from, date_to e duration_minutes são obrigatórios"}), 400
        if duration not in VALID_DURATIONS:
            return jsonify({"error": "duration_minutes deve ser 30 ou 60"}), 422
        if date_to < date_from or (date_to - date_from).days >= MAX_SLOT_RANGE_DAYS:
            return jsonify({"error": f"intervalo deve ter no máximo {MAX_SLOT_RANGE_DAYS} dias"}), 422
        if actor.role == RoleEnum.DOCTOR:
            own = DoctorProfile.query.filter_by(user_id=actor.id).first()
            if not own or own.id != doctor_id:
                return jsonify({"error": "Forbidden"}), 403
        if not doctor_belongs_to_clinic(doctor_id, clinic_id):
            return jsonify({"error": "Médico não encontrado"}), 404
        has_ranges = DoctorAvailability.query.filter_by(
            clinic_id=clinic_id, doctor_profile_id=doctor_id
        ).first() is not None
        return jsonify({
            "items": generate_slots(clinic_id, doctor_id, date_from, date_to, duration),
            "has_availability": has_ranges,
            "slot_step_minutes": 30,
        }), 200

    def _overlap(self, clinic_id, doctor_id, weekday, start, end, exclude_id=None):
        query = DoctorAvailability.query.filter(
            DoctorAvailability.clinic_id == clinic_id,
            DoctorAvailability.doctor_profile_id == doctor_id,
            DoctorAvailability.weekday == weekday,
            DoctorAvailability.start_time < end,
            DoctorAvailability.end_time > start,
        )
        if exclude_id:
            query = query.filter(DoctorAvailability.id != exclude_id)
        return query.first() is not None

    def _owned_row(self, actor, availability_id, data):
        clinic_id, error = _clinic_id(actor, data)
        if error:
            return None, (jsonify({"error": error}), 400)
        row = DoctorAvailability.query.filter_by(id=availability_id, clinic_id=clinic_id).first()
        if not row:
            return None, (jsonify({"error": "Disponibilidade não encontrada"}), 404)
        if actor.role == RoleEnum.DOCTOR:
            own = DoctorProfile.query.filter_by(user_id=actor.id).first()
            if not own or row.doctor_profile_id != own.id:
                return None, (jsonify({"error": "Forbidden"}), 403)
        return row, None

    def _create_pendings(self, row, actor, source, reason):
        appointments = future_invalid_appointments(row.clinic_id, row.doctor_profile_id)
        for appointment in appointments:
            ensure_pending(
                appointment, source, reason, actor.id,
                "DOCTOR_AVAILABILITY", row.id,
            )
        return len(appointments)
