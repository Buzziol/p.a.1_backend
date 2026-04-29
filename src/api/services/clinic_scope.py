from flask_jwt_extended import get_jwt_identity
from ..models_db.models import User, RoleEnum


def get_current_user():
    uid = int(get_jwt_identity())
    return User.query.get(uid)


def assert_clinic_scope(entity_clinic_id):
    user = get_current_user()
    if user.role == RoleEnum.SUPER_ADMIN:
        return True
    return user.clinic_id == entity_clinic_id
