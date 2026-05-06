from flask import request, jsonify
from flask_jwt_extended import create_access_token, get_jwt_identity, get_jwt
from ..decorators.auth import jwt_required_custom, base_permissions_for_role
from ..models_db.models import User


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

        token = create_access_token(
            identity=str(user.id),
            additional_claims={"role": user.role.value, "clinic_id": user.clinic_id},
        )
        return jsonify({
            "access_token": token,
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "role": user.role.value,
                "clinic_id": user.clinic_id,
            },
            "clinic": {"id": user.clinic_id} if user.clinic_id else None,
        }), 200

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
            "permissions": base_permissions_for_role(user.role),
        }), 200

    @jwt_required_custom
    def logout(self):
        from ..app import BLOCKLIST
        jti = get_jwt()["jti"]
        BLOCKLIST.add(jti)
        return jsonify({"message": "Logout realizado com sucesso"}), 200
