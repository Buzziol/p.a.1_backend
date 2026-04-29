from datetime import datetime
from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity
from ..decorators.auth import role_required
from ..models_db.models import ScheduleBlock, User, RoleEnum, DoctorProfile
from ..database.extensions import db


class ScheduleBlockController:
    @role_required("DOCTOR", "CLINIC_ADMIN")
    def create(self):
        actor = User.query.get(int(get_jwt_identity()))
        data = request.get_json(silent=True) or {}
        doctor_profile_id = data.get("doctor_profile_id")
        if actor.role == RoleEnum.DOCTOR:
            dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
            doctor_profile_id = dp.id if dp else None
        if not doctor_profile_id:
            return jsonify({"error": "doctor_profile_id obrigatório"}), 400
        start = datetime.fromisoformat(data["start_time"])
        end = datetime.fromisoformat(data["end_time"])
        block = ScheduleBlock(clinic_id=actor.clinic_id, doctor_profile_id=doctor_profile_id, start_time=start, end_time=end, reason=data.get("reason"))
        db.session.add(block)
        db.session.commit()
        return jsonify({"id": block.id}), 201

    @role_required("DOCTOR", "CLINIC_ADMIN")
    def list(self):
        actor = User.query.get(int(get_jwt_identity()))
        q = ScheduleBlock.query.filter_by(clinic_id=actor.clinic_id)
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
        if not b or b.clinic_id != actor.clinic_id:
            return jsonify({"error": "Not found"}), 404
        if actor.role == RoleEnum.DOCTOR:
            dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
            if not dp or b.doctor_profile_id != dp.id:
                return jsonify({"error": "Forbidden"}), 403
        db.session.delete(b)
        db.session.commit()
        return jsonify({"message": "Bloqueio removido"}), 200
