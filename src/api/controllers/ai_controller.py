from pathlib import Path

from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity
from werkzeug.utils import secure_filename

from ..decorators.auth import role_required
from ..database.extensions import db
from ..utils.request_utils import get_json_body
from ..models_db.models import AIAnalysis, Document, MedicalRecord, User, DoctorProfile, DoctorAgreementEnum
from ..services.prediction_service import PredictionService
from ..api_config import APIConfig
from ..models.prediction_request import PredictionRequest


# Singleton para não recarregar o modelo a cada request
_prediction_service = None


def _get_prediction_service():
    global _prediction_service
    if _prediction_service is None:
        _prediction_service = PredictionService(APIConfig())
    return _prediction_service


class AIController:
    DISCLAIMER = "Este resultado é apenas uma sugestão baseada em inteligência artificial e não substitui avaliação médica profissional."
    STORAGE_DIR = Path("storage") / "documents"

    @role_required("DOCTOR")
    def analyze(self):
        actor = User.query.get(int(get_jwt_identity()))
        dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
        if not dp:
            return jsonify({"error": "Doctor profile não encontrado"}), 400

        data = {}
        if request.form:
            data = request.form.to_dict()
        else:
            data = get_json_body()
            if not data:
                return jsonify({"error": "Body JSON inválido ou vazio"}), 400

        medical_record_id = data.get("medical_record_id")
        document_id = data.get("document_id")

        if not medical_record_id:
            return jsonify({"error": "medical_record_id é obrigatório"}), 400
        mr = MedicalRecord.query.get(int(medical_record_id))
        if not mr or mr.clinic_id != actor.clinic_id:
            return jsonify({"error": "Prontuário não encontrado"}), 404
        if mr.doctor_profile_id != dp.id:
            return jsonify({"error": "Forbidden"}), 403

        doc = None
        image_file_handle = None

        try:
            if document_id:
                doc = Document.query.get(int(document_id))
                if not doc or doc.medical_record_id != mr.id:
                    return jsonify({"error": "Documento inválido"}), 404
                image_file_handle = open(doc.file_path, "rb")
                wrapped = type("F", (), {
                    "filename": doc.file_path.split('/')[-1],
                    "read": image_file_handle.read,
                    "seek": image_file_handle.seek,
                })()
                pred_req = PredictionRequest(image_file=wrapped, patient_id=str(mr.patient_id))
            elif 'file' in request.files:
                file = request.files['file']
                # Salvar o arquivo como documento primeiro para persistir a análise
                self.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
                filename = secure_filename(file.filename)
                path = self.STORAGE_DIR / f"{mr.id}_{filename}"
                file.save(path)
                doc = Document(
                    clinic_id=actor.clinic_id,
                    medical_record_id=mr.id,
                    file_path=str(path),
                    file_type=file.mimetype or "application/octet-stream",
                )
                db.session.add(doc)
                db.session.flush()
                # Reabrir para predição
                image_file_handle = open(str(path), "rb")
                wrapped = type("F", (), {
                    "filename": filename,
                    "read": image_file_handle.read,
                    "seek": image_file_handle.seek,
                })()
                pred_req = PredictionRequest(image_file=wrapped, patient_id=str(mr.patient_id))
            else:
                return jsonify({"error": "file ou document_id é obrigatório"}), 400

            service = _get_prediction_service()
            result = service.predict(pred_req)
        finally:
            if image_file_handle:
                image_file_handle.close()

        analysis = AIAnalysis(
            clinic_id=actor.clinic_id,
            medical_record_id=mr.id,
            document_id=doc.id,
            ai_diagnosis=result.diagnosis,
            probability=result.probability,
            confidence_level=result.confidence_level,
            recommendation=result.recommendation,
            model_version=result.model_version,
        )
        db.session.add(analysis)
        db.session.commit()
        return jsonify({
            "id": analysis.id,
            "ai_diagnosis": analysis.ai_diagnosis,
            "probability": analysis.probability,
            "confidence_level": analysis.confidence_level,
            "recommendation": analysis.recommendation,
            "model_version": analysis.model_version,
            "disclaimer": self.DISCLAIMER,
        }), 201

    @role_required("DOCTOR")
    def validate(self, analysis_id):
        actor = User.query.get(int(get_jwt_identity()))
        dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
        analysis = AIAnalysis.query.get(analysis_id)
        if not analysis or analysis.clinic_id != actor.clinic_id:
            return jsonify({"error": "Not found"}), 404
        mr = MedicalRecord.query.get(analysis.medical_record_id)
        if not dp or not mr or mr.doctor_profile_id != dp.id:
            return jsonify({"error": "Forbidden"}), 403
        data = get_json_body()
        if not data:
            return jsonify({"error": "Body JSON inválido ou vazio"}), 400
        try:
            analysis.doctor_agreement = DoctorAgreementEnum(data.get("doctor_agreement"))
        except Exception:
            return jsonify({"error": "doctor_agreement inválido"}), 400
        analysis.doctor_final_assessment = data.get("doctor_final_assessment")
        analysis.doctor_notes = data.get("doctor_notes")
        db.session.commit()
        return jsonify({"id": analysis.id, "doctor_agreement": analysis.doctor_agreement.value}), 200
