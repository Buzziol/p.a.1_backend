"""
Configurações da API REST
"""

import os
import secrets
from datetime import timedelta
from pathlib import Path


class APIConfig:
    """Configurações da API."""

    DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    HOST = os.getenv('API_HOST', '0.0.0.0')
    PORT = int(os.getenv('API_PORT', 5000))

    # Diretórios
    BASE_DIR = Path(__file__).resolve().parent.parent.parent
    MODELS_DIR = BASE_DIR / "models"
    LOGS_DIR = BASE_DIR / "logs"
    MODEL_PATH = MODELS_DIR / "final_ensemble_model.keras"

    # Banco de dados
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///dermato.db")

    # Segurança — nunca usar os defaults em produção
    SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", secrets.token_hex(32))
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        hours=int(os.getenv("JWT_TOKEN_HOURS", "8"))
    )

    # Imagens / upload
    IMG_SIZE = (224, 224)
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

    # Modelo IA
    MALIGNANT_THRESHOLD = 0.5
    CONFIDENCE_HIGH = 0.8
    CONFIDENCE_MEDIUM = 0.6
    CONFIDENCE_LOW = 0.4

    # Swagger
    SWAGGER_TITLE = "AegisDerm API"
    SWAGGER_VERSION = "1.0.0"
    SWAGGER_DESCRIPTION = """API para gestão clínica dermatológica com suporte a IA."""

    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    # CORS — restringir em produção
    CORS_ORIGINS = os.getenv(
        'CORS_ORIGINS',
        'http://localhost:5173,http://localhost:4173'
    ).split(',')

    @classmethod
    def validate_config(cls):
        if not cls.MODELS_DIR.exists():
            raise FileNotFoundError(f"Diretório de modelos não encontrado: {cls.MODELS_DIR}")
        if not cls.MODEL_PATH.exists():
            raise FileNotFoundError(f"Modelo não encontrado: {cls.MODEL_PATH}")
        cls.LOGS_DIR.mkdir(exist_ok=True)
