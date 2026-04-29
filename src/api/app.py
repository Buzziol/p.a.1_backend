from flask import Flask, jsonify
from flask_cors import CORS
from flasgger import Swagger

from .api_config import APIConfig
from .controllers.prediction_controller import PredictionController
from .controllers.auth_controller import AuthController
from .controllers.admin_controller import AdminController
from .controllers.patient_controller import PatientController
from .controllers.appointment_controller import AppointmentController
from .controllers.schedule_block_controller import ScheduleBlockController
from .controllers.medical_record_controller import MedicalRecordController
from .controllers.document_controller import DocumentController
from .controllers.ai_controller import AIController
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

    @app.errorhandler(400)
    def handle_bad_request(error):
        return jsonify({"error": "Requisição inválida", "message": str(error)}), 400


    prediction_controller = PredictionController()
    auth_controller = AuthController()
    admin_controller = AdminController()
    patient_controller = PatientController()
    appointment_controller = AppointmentController()
    schedule_block_controller = ScheduleBlockController()
    medical_record_controller = MedicalRecordController()
    document_controller = DocumentController()
    ai_controller = AIController()

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


    @app.route('/api/v1/patients', methods=['POST'])
    def create_patient():
        return patient_controller.create_patient()

    @app.route('/api/v1/patients', methods=['GET'])
    def list_patients():
        return patient_controller.list_patients()

    @app.route('/api/v1/patients/<int:patient_id>', methods=['GET'])
    def get_patient(patient_id):
        return patient_controller.get_patient(patient_id)

    @app.route('/api/v1/patients/<int:patient_id>', methods=['PUT'])
    def update_patient(patient_id):
        return patient_controller.update_patient(patient_id)

    @app.route('/api/v1/patients/<int:patient_id>', methods=['DELETE'])
    def delete_patient(patient_id):
        return patient_controller.delete_patient(patient_id)

    @app.route('/api/v1/patients/my', methods=['GET'])
    def my_patients():
        return patient_controller.my_patients()

    @app.route('/api/v1/appointments', methods=['POST'])
    def create_appointment():
        return appointment_controller.create()

    @app.route('/api/v1/appointments', methods=['GET'])
    def list_appointments():
        return appointment_controller.list()

    @app.route('/api/v1/appointments/doctor', methods=['GET'])
    def doctor_appointments():
        return appointment_controller.doctor_list()

    @app.route('/api/v1/appointments/doctor/day', methods=['GET'])
    def doctor_appointments_day():
        return appointment_controller.doctor_day()

    @app.route('/api/v1/appointments/<int:appointment_id>/status', methods=['PUT'])
    def update_appointment_status(appointment_id):
        return appointment_controller.update_status(appointment_id)

    @app.route('/api/v1/appointments/<int:appointment_id>/reschedule', methods=['PUT'])
    def reschedule_appointment(appointment_id):
        return appointment_controller.reschedule(appointment_id)

    @app.route('/api/v1/appointments/<int:appointment_id>', methods=['DELETE'])
    def cancel_appointment(appointment_id):
        return appointment_controller.cancel(appointment_id)

    @app.route('/api/v1/schedule-blocks', methods=['POST'])
    def create_schedule_block():
        return schedule_block_controller.create()

    @app.route('/api/v1/schedule-blocks', methods=['GET'])
    def list_schedule_blocks():
        return schedule_block_controller.list()

    @app.route('/api/v1/schedule-blocks/<int:block_id>', methods=['DELETE'])
    def delete_schedule_block(block_id):
        return schedule_block_controller.delete(block_id)



    @app.route('/api/v1/medical-records', methods=['POST'])
    def create_medical_record():
        return medical_record_controller.create()

    @app.route('/api/v1/medical-records/<int:record_id>', methods=['GET'])
    def get_medical_record(record_id):
        return medical_record_controller.get(record_id)

    @app.route('/api/v1/medical-records/<int:record_id>', methods=['PUT'])
    def update_medical_record(record_id):
        return medical_record_controller.update(record_id)

    @app.route('/api/v1/documents/upload', methods=['POST'])
    def upload_document():
        return document_controller.upload()

    @app.route('/api/v1/ai/analyze', methods=['POST'])
    def ai_analyze():
        return ai_controller.analyze()

    @app.route('/api/v1/ai/<int:analysis_id>/validate', methods=['PUT'])
    def ai_validate(analysis_id):
        return ai_controller.validate(analysis_id)

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
