# Configuração da IA — AegisDerm

## Modelo

| Item | Valor |
|------|-------|
| **Arquivo** | `src/models/final_ensemble_model.keras` |
| **Framework** | TensorFlow / Keras |
| **Estratégia** | Ensemble de 5 folds (média de probabilidades) |
| **Input** | 224 × 224 × 3 (RGB, pré-processado com ResNet50) |
| **Output** | Probabilidade 0–1 de lesão maligna |
| **Tamanho** | ~958 MB |
| **Threshold** | 0.5 (acima → maligno) |

## Arquivos de fold

```
src/models/
├── final_ensemble_model.keras   ← modelo usado em produção
├── fold_1_best_model.keras
├── fold_2_best_model.keras
├── fold_3_best_model.keras
├── fold_4_best_model.keras
├── fold_5_best_model.keras
└── ensemble_info.json
```

## Fluxo de predição

```
POST /api/v1/ai/analyze
│
├─ Autenticação JWT (role: DOCTOR)
├─ Validação do prontuário médico (medical_record_id)
├─ Recebe imagem via multipart/form-data OU document_id existente
│
├─ PredictionService.predict()
│   ├─ preprocess_image()   → resize 224×224, normaliza ResNet50
│   ├─ model.predict()      → probabilidade [0..1]
│   ├─ get_confidence_level() → HIGH | MEDIUM | LOW
│   └─ get_recommendation() → texto de recomendação médica
│
├─ Persiste AIAnalysis no banco
└─ Retorna { ai_diagnosis, probability, confidence_level, recommendation, disclaimer }
```

## Níveis de confiança

| Nível | Distância do threshold |
|-------|------------------------|
| HIGH   | ≥ 0.2 de 0.5           |
| MEDIUM | ≥ 0.4 de 0.5           |
| LOW    | < 0.4 de 0.5           |

## Singleton

O modelo é carregado **uma única vez** no startup via singleton em `ai_controller.py`:

```python
_prediction_service = None

def _get_prediction_service():
    global _prediction_service
    if _prediction_service is None:
        _prediction_service = PredictionService(APIConfig())
    return _prediction_service
```

Isso evita recarregar ~958 MB a cada request.

## Inicialização sem modelo

O sistema **inicia normalmente** mesmo sem o arquivo de modelo. Se o arquivo não existir, `PredictionService.is_model_loaded()` retorna `False` e o endpoint `/api/v1/ai/analyze` responde `503 Service Unavailable`.

## Memória

- Carregamento: ~2.0 GB de RAM
- Durante inferência: ~2.5 GB
- GPU: recomendado para produção (reduz latência de ~5s para ~0.5s)

## Retraining

Ver `src/training/model_training.py` e `src/training/model_ensemble.py`.

## Testes

```bash
cd p.a.1_backend
source venv/bin/activate
python -m pytest tests/test_ai_analysis.py -v
```
