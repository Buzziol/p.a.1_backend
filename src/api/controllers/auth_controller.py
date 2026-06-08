from datetime import timedelta
from flask import request, jsonify
from flask_jwt_extended import create_access_token, get_jwt_identity, get_jwt
from ..decorators.auth import jwt_required_custom, base_permissions_for_role
from ..models_db.models import User, RefreshToken
from ..database.extensions import db


def _user_is_active(user):
    return True if user.is_active is None else bool(user.is_active)


class AuthController:
    def login(self):
        data = request.get_json(silent=True) or {}
        email = data.get("email")
        password = data.get("password")
        if not email or not password:
            return jsonify({"error": "Email e senha são obrigatórios"}), 400

        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password) or not user.is_active:
            return jsonify({"error": "Credenciais inválidas"}), 401

        access_token = create_access_token(
            identity=str(user.id),
            additional_claims={"role": user.role.value, "clinic_id": user.clinic_id},
        )
        refresh_token = RefreshToken.create(user.id, expires_in_days=30)
        db.session.commit()

        return jsonify({
            "access_token": access_token,
            "refresh_token": refresh_token.token,
            "expires_in": 28800,  # 8 hours in seconds (default JWT_ACCESS_TOKEN_EXPIRES)
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "role": user.role.value,
                "clinic_id": user.clinic_id,
                "is_active": _user_is_active(user),
            },
            "clinic": {"id": user.clinic_id} if user.clinic_id else None,
        }), 200

    def refresh(self):
        """Exchange a valid refresh token for a new access token."""
        data = request.get_json(silent=True) or {}
        token_str = data.get("refresh_token")
        if not token_str:
            return jsonify({"error": "refresh_token é obrigatório"}), 400

        rt = RefreshToken.query.filter_by(token=token_str).first()
        if not rt or not rt.is_valid():
            return jsonify({"error": "Refresh token inválido ou expirado"}), 401

        user = User.query.get(rt.user_id)
        if not user or not user.is_active:
            return jsonify({"error": "Usuário inativo"}), 401

        new_access_token = create_access_token(
            identity=str(user.id),
            additional_claims={"role": user.role.value, "clinic_id": user.clinic_id},
        )
        return jsonify({"access_token": new_access_token, "expires_in": 28800}), 200

    @jwt_required_custom
    def me(self):
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "Usuário não encontrado"}), 404
        return jsonify({
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role.value,
            "clinic_id": user.clinic_id,
            "is_active": _user_is_active(user),
            "permissions": base_permissions_for_role(user.role),
        }), 200

    @jwt_required_custom
    def logout(self):
        from ..app import BLOCKLIST
        jti = get_jwt()["jti"]
        BLOCKLIST.add(jti)
        user_id = int(get_jwt_identity())
        # Revoke all refresh tokens for this user
        RefreshToken.query.filter_by(user_id=user_id, revoked=False).update({"revoked": True})
        db.session.commit()
        return jsonify({"message": "Logout realizado com sucesso"}), 200
