from datetime import date, datetime, time, timedelta

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ..database.extensions import db
from ..decorators.auth import role_required
from ..models_db.models import AuditLog, DoctorProfile, RoleEnum, ScheduleBlock, User
from ..services.scheduling import (
    appointments_overlapping, doctor_belongs_to_clinic, ensure_pending, naive,
    reconcile_block_pendings,
)
from ..utils.date_validation import parse_iso_datetime
from ..utils.request_utils import get_json_body


def _clinic_id(actor, data=None):
    if actor.clinic_id is not None: return actor.clinic_id, None
    raw = (data or {}).get("clinic_id") or request.args.get("clinic_id")
    if not raw: return None, "clinic_id é obrigatório para SUPER_ADMIN"
    try: return int(raw), None
    except (TypeError, ValueError): return None, "clinic_id inválido"


def _interval(data):
    all_day = bool(data.get("all_day", False))
    if all_day and (data.get("start_date") or data.get("end_date")):
        try:
            first = date.fromisoformat(data.get("start_date"))
            last = date.fromisoformat(data.get("end_date") or data.get("start_date"))
        except (TypeError, ValueError):
            return None, None, None, "start_date e end_date devem usar YYYY-MM-DD"
        # Public end_date is inclusive; storage is [start, next day after end_date).
        return datetime.combine(first, time.min), datetime.combine(last + timedelta(days=1), time.min), True, None
    start, error = parse_iso_datetime(data.get("start_time"), "start_time")
    if error or start is None: return None, None, None, error or "start_time é obrigatório"
    end, error = parse_iso_datetime(data.get("end_time"), "end_time")
    if error or end is None: return None, None, None, error or "end_time é obrigatório"
    return naive(start), naive(end), all_day, None


def _serialize(block):
    data = {
        "id": block.id, "clinic_id": block.clinic_id,
        "doctor_profile_id": block.doctor_profile_id,
        "start_time": block.start_time.isoformat(), "end_time": block.end_time.isoformat(),
        "all_day": bool(block.all_day), "reason": block.reason,
    }
    if block.all_day:
        data["start_date"] = block.start_time.date().isoformat()
        data["end_date"] = (block.end_time.date() - timedelta(days=1)).isoformat()
    return data


def _audit(actor, block, action, metadata=None):
    db.session.add(AuditLog(
        clinic_id=block.clinic_id, user_id=actor.id, action=action,
        entity_type="ScheduleBlock", entity_id=str(block.id), metadata_json=metadata or {},
        ip_address=request.remote_addr,
    ))


def _persistence_error(exc):
    db.session.rollback()
    if isinstance(exc, IntegrityError):
        return jsonify({"error": "Conflito de integridade da agenda"}), 409
    return jsonify({"error": "Não foi possível concluir a alteração da agenda"}), 500


