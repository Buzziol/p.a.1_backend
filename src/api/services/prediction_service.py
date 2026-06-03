import io
from datetime import datetime
from typing import Optional

import numpy as np
from PIL import Image
from tensorflow import keras

from ..api_config import APIConfig
from ..models.prediction_request import PredictionRequest
from ..models.prediction_response import PredictionResponse
from ..utils.exceptions import (
    ModelNotLoadedException,
    InvalidImageException,
    PredictionException
)
from ..utils.logger import APILogger

from tensorflow.keras.applications.resnet50 import preprocess_input


class PredictionService:
    """Serviço de predição de câncer de pele."""

    def __init__(self, config: APIConfig = None):
        """
        Inicializa o serviço.

        Args:
            config: Configurações da API
        """
        self.config = config or APIConfig()
        self.logger = APILogger.get_logger('PredictionService', self.config.LOGS_DIR)
        self.model: Optional[keras.Model] = None
        self._load_model()

    def _load_model(self):
        """Carrega o modelo de predição. Não levanta exceção — o app inicia mesmo sem modelo."""
        try:
            self.logger.info(f"Carregando modelo de: {self.config.MODEL_PATH}")

            if not self.config.MODEL_PATH.exists():
                self.logger.warning(
                    f"Modelo não encontrado em: {self.config.MODEL_PATH}. "
                    "O módulo de IA ficará indisponível até que o modelo seja colocado no caminho correto."
                )
                return

            self.model = keras.models.load_model(str(self.config.MODEL_PATH))
            self.logger.info("Modelo carregado com sucesso")
            self.logger.info(f"   - Input shape: {self.model.input_shape}")
            self.logger.info(f"   - Output shape: {self.model.output_shape}")

        except Exception as e:
            self.logger.warning(
                f"Erro ao carregar modelo: {str(e)}. "
                "O módulo de IA ficará indisponível."
            )
            self.model = None

    def is_model_loaded(self):
        """Verifica se o modelo está carregado."""
        return self.model is not None

    def preprocess_image(self, image_file):
        """
        Preprocessa a imagem para o formato esperado pelo modelo.

        Args:
            image_file: Arquivo de imagem (FileStorage do Flask)

        Returns:
            Array numpy com a imagem preprocessada

        Raises:
            InvalidImageException: Se a imagem for inválida
        """
        try:
            image_bytes = image_file.read()
            image = Image.open(io.BytesIO(image_bytes))

            if image.mode != 'RGB':
                image = image.convert('RGB')

            image = image.resize(self.config.IMG_SIZE)

            img_array = np.array(image, dtype=np.float32)
            img_array = preprocess_input(img_array)
            img_array = np.expand_dims(img_array, axis=0)

            self.logger.info(f"Imagem preprocessada: shape={img_array.shape}")

            return img_array

        except Exception as e:
            self.logger.error(f"Erro ao processar imagem: {str(e)}")
            raise InvalidImageException(f"Erro ao processar imagem: {str(e)}")

    def predict(self, request: PredictionRequest):
        """
        Realiza a predição.

        Args:
            request: Requisição de predição

        Returns:
            Resposta com a predição

        Raises:
            ModelNotLoadedException: Se o modelo não estiver carregado
            PredictionException: Se houver erro na predição
        """
        try:
            if not self.is_model_loaded():
                raise ModelNotLoadedException()

            filename = getattr(request.image_file, "filename", "") or ""
            extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "none"
            self.logger.info(
                "Iniciando predição: patient_id_provided=%s, file_extension=%s",
                bool(request.patient_id),
                extension,
            )

            img_array = self.preprocess_image(request.image_file)

            prediction = self.model.predict(img_array, verbose=0)
            probability = float(prediction[0][0])

            self.logger.info(f"Predição realizada: probability={probability:.4f}")

            diagnosis = 'malignant' if probability >= self.config.MALIGNANT_THRESHOLD else 'benign'

            confidence_level = PredictionResponse.get_confidence_level(probability)

            recommendation = PredictionResponse.get_recommendation(diagnosis, confidence_level)

            response = PredictionResponse(
                diagnosis=diagnosis,
                probability=probability,
                confidence_level=confidence_level,
                recommendation=recommendation,
                timestamp=datetime.utcnow().isoformat() + 'Z',
                patient_id=request.patient_id
            )

            self.logger.info(f"Diagnóstico: {diagnosis} (confidence: {confidence_level})")

            return response

        except (ModelNotLoadedException, InvalidImageException):
            raise
        except Exception as e:
            self.logger.error(f"Erro na predição: {str(e)}")
            raise PredictionException(f"Erro ao realizar predição: {str(e)}")

    def health_check(self):
        """
        Verifica a saúde do serviço.

        Returns:
            Status do serviço
        """
        return {
            'model_loaded': self.is_model_loaded(),
            'model_path': str(self.config.MODEL_PATH),
            'model_exists': self.config.MODEL_PATH.exists()
        }
