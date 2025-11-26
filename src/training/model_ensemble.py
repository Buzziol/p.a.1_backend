"""
Model Ensemble Manager
Responsável por combinar os modelos de cada fold em um modelo final unificado.
"""

import logging
import os

import numpy as np
from tensorflow import keras


class ModelEnsembleManager:
    """Gerencia a criação de um modelo ensemble a partir dos folds."""

    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger

    def create_ensemble_model(self, fold_models_dir: str = None):
        """
        Cria um modelo ensemble que combina todos os modelos dos folds.

        Estratégia: Averaging Ensemble
        - Carrega todos os modelos dos folds
        - Cria um novo modelo que faz a média das predições

        Args:
            fold_models_dir: Diretório contendo os modelos dos folds

        Returns:
            Modelo ensemble unificado
        """
        self.logger.info("=" * 60)
        self.logger.info("CRIANDO MODELO ENSEMBLE FINAL")
        self.logger.info("=" * 60)

        if fold_models_dir is None:
            fold_models_dir = self.config.MODELS_DIR

        fold_models = []
        for fold in range(1, self.config.N_FOLDS + 1):
            model_path = os.path.join(fold_models_dir, f'fold_{fold}_best_model.keras')

            if not os.path.exists(model_path):
                self.logger.warning(f"Modelo do Fold {fold} não encontrado: {model_path}")
                continue

            self.logger.info(f"Carregando modelo do Fold {fold}...")
            model = keras.models.load_model(model_path)
            fold_models.append(model)

        if len(fold_models) == 0:
            raise ValueError("Nenhum modelo de fold foi encontrado!")

        self.logger.info(f"\n{len(fold_models)} modelos carregados com sucesso")

        self.logger.info("\nCriando arquitetura ensemble...")

        inputs = keras.Input(shape=(*self.config.IMG_SIZE, 3))

        predictions = []
        for i, model in enumerate(fold_models):
            model._name = f'fold_{i + 1}_model'
            if hasattr(model, 'name'):
                model.name = f'fold_{i + 1}_model'
            for layer in model.layers:
                layer.trainable = False
                layer._name = f'fold_{i + 1}_{layer.name}'

            pred = model(inputs)
            predictions.append(pred)

        if len(predictions) > 1:
            averaged_output = keras.layers.Average()(predictions)
        else:
            averaged_output = predictions[0]

        ensemble_model = keras.Model(inputs=inputs, outputs=averaged_output, name='ensemble_model')

        self.logger.info("Modelo ensemble criado com sucesso")
        self.logger.info(f"   - Total de sub-modelos: {len(fold_models)}")
        self.logger.info(f"   - Estratégia: Averaging Ensemble")

        return ensemble_model

    def save_ensemble_model(
            self,
            ensemble_model: keras.Model,
            save_path: str = None
    ):
        """
        Salva o modelo ensemble.

        Args:
            ensemble_model: Modelo ensemble a ser salvo
            save_path: Caminho onde salvar o modelo

        Returns:
            Caminho onde o modelo foi salvo
        """
        if save_path is None:
            save_path = os.path.join(self.config.MODELS_DIR, 'final_ensemble_model.keras')

        self.logger.info(f"\nSalvando modelo ensemble final...")
        ensemble_model.save(save_path)
        self.logger.info(f"Modelo salvo em: {save_path}")

        ensemble_info = {
            'n_models': self.config.N_FOLDS,
            'strategy': 'averaging',
            'input_shape': (*self.config.IMG_SIZE, 3),
            'model_path': save_path
        }

        import json
        info_path = os.path.join(self.config.MODELS_DIR, 'ensemble_info.json')
        with open(info_path, 'w') as f:
            json.dump(ensemble_info, f, indent=4)

        self.logger.info(f"Informações do ensemble salvas em: {info_path}")

        return save_path

    def create_and_save_ensemble(self):
        """
        Método de conveniência que cria e salva o modelo ensemble.

        Returns:
            Caminho do modelo salvo
        """
        ensemble_model = self.create_ensemble_model()
        save_path = self.save_ensemble_model(ensemble_model)

        self.logger.info("\n" + "=" * 60)
        self.logger.info("MODELO ENSEMBLE CRIADO E SALVO COM SUCESSO")
        self.logger.info("=" * 60)

        return save_path

    def verify_ensemble_model(self, model_path: str = None):
        """
        Verifica se o modelo ensemble foi salvo corretamente.

        Args:
            model_path: Caminho do modelo a verificar

        Returns:
            True se o modelo é válido, False caso contrário
        """
        if model_path is None:
            model_path = os.path.join(self.config.MODELS_DIR, 'final_ensemble_model.keras')

        try:
            self.logger.info(f"\nVerificando modelo ensemble: {model_path}")

            if not os.path.exists(model_path):
                self.logger.error(f" Arquivo não encontrado: {model_path}")
                return False

            # Carregar modelo
            model = keras.models.load_model(model_path)

            # Verificar estrutura
            self.logger.info(f" Modelo carregado com sucesso")
            self.logger.info(f"   - Input shape: {model.input_shape}")
            self.logger.info(f"   - Output shape: {model.output_shape}")
            self.logger.info(f"   - Total de parâmetros: {model.count_params():,}")

            # Teste de predição com imagem dummy
            dummy_input = np.random.rand(1, *self.config.IMG_SIZE, 3).astype(np.float32)
            prediction = model.predict(dummy_input, verbose=0)

            self.logger.info(f"Teste de predição bem-sucedido")
            self.logger.info(f"   - Formato de saída: {prediction.shape}")
            self.logger.info(f"   - Valor da predição: {prediction[0][0]:.4f}")

            return True

        except Exception as e:
            self.logger.error(f" Erro ao verificar modelo: {str(e)}")
            return False