class ScheduleBlockController:
    def _overlap(self, clinic_id, doctor_id, start, end, exclude_id=None):
        query = ScheduleBlock.query.filter(
            ScheduleBlock.clinic_id == clinic_id, ScheduleBlock.doctor_profile_id == doctor_id,
            ScheduleBlock.start_time < end, ScheduleBlock.end_time > start,
        )
        if exclude_id: query = query.filter(ScheduleBlock.id != exclude_id)
        return query.first() is not None

    def _doctor_id(self, actor, data, clinic_id):
        if actor.role == RoleEnum.DOCTOR:
            profile = DoctorProfile.query.filter_by(user_id=actor.id).first()
            supplied = data.get("doctor_profile_id")
            if not profile: return None, "Perfil médico não encontrado", 404
            if supplied is not None:
                try:
                    if int(supplied) != profile.id: return None, "Forbidden", 403
                except (TypeError, ValueError):
                    return None, "Forbidden", 403
            return profile.id, None, None
        try: doctor_id = int(data.get("doctor_profile_id"))
        except (TypeError, ValueError): return None, "doctor_profile_id obrigatório", 400
        if not doctor_belongs_to_clinic(doctor_id, clinic_id): return None, "Médico não encontrado", 404
        return doctor_id, None, None

    @role_required("DOCTOR", "CLINIC_ADMIN")
    def create(self):
        actor = User.query.get(int(get_jwt_identity())); data = get_json_body() or {}
        clinic_id, error = _clinic_id(actor, data)
        if error: return jsonify({"error": error}), 400
        doctor_id, error, status = self._doctor_id(actor, data, clinic_id)
        if error: return jsonify({"error": error}), status
        start, end, all_day, error = _interval(data)
        if error: return jsonify({"error": error}), 400
        if end <= start: return jsonify({"error": "Intervalo inválido"}), 422
        if self._overlap(clinic_id, doctor_id, start, end):
            return jsonify({"error": "Conflito com bloqueio existente"}), 409
        try:
            block = ScheduleBlock(
                clinic_id=clinic_id, doctor_profile_id=doctor_id, start_time=start, end_time=end,
                all_day=all_day, reason=data.get("reason"), created_by=actor.id, updated_by=actor.id,
            )
            db.session.add(block); db.session.flush()
            appointments = appointments_overlapping(clinic_id, doctor_id, start, end)
            for appointment in appointments:
                ensure_pending(
                    appointment, "BLOCK_CREATED", "Bloqueio criado", actor.id,
                    "SCHEDULE_BLOCK", block.id,
                )
            _audit(actor, block, "CREATE", {"affected_appointments": len(appointments), "all_day": all_day})
            db.session.commit()
            return jsonify({**_serialize(block), "affected_appointments": len(appointments)}), 201
        except SQLAlchemyError as exc:
            return _persistence_error(exc)

    @role_required("DOCTOR", "CLINIC_ADMIN")
    def list(self):
        actor = User.query.get(int(get_jwt_identity())); clinic_id, error = _clinic_id(actor)
        if error: return jsonify({"error": error}), 400
        query = ScheduleBlock.query.filter_by(clinic_id=clinic_id)
        if actor.role == RoleEnum.DOCTOR:
            profile = DoctorProfile.query.filter_by(user_id=actor.id).first()
            if not profile: return jsonify([]), 200
            query = query.filter_by(doctor_profile_id=profile.id)
        elif request.args.get("doctor_profile_id", type=int):
            doctor_id = request.args.get("doctor_profile_id", type=int)
            if not doctor_belongs_to_clinic(doctor_id, clinic_id): return jsonify({"error": "Médico não encontrado"}), 404
            query = query.filter_by(doctor_profile_id=doctor_id)
        return jsonify([_serialize(row) for row in query.order_by(ScheduleBlock.start_time.desc()).all()]), 200

    @role_required("DOCTOR", "CLINIC_ADMIN")
    def update(self, block_id):
        actor = User.query.get(int(get_jwt_identity())); data = get_json_body() or {}
        block, response = self._owned(actor, block_id, data)
        if response: return response
        merged = {
            "start_time": data.get("start_time", block.start_time.isoformat()),
            "end_time": data.get("end_time", block.end_time.isoformat()),
            "all_day": data.get("all_day", block.all_day),
            "start_date": data.get("start_date"), "end_date": data.get("end_date"),
        }
        start, end, all_day, error = _interval(merged)
        if error: return jsonify({"error": error}), 400
        if end <= start: return jsonify({"error": "Intervalo inválido"}), 422
        if self._overlap(block.clinic_id, block.doctor_profile_id, start, end, block.id):
            return jsonify({"error": "Conflito com bloqueio existente"}), 409
        try:
            block.start_time, block.end_time, block.all_day = start, end, all_day
            block.reason = data.get("reason", block.reason); block.updated_by = actor.id
            db.session.flush()
            appointments = appointments_overlapping(block.clinic_id, block.doctor_profile_id, start, end)
            for appointment in appointments:
                ensure_pending(
                    appointment, "BLOCK_UPDATED", "Bloqueio alterado", actor.id,
                    "SCHEDULE_BLOCK", block.id,
                )
            reconciled = reconcile_block_pendings(block.id, actor.id)
            _audit(actor, block, "UPDATE", {
                "affected_appointments": len(appointments),
                "reconciled_pendings": reconciled,
            })
            db.session.commit()
            return jsonify({**_serialize(block), "affected_appointments": len(appointments)}), 200
        except SQLAlchemyError as exc:
            return _persistence_error(exc)

    @role_required("DOCTOR", "CLINIC_ADMIN")
    def delete(self, block_id):
        actor = User.query.get(int(get_jwt_identity())); block, response = self._owned(actor, block_id, {})
        if response: return response
        try:
            block_id = block.id
            db.session.delete(block); db.session.flush()
            reconcile_block_pendings(block_id, actor.id)
            _audit(actor, block, "DELETE")
            db.session.commit()
            return jsonify({"message": "Bloqueio removido"}), 200
        except SQLAlchemyError as exc:
            return _persistence_error(exc)

    def _owned(self, actor, block_id, data):
        clinic_id, error = _clinic_id(actor, data)
        if error: return None, (jsonify({"error": error}), 400)
        block = ScheduleBlock.query.filter_by(id=block_id, clinic_id=clinic_id).first()
        if not block: return None, (jsonify({"error": "Not found"}), 404)
        if actor.role == RoleEnum.DOCTOR:
            profile = DoctorProfile.query.filter_by(user_id=actor.id).first()
            if not profile or block.doctor_profile_id != profile.id:
                return None, (jsonify({"error": "Forbidden"}), 403)
        return block, None
