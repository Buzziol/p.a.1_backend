import logging
import uuid
import time
from flask import Flask, jsonify, g, request
from flask_cors import CORS
from flasgger import Swagger
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from .api_config import APIConfig
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


# In-memory JWT blocklist (para invalidar tokens no logout)
BLOCKLIST = set()


def create_app(config: APIConfig = None) -> Flask:
    if config is None:
        config = APIConfig()
        config.validate_config()

    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = config.MAX_FILE_SIZE
    app.config['SECRET_KEY'] = config.SECRET_KEY
    app.config['JWT_SECRET_KEY'] = config.JWT_SECRET_KEY
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = config.JWT_ACCESS_TOKEN_EXPIRES
    app.config['SQLALCHEMY_DATABASE_URI'] = config.DATABASE_URL
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    CORS(app, origins=config.CORS_ORIGINS)

    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["1000 per hour", "200 per minute"],
        storage_uri="memory://",
    )

    Swagger(app, config={
        "headers": [],
        "specs": [{
            "endpoint": "apispec",
            "route": "/apispec.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }],
        "swagger_ui": True,
        "specs_route": "/docs",
        "info": {
            "title": "AegisDerm API",
            "version": "1.0.0",
            "description": (
                "API para gestão clínica dermatológica com suporte a IA. "
                "Autentique-se via POST /api/v1/auth/login e use o token JWT "
                "no header Authorization: Bearer <token>."
            ),
        },
        "securityDefinitions": {
            "Bearer": {
                "type": "apiKey",
                "name": "Authorization",
                "in": "header",
                "description": "JWT token. Formato: Bearer <token>",
            }
        },
        "basePath": "/",
        "consumes": ["application/json"],
        "produces": ["application/json"],
    })

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    from .models_db import models  # noqa: F401

    _api_logger = logging.getLogger("aegisderm.api")

    @app.before_request
    def _before_request():
        g.request_id = str(uuid.uuid4())
        g.start_time = time.time()

    @app.after_request
    def _after_request(response):
        duration_ms = round((time.time() - g.get("start_time", time.time())) * 1000, 2)
        _api_logger.info(
            "%s %s %s %.1fms [%s]",
            request.method,
            request.path,
            response.status_code,
            duration_ms,
            g.get("request_id", "-"),
        )
        response.headers["X-Request-ID"] = g.get("request_id", "")
        return response

    # JWT blocklist check
    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_payload):
        jti = jwt_payload["jti"]
        return jti in BLOCKLIST

    # Error handlers
    @app.errorhandler(400)
    def handle_bad_request(error):
        return jsonify({"error": "Requisição inválida", "code": "VALIDATION_ERROR", "message": str(error)}), 400

    @app.errorhandler(404)
    def handle_not_found(error):
        return jsonify({"error": "Não encontrado", "code": "NOT_FOUND"}), 404

    @app.errorhandler(413)
    def handle_too_large(error):
        return jsonify({
            "error": f"Arquivo muito grande. Máximo: {config.MAX_FILE_SIZE // (1024 * 1024)}MB",
            "code": "VALIDATION_ERROR",
        }), 413

    @app.errorhandler(429)
    def handle_rate_limit(error):
        return jsonify({"error": "Muitas requisições. Tente novamente em breve.", "code": "RATE_LIMIT"}), 429

    @app.errorhandler(500)
    def handle_internal(error):
        return jsonify({"error": "Erro interno do servidor", "code": "INTERNAL_ERROR"}), 500

    # Controllers
    auth_controller = AuthController()
    admin_controller = AdminController()
    patient_controller = PatientController()
    appointment_controller = AppointmentController()
    schedule_block_controller = ScheduleBlockController()
    medical_record_controller = MedicalRecordController()
    document_controller = DocumentController()
    ai_controller = AIController()

    # ── Auth ──
    @app.route('/api/v1/auth/login', methods=['POST'])
    @limiter.limit("10 per minute")
    def login():
        """
        Autenticar usuário
        ---
        tags:
          - Auth
        parameters:
          - in: body
            name: body
            required: true
            schema:
              type: object
              required: [email, password]
              properties:
                email:
                  type: string
                  example: doctor@clinic.com
                password:
                  type: string
                  example: senha123
        responses:
          200:
            description: Login realizado com sucesso
            schema:
              type: object
              properties:
                access_token:
                  type: string
                user:
                  type: object
                  properties:
                    id: {type: integer}
                    email: {type: string}
                    role: {type: string}
                    clinic_id: {type: integer}
          401:
            description: Credenciais inválidas
        """
        return auth_controller.login()

    @app.route('/api/v1/auth/me', methods=['GET'])
    def me():
        """
        Retornar dados do usuário autenticado
        ---
        tags:
          - Auth
        security:
          - Bearer: []
        responses:
          200:
            description: Dados do usuário
          401:
            description: Token inválido ou ausente
        """
        return auth_controller.me()

    @app.route('/api/v1/auth/refresh', methods=['POST'])
    @limiter.limit("30 per minute")
    def refresh():
        """
        Renovar access token usando refresh token
        ---
        tags:
          - Auth
        parameters:
          - in: body
            name: body
            required: true
            schema:
              type: object
              required: [refresh_token]
              properties:
                refresh_token:
                  type: string
        responses:
          200:
            description: Novo access token gerado
            schema:
              type: object
              properties:
                access_token: {type: string}
                expires_in: {type: integer}
          401:
            description: Refresh token inválido ou expirado
        """
        return auth_controller.refresh()

    @app.route('/api/v1/auth/logout', methods=['POST'])
    def logout():
        """
        Encerrar sessão (invalida o token)
        ---
        tags:
          - Auth
        security:
          - Bearer: []
        responses:
          200:
            description: Logout realizado com sucesso
          401:
            description: Token inválido ou ausente
        """
        return auth_controller.logout()

    # ── Admin ──
    @app.route('/api/v1/clinics', methods=['GET'])
    def list_clinics():
        """
        Listar clínicas (SUPER_ADMIN)
        ---
        tags:
          - Admin
        security:
          - Bearer: []
        responses:
          200:
            description: Lista de clínicas
          403:
            description: Acesso negado
        """
        return admin_controller.list_clinics()

    @app.route('/api/v1/clinics', methods=['POST'])
    def create_clinic():
        """
        Criar clínica (SUPER_ADMIN)
        ---
        tags:
          - Admin
        security:
          - Bearer: []
        parameters:
          - in: body
            name: body
            required: true
            schema:
              type: object
              required: [name]
              properties:
                name:
                  type: string
                  example: Clínica Derma SP
        responses:
          201:
            description: Clínica criada
          400:
            description: Dados inválidos
          403:
            description: Acesso negado
        """
        return admin_controller.create_clinic()

    @app.route('/api/v1/users', methods=['GET'])
    def list_users():
        """
        Listar usuários da clínica (CLINIC_ADMIN)
        ---
        tags:
          - Admin
        security:
          - Bearer: []
        responses:
          200:
            description: Lista de usuários
          403:
            description: Acesso negado
        """
        return admin_controller.list_users()

    @app.route('/api/v1/users', methods=['POST'])
    def create_user():
        """
        Criar usuário na clínica (CLINIC_ADMIN)
        ---
        tags:
          - Admin
        security:
          - Bearer: []
        parameters:
          - in: body
            name: body
            required: true
            schema:
              type: object
              required: [name, email, password, role]
              properties:
                name: {type: string, example: Dr. João}
                email: {type: string, example: joao@clinic.com}
                password: {type: string, example: senha123}
                role:
                  type: string
                  enum: [DOCTOR, RECEPTIONIST, CLINIC_ADMIN]
        responses:
          201:
            description: Usuário criado
          400:
            description: Dados inválidos
          409:
            description: E-mail já cadastrado
        """
        return admin_controller.create_user()

    @app.route('/api/v1/audit-logs', methods=['GET'])
    def list_audit_logs():
        """
        Listar logs de auditoria (CLINIC_ADMIN)
        ---
        tags:
          - Admin
        security:
          - Bearer: []
        responses:
          200:
            description: Lista de logs
          403:
            description: Acesso negado
        """
        return admin_controller.list_audit_logs()

    # ── Dashboard ──
    @app.route('/api/v1/dashboard', methods=['GET'])
    def dashboard():
        """
        Estatísticas do dashboard da clínica
        ---
        tags:
          - Dashboard
        security:
          - Bearer: []
        responses:
          200:
            description: Métricas da clínica
            schema:
              type: object
              properties:
                total_patients: {type: integer}
                total_appointments: {type: integer}
                appointments_today: {type: integer}
          401:
            description: Não autenticado
        """
        return admin_controller.dashboard()

    # ── Patients ──
    @app.route('/api/v1/patients', methods=['POST'])
    def create_patient():
        """
        Criar paciente (CLINIC_ADMIN, RECEPTIONIST)
        ---
        tags:
          - Patients
        security:
          - Bearer: []
        parameters:
          - in: body
            name: body
            required: true
            schema:
              type: object
              required: [name, cpf, email, phone, birth_date, blood_type, address, cep, marital_status]
              properties:
                name: {type: string, example: João Silva}
                cpf: {type: string, example: "123.456.789-00"}
                email: {type: string, example: joao@email.com}
                phone: {type: string, example: "11 99999-9999"}
                birth_date: {type: string, format: date, example: "1990-01-01"}
                blood_type: {type: string, example: O}
                address: {type: string, example: "Rua A, 123"}
                cep: {type: string, example: "01234-567"}
                marital_status:
                  type: string
                  enum: [single, married, divorced, widowed]
        responses:
          201:
            description: Paciente criado
          400:
            description: Campos obrigatórios ausentes
          409:
            description: CPF já cadastrado nesta clínica
        """
        return patient_controller.create_patient()

    @app.route('/api/v1/patients', methods=['GET'])
    def list_patients():
        """
        Listar pacientes da clínica com paginação
        ---
        tags:
          - Patients
        security:
          - Bearer: []
        parameters:
          - in: query
            name: search
            type: string
            description: Busca por nome, CPF ou e-mail
          - in: query
            name: page
            type: integer
            default: 1
          - in: query
            name: per_page
            type: integer
            default: 20
        responses:
          200:
            description: Lista paginada de pacientes
            schema:
              type: object
              properties:
                items:
                  type: array
                  items:
                    type: object
                    properties:
                      id: {type: integer}
                      name: {type: string}
                      cpf: {type: string}
                      phone: {type: string}
                      email: {type: string}
                total: {type: integer}
                page: {type: integer}
                pages: {type: integer}
        """
        return patient_controller.list_patients()

    # IMPORTANTE: Esta rota DEVE estar ANTES de /patients/<int:patient_id>
    # Caso contrário, /patients/my será interpretado como /patients/<id> onde id="my"
    @app.route('/api/v1/patients/my', methods=['GET'])
    def my_patients():
        """
        Listar meus pacientes (DOCTOR) — pacientes com consultas deste médico
        ---
        tags:
          - Patients
        security:
          - Bearer: []
        responses:
          200:
            description: Lista de pacientes do médico
          403:
            description: Acesso negado (somente DOCTOR)
        """
        return patient_controller.my_patients()

    @app.route('/api/v1/patients/<int:patient_id>', methods=['GET'])
    def get_patient(patient_id):
        """
        Buscar paciente por ID
        ---
        tags:
          - Patients
        security:
          - Bearer: []
        parameters:
          - in: path
            name: patient_id
            type: integer
            required: true
        responses:
          200:
            description: Dados completos do paciente
          404:
            description: Paciente não encontrado
        """
        return patient_controller.get_patient(patient_id)

    @app.route('/api/v1/patients/<int:patient_id>', methods=['PUT'])
    def update_patient(patient_id):
        """
        Atualizar dados do paciente (CLINIC_ADMIN, RECEPTIONIST)
        ---
        tags:
          - Patients
        security:
          - Bearer: []
        parameters:
          - in: path
            name: patient_id
            type: integer
            required: true
          - in: body
            name: body
            required: true
            schema:
              type: object
              properties:
                name: {type: string}
                phone: {type: string}
                email: {type: string}
                address: {type: string}
        responses:
          200:
            description: Paciente atualizado
          404:
            description: Paciente não encontrado
        """
        return patient_controller.update_patient(patient_id)

    @app.route('/api/v1/patients/<int:patient_id>', methods=['DELETE'])
    def delete_patient(patient_id):
        """
        Desativar paciente (soft delete) — CLINIC_ADMIN
        ---
        tags:
          - Patients
        security:
          - Bearer: []
        parameters:
          - in: path
            name: patient_id
            type: integer
            required: true
        responses:
          200:
            description: Paciente desativado
          404:
            description: Paciente não encontrado
        """
        return patient_controller.delete_patient(patient_id)

    # ── Appointments ──
    @app.route('/api/v1/appointments', methods=['POST'])
    def create_appointment():
        """
        Criar consulta (CLINIC_ADMIN, RECEPTIONIST, DOCTOR)
        ---
        tags:
          - Appointments
        security:
          - Bearer: []
        parameters:
          - in: body
            name: body
            required: true
            schema:
              type: object
              required: [patient_id, doctor_profile_id, scheduled_at]
              properties:
                patient_id: {type: integer}
                doctor_profile_id: {type: integer}
                scheduled_at: {type: string, format: date-time, example: "2026-06-15T10:00:00"}
                notes: {type: string}
        responses:
          201:
            description: Consulta criada
          400:
            description: Dados inválidos
          409:
            description: Conflito de horário
        """
        return appointment_controller.create()

    @app.route('/api/v1/appointments', methods=['GET'])
    def list_appointments():
        """
        Listar consultas com filtros opcionais
        ---
        tags:
          - Appointments
        security:
          - Bearer: []
        parameters:
          - in: query
            name: date
            type: string
            format: date
            description: Filtrar por data (YYYY-MM-DD)
          - in: query
            name: status
            type: string
            enum: [SCHEDULED, CONFIRMED, IN_PROGRESS, COMPLETED, CANCELLED, NO_SHOW, RESCHEDULED]
        responses:
          200:
            description: Lista de consultas
        """
        return appointment_controller.list()

    @app.route('/api/v1/appointments/doctor', methods=['GET'])
    def doctor_appointments():
        """
        Listar consultas do médico autenticado (DOCTOR)
        ---
        tags:
          - Appointments
        security:
          - Bearer: []
        responses:
          200:
            description: Consultas do médico
          403:
            description: Acesso negado
        """
        return appointment_controller.doctor_list()

    @app.route('/api/v1/appointments/doctor/day', methods=['GET'])
    def doctor_appointments_day():
        """
        Listar consultas do médico no dia especificado (DOCTOR)
        ---
        tags:
          - Appointments
        security:
          - Bearer: []
        parameters:
          - in: query
            name: date
            type: string
            format: date
            required: true
        responses:
          200:
            description: Consultas do dia
        """
        return appointment_controller.doctor_day()

    @app.route('/api/v1/appointments/<int:appointment_id>/status', methods=['PUT'])
    def update_appointment_status(appointment_id):
        """
        Atualizar status da consulta
        ---
        tags:
          - Appointments
        security:
          - Bearer: []
        parameters:
          - in: path
            name: appointment_id
            type: integer
            required: true
          - in: body
            name: body
            required: true
            schema:
              type: object
              required: [status]
              properties:
                status:
                  type: string
                  enum: [SCHEDULED, CONFIRMED, IN_PROGRESS, COMPLETED, CANCELLED, NO_SHOW, RESCHEDULED]
        responses:
          200:
            description: Status atualizado
          404:
            description: Consulta não encontrada
        """
        return appointment_controller.update_status(appointment_id)

    @app.route('/api/v1/appointments/<int:appointment_id>/reschedule', methods=['PUT'])
    def reschedule_appointment(appointment_id):
        """
        Reagendar consulta
        ---
        tags:
          - Appointments
        security:
          - Bearer: []
        parameters:
          - in: path
            name: appointment_id
            type: integer
            required: true
          - in: body
            name: body
            required: true
            schema:
              type: object
              required: [scheduled_at]
              properties:
                scheduled_at: {type: string, format: date-time}
        responses:
          200:
            description: Consulta reagendada
          409:
            description: Conflito de horário
        """
        return appointment_controller.reschedule(appointment_id)

    @app.route('/api/v1/appointments/<int:appointment_id>', methods=['DELETE'])
    def cancel_appointment(appointment_id):
        """
        Cancelar consulta
        ---
        tags:
          - Appointments
        security:
          - Bearer: []
        parameters:
          - in: path
            name: appointment_id
            type: integer
            required: true
        responses:
          200:
            description: Consulta cancelada
          404:
            description: Consulta não encontrada
        """
        return appointment_controller.cancel(appointment_id)

    # ── Schedule Blocks ──
    @app.route('/api/v1/schedule-blocks', methods=['POST'])
    def create_schedule_block():
        """
        Criar bloqueio de agenda (DOCTOR, CLINIC_ADMIN)
        ---
        tags:
          - Schedule Blocks
        security:
          - Bearer: []
        parameters:
          - in: body
            name: body
            required: true
            schema:
              type: object
              required: [start_time, end_time]
              properties:
                start_time: {type: string, format: date-time, example: "2026-06-20T09:00:00"}
                end_time: {type: string, format: date-time, example: "2026-06-20T12:00:00"}
                reason: {type: string, example: Congresso médico}
        responses:
          201:
            description: Bloqueio criado
          409:
            description: Conflito com consulta ou outro bloqueio
        """
        return schedule_block_controller.create()

    @app.route('/api/v1/schedule-blocks', methods=['GET'])
    def list_schedule_blocks():
        """
        Listar bloqueios de agenda do médico/clínica
        ---
        tags:
          - Schedule Blocks
        security:
          - Bearer: []
        responses:
          200:
            description: Lista de bloqueios
        """
        return schedule_block_controller.list()

    @app.route('/api/v1/schedule-blocks/<int:block_id>', methods=['DELETE'])
    def delete_schedule_block(block_id):
        """
        Remover bloqueio de agenda (DOCTOR, CLINIC_ADMIN)
        ---
        tags:
          - Schedule Blocks
        security:
          - Bearer: []
        parameters:
          - in: path
            name: block_id
            type: integer
            required: true
        responses:
          200:
            description: Bloqueio removido
          404:
            description: Bloqueio não encontrado
        """
        return schedule_block_controller.delete(block_id)

    # ── Medical Records ──
    @app.route('/api/v1/medical-records', methods=['POST'])
    def create_medical_record():
        """
        Criar prontuário médico (DOCTOR)
        ---
        tags:
          - Medical Records
        security:
          - Bearer: []
        parameters:
          - in: body
            name: body
            required: true
            schema:
              type: object
              required: [patient_id, appointment_id]
              properties:
                patient_id: {type: integer}
                appointment_id: {type: integer}
                anamnesis: {type: string}
                diagnosis: {type: string}
                prescription: {type: string}
                observations: {type: string}
        responses:
          201:
            description: Prontuário criado
          400:
            description: Dados inválidos
          403:
            description: Acesso negado (somente DOCTOR)
        """
        return medical_record_controller.create()

    @app.route('/api/v1/medical-records', methods=['GET'])
    def list_medical_records():
        """
        Listar prontuários do médico autenticado (DOCTOR)
        ---
        tags:
          - Medical Records
        security:
          - Bearer: []
        responses:
          200:
            description: Lista de prontuários
          403:
            description: Acesso negado
        """
        return medical_record_controller.list()

    @app.route('/api/v1/medical-records/<int:record_id>', methods=['GET'])
    def get_medical_record(record_id):
        """
        Buscar prontuário por ID (DOCTOR)
        ---
        tags:
          - Medical Records
        security:
          - Bearer: []
        parameters:
          - in: path
            name: record_id
            type: integer
            required: true
        responses:
          200:
            description: Prontuário completo com análises de IA
          404:
            description: Prontuário não encontrado
        """
        return medical_record_controller.get(record_id)

    @app.route('/api/v1/medical-records/<int:record_id>', methods=['PUT'])
    def update_medical_record(record_id):
        """
        Atualizar prontuário médico (DOCTOR)
        ---
        tags:
          - Medical Records
        security:
          - Bearer: []
        parameters:
          - in: path
            name: record_id
            type: integer
            required: true
          - in: body
            name: body
            required: true
            schema:
              type: object
              properties:
                anamnesis: {type: string}
                diagnosis: {type: string}
                prescription: {type: string}
        responses:
          200:
            description: Prontuário atualizado
          404:
            description: Prontuário não encontrado
        """
        return medical_record_controller.update(record_id)

    # ── Documents ──
    @app.route('/api/v1/documents/upload', methods=['POST'])
    def upload_document():
        """
        Upload de documento/imagem (DOCTOR, CLINIC_ADMIN)
        ---
        tags:
          - Documents
        security:
          - Bearer: []
        consumes:
          - multipart/form-data
        parameters:
          - in: formData
            name: file
            type: file
            required: true
            description: Imagem ou documento (PNG, JPG, JPEG; máx 10MB)
          - in: formData
            name: medical_record_id
            type: integer
            required: true
        responses:
          201:
            description: Documento enviado com sucesso
          400:
            description: Arquivo inválido ou campos ausentes
          413:
            description: Arquivo excede o tamanho máximo
        """
        return document_controller.upload()

    # ── AI ──
    @app.route('/api/v1/ai/analyze', methods=['POST'])
    @limiter.limit("20 per minute")
    def ai_analyze():
        """
        Analisar imagem dermatológica com IA (DOCTOR)
        ---
        tags:
          - AI Analysis
        security:
          - Bearer: []
        consumes:
          - multipart/form-data
        parameters:
          - in: formData
            name: file
            type: file
            description: Imagem dermatológica (PNG, JPG, JPEG)
          - in: formData
            name: medical_record_id
            type: integer
            required: true
          - in: formData
            name: document_id
            type: integer
            description: ID de documento já existente (alternativa ao upload)
        responses:
          201:
            description: Análise realizada com sucesso
            schema:
              type: object
              properties:
                id: {type: integer}
                ai_diagnosis: {type: string, enum: [benign, malignant]}
                probability: {type: number, format: float}
                confidence_level: {type: string, enum: [high, medium, low]}
                recommendation: {type: string}
                model_version: {type: string}
                disclaimer: {type: string}
          400:
            description: Dados inválidos
          403:
            description: Acesso negado (somente DOCTOR)
          503:
            description: Modelo de IA indisponível
        """
        return ai_controller.analyze()

    @app.route('/api/v1/ai/<int:analysis_id>/validate', methods=['PUT'])
    def ai_validate(analysis_id):
        """
        Médico valida resultado da análise de IA (DOCTOR)
        ---
        tags:
          - AI Analysis
        security:
          - Bearer: []
        parameters:
          - in: path
            name: analysis_id
            type: integer
            required: true
          - in: body
            name: body
            required: true
            schema:
              type: object
              required: [doctor_agreement]
              properties:
                doctor_agreement:
                  type: string
                  enum: [AGREE, DISAGREE, PARTIALLY_AGREE]
                doctor_final_assessment: {type: string}
                doctor_notes: {type: string}
        responses:
          200:
            description: Validação registrada
          404:
            description: Análise não encontrada
        """
        return ai_controller.validate(analysis_id)

    # ── CLI ──
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
