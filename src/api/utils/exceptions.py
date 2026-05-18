from enum import Enum


class ErrorCode(Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    DUPLICATE_CPF = "DUPLICATE_CPF"
    APPOINTMENT_CONFLICT = "APPOINTMENT_CONFLICT"
    SCHEDULE_BLOCK_CONFLICT = "SCHEDULE_BLOCK_CONFLICT"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    AI_UNAVAILABLE = "AI_UNAVAILABLE"


class APIException(Exception):
    """Exceção base para a API."""

    def __init__(self, message: str, status_code: int = 500, details: dict = None, code: ErrorCode = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.code = code


class ModelNotLoadedException(APIException):
    """Exceção quando o modelo não está carregado."""

    def __init__(self, message: str = "Modelo não carregado"):
        super().__init__(message, status_code=503)


class InvalidImageException(APIException):
    """Exceção para imagem inválida."""

    def __init__(self, message: str = "Imagem inválida"):
        super().__init__(message, status_code=400)


class PredictionException(APIException):
    """Exceção durante predição."""

    def __init__(self, message: str = "Erro ao realizar predição"):
        super().__init__(message, status_code=500)


class ValidationException(APIException):
    """Exceção de validação."""

    def __init__(self, message: str, details: dict = None):
        super().__init__(message, status_code=400, details=details)