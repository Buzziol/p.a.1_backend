from functools import wraps
from flask import jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from ..models_db.models import User, RoleEnum


def jwt_required_custom(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        return fn(*args, **kwargs)
    return wrapper


def role_required(*allowed_roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            user_id = int(get_jwt_identity())
            user = User.query.get(user_id)
            if not user:
                return jsonify({"error": "Unauthorized"}), 401
            if user.role.value not in allowed_roles:
                return jsonify({"error": "Forbidden"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return deco


def base_permissions_for_role(role: RoleEnum):
    mapping = {
        RoleEnum.SUPER_ADMIN: ["clinics.read", "clinics.write", "users.read", "users.write", "audit.read"],
        RoleEnum.CLINIC_ADMIN: ["users.read", "users.write", "audit.read"],
        RoleEnum.DOCTOR: ["patients.read", "appointments.read"],
        RoleEnum.RECEPTIONIST: ["patients.read", "appointments.read", "appointments.write"],
    }
    return mapping.get(role, [])
