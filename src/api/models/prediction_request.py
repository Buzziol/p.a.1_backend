from dataclasses import dataclass
from typing import Optional, Dict, Any

@dataclass
class PredictionRequest:
    """Requisição de predição."""

    image_file: Any
    patient_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def validate(self):
        """
        Valida a requisição.

        Returns:
            (is_valid, error_message)
        """
        if not self.image_file:
            return False, "Nenhuma imagem foi fornecida"

        if not self.image_file.filename:
            return False, "Nome do arquivo inválido"

        # Validar extensão
        from ..api_config import APIConfig
        parts = self.image_file.filename.rsplit('.', 1)
        if len(parts) < 2:
            return False, f"Arquivo sem extensão. Use: {', '.join(APIConfig.ALLOWED_EXTENSIONS)}"
        extension = parts[1].lower()
        if extension not in APIConfig.ALLOWED_EXTENSIONS:
            return False, f"Formato de arquivo não suportado. Use: {', '.join(APIConfig.ALLOWED_EXTENSIONS)}"

        return True, None

