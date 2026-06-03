"""
Testes para PredictionService e fluxo de análise de IA.

Estes testes não carregam o modelo TensorFlow real (é grande demais para CI).
Usam um mock do modelo para validar a lógica de pré-processamento,
confiança e recomendações.
"""

import io
import time
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
from PIL import Image

import sys
sys.path.insert(0, '.')

from src.api.api_config import APIConfig
from src.api.models.prediction_request import PredictionRequest
from src.api.models.prediction_response import PredictionResponse


def _make_fake_image_file(size=(300, 300), mode="RGB", color=None) -> MagicMock:
    """Cria um objeto de arquivo de imagem fake para testes."""
    if color is None:
        color = (128, 64, 192) if mode == "RGB" else 128
    buf = io.BytesIO()
    img = Image.new(mode, size, color=color)
    img.save(buf, format="JPEG")
    buf.seek(0)

    fake_file = MagicMock()
    fake_file.filename = "test_lesao.jpg"
    fake_file.read.side_effect = lambda: buf.read()
    fake_file.seek.side_effect = lambda pos: buf.seek(pos)
    return fake_file


class TestPredictionServiceWithMock(unittest.TestCase):

    def setUp(self):
        """Configura um PredictionService com modelo mockado."""
        from src.api.services.prediction_service import PredictionService

        with patch.object(PredictionService, '_load_model'):
            self.service = PredictionService(APIConfig())

        # Mock do modelo: retorna probabilidade 0.8 (maligno com alta confiança)
        self.service.model = MagicMock()
        self.service.model.predict.return_value = np.array([[0.8]])
        self.service.model.input_shape = (None, 224, 224, 3)
        self.service.model.output_shape = (None, 1)

    def test_is_model_loaded_true_with_mock(self):
        self.assertTrue(self.service.is_model_loaded())

    def test_is_model_loaded_false_without_model(self):
        from src.api.services.prediction_service import PredictionService
        with patch.object(PredictionService, '_load_model'):
            svc = PredictionService(APIConfig())
        svc.model = None
        self.assertFalse(svc.is_model_loaded())

    def test_preprocess_image_returns_correct_shape(self):
        fake_file = _make_fake_image_file()
        result = self.service.preprocess_image(fake_file)
        self.assertEqual(result.shape, (1, 224, 224, 3))

    def test_preprocess_grayscale_image_converts_to_rgb(self):
        fake_file = _make_fake_image_file(mode="L", color=128)
        result = self.service.preprocess_image(fake_file)
        self.assertEqual(result.shape, (1, 224, 224, 3))

    def test_predict_returns_malignant_for_high_probability(self):
        self.service.model.predict.return_value = np.array([[0.85]])
        fake_file = _make_fake_image_file()
        req = PredictionRequest(image_file=fake_file, patient_id="42")
        response = self.service.predict(req)
        self.assertEqual(response.diagnosis, "malignant")
        self.assertAlmostEqual(response.probability, 0.85, places=2)

    def test_predict_returns_benign_for_low_probability(self):
        self.service.model.predict.return_value = np.array([[0.2]])
        fake_file = _make_fake_image_file()
        req = PredictionRequest(image_file=fake_file, patient_id="42")
        response = self.service.predict(req)
        self.assertEqual(response.diagnosis, "benign")

    def test_predict_speed_under_10s(self):
        """Predição mockada deve completar bem abaixo do timeout de 10s."""
        fake_file = _make_fake_image_file()
        req = PredictionRequest(image_file=fake_file, patient_id="1")
        start = time.time()
        self.service.predict(req)
        elapsed = time.time() - start
        self.assertLess(elapsed, 10)

    def test_predict_raises_when_model_not_loaded(self):
        from src.api.utils.exceptions import ModelNotLoadedException
        self.service.model = None
        fake_file = _make_fake_image_file()
        req = PredictionRequest(image_file=fake_file, patient_id="1")
        with self.assertRaises(ModelNotLoadedException):
            self.service.predict(req)

    def test_health_check_returns_loaded_true(self):
        result = self.service.health_check()
        self.assertTrue(result["model_loaded"])

    def test_health_check_returns_loaded_false_without_model(self):
        self.service.model = None
        result = self.service.health_check()
        self.assertFalse(result["model_loaded"])


class TestConfidenceLevel(unittest.TestCase):

    def test_high_confidence_malignant(self):
        level = PredictionResponse.get_confidence_level(0.95)
        self.assertEqual(level, "high")

    def test_high_confidence_benign(self):
        level = PredictionResponse.get_confidence_level(0.05)
        self.assertEqual(level, "high")

    def test_low_confidence_near_threshold(self):
        level = PredictionResponse.get_confidence_level(0.51)
        self.assertEqual(level, "low")

    def test_recommendation_malignant_high(self):
        rec = PredictionResponse.get_recommendation("malignant", "high")
        self.assertIn("URGENTE", rec)

    def test_recommendation_malignant_low(self):
        rec = PredictionResponse.get_recommendation("malignant", "low")
        self.assertIn("dermatologista", rec.lower())

    def test_recommendation_benign_high(self):
        rec = PredictionResponse.get_recommendation("benign", "high")
        self.assertIn("benigna", rec.lower())


class TestPredictionRequest(unittest.TestCase):

    def test_valid_request(self):
        fake_file = _make_fake_image_file()
        req = PredictionRequest(image_file=fake_file, patient_id="1")
        valid, msg = req.validate()
        self.assertTrue(valid, msg)

    def test_invalid_extension(self):
        fake_file = MagicMock()
        fake_file.filename = "virus.exe"
        req = PredictionRequest(image_file=fake_file, patient_id="1")
        valid, msg = req.validate()
        self.assertFalse(valid)


class TestLegacyAIRoutes(unittest.TestCase):

    def setUp(self):
        from src.api.app import create_app

        cfg = APIConfig()
        cfg.DATABASE_URL = "sqlite:///:memory:"
        self.app = create_app(cfg)
        self.client = self.app.test_client()

    @patch("src.api.controllers.ai_controller._get_prediction_service")
    def test_legacy_health_returns_controlled_json(self, get_service):
        service = MagicMock()
        service.health_check.return_value = {
            "model_loaded": False,
            "model_path": "missing.keras",
            "model_exists": False,
        }
        get_service.return_value = service

        response = self.client.get("/api/v1/health", headers={"Origin": "http://localhost:8080"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "http://localhost:8080")
        self.assertEqual(response.get_json()["status"], "healthy")

    @patch("src.api.controllers.ai_controller._get_prediction_service")
    def test_legacy_predict_keeps_existing_contract(self, get_service):
        service = MagicMock()
        service.predict.return_value = PredictionResponse(
            diagnosis="benign",
            probability=0.2,
            confidence_level="high",
            recommendation="Monitore alteracoes.",
            timestamp="2026-05-29T00:00:00Z",
            patient_id="PAT001",
        )
        get_service.return_value = service

        fake_file = _make_fake_image_file()
        response = self.client.post(
            "/api/v1/predict",
            data={"file": (io.BytesIO(fake_file.read()), fake_file.filename), "patient_id": "PAT001"},
            content_type="multipart/form-data",
            headers={"Origin": "http://localhost:8080"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "http://localhost:8080")
        self.assertEqual(response.get_json()["patient_id"], "PAT001")


if __name__ == "__main__":
    unittest.main()
