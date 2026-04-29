from flask import Flask
from flask_cors import CORS
from flasgger import Swagger

from .api_config import APIConfig
from .controllers.prediction_controller import PredictionController
from .controllers.auth_controller import AuthController
from .controllers.admin_controller import AdminController
from .database.extensions import db, migrate, jwt
from .seed.seed_data import run_seed


def create_app(config: APIConfig = None) -> Flask:
    if config is None:
        config = APIConfig()
        config.validate_config()

    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = config.MAX_FILE_SIZE
    app.config['SECRET_KEY'] = config.SECRET_KEY
    app.config['JWT_SECRET_KEY'] = config.JWT_SECRET_KEY
    app.config['SQLALCHEMY_DATABASE_URI'] = config.DATABASE_URL
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    CORS(app, origins=config.CORS_ORIGINS)
    Swagger(app, config={"headers": [], "specs": [{"endpoint": "apispec", "route": "/apispec.json", "rule_filter": lambda rule: True, "model_filter": lambda tag: True}], "swagger_ui": True, "specs_route": "/docs"})

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    from .models_db import models  # noqa: F401

    prediction_controller = PredictionController()
    auth_controller = AuthController()
    admin_controller = AdminController()

    @app.route('/api/v1/predict', methods=['POST'])
    def predict():
        return prediction_controller.predict()

    @app.route('/api/v1/health', methods=['GET'])
    def health_check():
        return prediction_controller.health()

    @app.route('/api/v1/auth/login', methods=['POST'])
    def login():
        return auth_controller.login()

    @app.route('/api/v1/auth/me', methods=['GET'])
    def me():
        return auth_controller.me()

    @app.route('/api/v1/auth/logout', methods=['POST'])
    def logout():
        return auth_controller.logout()

    @app.route('/api/v1/clinics', methods=['GET'])
    def list_clinics():
        return admin_controller.list_clinics()

    @app.route('/api/v1/clinics', methods=['POST'])
    def create_clinic():
        return admin_controller.create_clinic()

    @app.route('/api/v1/users', methods=['GET'])
    def list_users():
        return admin_controller.list_users()

    @app.route('/api/v1/users', methods=['POST'])
    def create_user():
        return admin_controller.create_user()

    @app.route('/api/v1/audit-logs', methods=['GET'])
    def list_audit_logs():
        return admin_controller.list_audit_logs()

    @app.cli.command("seed")
    def seed_command():
        run_seed()
        print("Seed executado com sucesso")

    return app


def main():
    config = APIConfig()
    app = create_app(config)
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)


if __name__ == '__main__':
    main()
