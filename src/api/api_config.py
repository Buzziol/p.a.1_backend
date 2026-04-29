"""
Configurações da API REST
"""

import os
from pathlib import Path


class APIConfig:
    """Configurações da API de predição."""

    DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    HOST = os.getenv('API_HOST', '0.0.0.0')
    PORT = int(os.getenv('API_PORT', 5000))

    MODELS_DIR = Path("src") / "models"
    LOGS_DIR = Path("src") / "logs"
    MODEL_PATH = MODELS_DIR / "final_ensemble_model.keras"

    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///dermato.db")
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-jwt-secret")

    IMG_SIZE = (224, 224)
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
    MAX_FILE_SIZE = 10 * 1024 * 1024

    MALIGNANT_THRESHOLD = 0.5

    CONFIDENCE_HIGH = 0.8
    CONFIDENCE_MEDIUM = 0.6
    CONFIDENCE_LOW = 0.4

    SWAGGER_TITLE = "Skin Cancer Classification API"
    SWAGGER_VERSION = "1.0.0"
    SWAGGER_DESCRIPTION = """API para classificação de lesões de pele e fundação clínica."""

    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    CORS_ORIGINS = os.getenv('CORS_ORIGINS', '*').split(',')

    @classmethod
    def validate_config(cls):
        if not cls.MODELS_DIR.exists():
            raise FileNotFoundError(f"Diretório de modelos não encontrado: {cls.MODELS_DIR}")
        if not cls.MODEL_PATH.exists():
            raise FileNotFoundError(f"Modelo não encontrado: {cls.MODEL_PATH}")
        cls.LOGS_DIR.mkdir(exist_ok=True)
