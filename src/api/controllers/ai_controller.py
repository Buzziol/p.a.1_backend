from pathlib import Path
from datetime import datetime, timezone

from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity
from werkzeug.utils import secure_filename

from ..decorators.auth import role_required
from ..database.extensions import db
from ..utils.request_utils import get_json_body
from ..models_db.models import AIAnalysis, Document, MedicalRecord, User, DoctorAgreementEnum, RoleEnum
from ..services.clinic_scope import doctor_can_access_medical_record, get_doctor_profile
from ..services.prediction_service import PredictionService
from ..api_config import APIConfig
from ..models.prediction_request import PredictionRequest
from ..utils.exceptions import APIException
from .document_controller import MAX_DOCUMENTS_PER_MEDICAL_RECORD


# Singleton para não recarregar o modelo a cada request
_prediction_service = None


def _get_prediction_service():
    global _prediction_service
    if _prediction_service is None:
        _prediction_service = PredictionService(APIConfig())
    return _prediction_service


def _utcnow():
    return datetime.now(timezone.utc)


def _iso(dt):
    if not dt:
        return None
    return dt.isoformat() + ("Z" if dt.tzinfo is None else "")


def serialize_ai_analysis(analysis, include_validation=True):
    data = {
        "id": analysis.id,
        "medical_record_id": analysis.medical_record_id,
        "document_id": analysis.document_id,
        "ai_diagnosis": analysis.ai_diagnosis,
        "probability": round(float(analysis.probability), 4),
        "confidence_level": analysis.confidence_level,
        "recommendation": analysis.recommendation,
        "model_version": analysis.model_version,
        "disclaimer": analysis.disclaimer,
        "created_at": _iso(analysis.created_at),
    }
    if include_validation:
        data.update({
            "doctor_agreement": analysis.doctor_agreement.value if analysis.doctor_agreement else None,
            "doctor_final_assessment": analysis.doctor_final_assessment,
            "doctor_notes": analysis.doctor_notes,
            "validated_at": _iso(analysis.validated_at),
            "updated_at": _iso(analysis.updated_at),
        })
    return data


class AIController:
    DISCLAIMER = "Este resultado é apenas uma sugestão baseada em inteligência artificial e não substitui avaliação médica profissional."
    STORAGE_DIR = Path("storage") / "documents"

    def legacy_health(self):
        service = _get_prediction_service()
        health = service.health_check()
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "version": "1.0.0",
            **health,
        }), 200

    def legacy_predict(self):
        if "file" not in request.files:
            return jsonify({"error": "Nenhuma imagem foi fornecida", "code": "VALIDATION_ERROR"}), 400

        pred_req = PredictionRequest(
            image_file=request.files["file"],
            patient_id=request.form.get("patient_id"),
            metadata=request.form.to_dict(),
        )
        is_valid, error = pred_req.validate()
        if not is_valid:
            return jsonify({"error": error, "code": "VALIDATION_ERROR"}), 400

        try:
            service = _get_prediction_service()
            result = service.predict(pred_req)
            return jsonify(result.to_dict()), 200
        except APIException as exc:
            return jsonify({
                "error": exc.message,
                "code": exc.code.value if exc.code else "AI_UNAVAILABLE",
            }), exc.status_code

    @role_required("DOCTOR")
    def analyze(self):
        actor = User.query.get(int(get_jwt_identity()))
        if actor.role != RoleEnum.DOCTOR:
            return jsonify({"error": "Forbidden"}), 403
        dp = get_doctor_profile(actor)
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
        try:
            medical_record_id = int(medical_record_id)
            document_id = int(document_id) if document_id else None
        except (TypeError, ValueError):
            return jsonify({"error": "medical_record_id e document_id devem ser inteiros"}), 400

        mr = MedicalRecord.query.get(medical_record_id)
        if not mr or (actor.clinic_id is not None and mr.clinic_id != actor.clinic_id):
            return jsonify({"error": "Prontuário não encontrado"}), 404
        if not doctor_can_access_medical_record(actor, mr):
            return jsonify({"error": "Forbidden"}), 403

        doc = None
        image_file_handle = None

        try:
            if document_id:
                doc = Document.query.get(document_id)
                if not doc or doc.medical_record_id != mr.id or doc.clinic_id != mr.clinic_id:
                    return jsonify({"error": "Documento inválido"}), 404
                image_file_handle = open(doc.file_path, "rb")
                wrapped = type("F", (), {
                    "filename": doc.file_path.split('/')[-1],
                    "read": image_file_handle.read,
                    "seek": image_file_handle.seek,
                })()
                pred_req = PredictionRequest(image_file=wrapped, patient_id=str(mr.patient_id))
            elif 'file' in request.files:
                current_count = Document.query.filter_by(medical_record_id=mr.id).count()
                if current_count >= MAX_DOCUMENTS_PER_MEDICAL_RECORD:
                    return jsonify({"error": "Limite de 99 documentos atingido para este prontuário."}), 409
                file = request.files['file']
                # Salvar o arquivo como documento primeiro para persistir a análise
                self.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
                filename = secure_filename(file.filename)
                path = self.STORAGE_DIR / f"{mr.id}_{filename}"
                file.save(path)
                doc = Document(
                    clinic_id=actor.clinic_id or mr.clinic_id,
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
            if not service.is_model_loaded():
                return jsonify({"error": "Modelo de IA não está disponível. Contate o administrador."}), 503
            result = service.predict(pred_req)
        finally:
            if image_file_handle:
                image_file_handle.close()

        analysis = AIAnalysis(
            clinic_id=actor.clinic_id or mr.clinic_id,
            medical_record_id=mr.id,
            document_id=doc.id,
            ai_diagnosis=result.diagnosis,
            probability=result.probability,
            confidence_level=result.confidence_level,
            recommendation=result.recommendation,
            model_version=result.model_version,
            disclaimer=self.DISCLAIMER,
        )
        db.session.add(analysis)
        db.session.commit()
        return jsonify(serialize_ai_analysis(analysis, include_validation=False)), 201

    @role_required("DOCTOR")
    def validate(self, analysis_id):
        actor = User.query.get(int(get_jwt_identity()))
        if actor.role != RoleEnum.DOCTOR:
            return jsonify({"error": "Forbidden"}), 403
        dp = get_doctor_profile(actor)
        analysis = AIAnalysis.query.get(analysis_id)
        if not analysis or (actor.clinic_id is not None and analysis.clinic_id != actor.clinic_id):
            return jsonify({"error": "Not found"}), 404
        mr = MedicalRecord.query.get(analysis.medical_record_id)
        if not dp or not mr or not doctor_can_access_medical_record(actor, mr):
            return jsonify({"error": "Forbidden"}), 403
        data = get_json_body()
        if not data:
            return jsonify({"error": "Body JSON inválido ou vazio"}), 400
        try:
            if not data.get("doctor_agreement"):
                return jsonify({"error": "doctor_agreement e obrigatorio", "allowed_values": ["YES", "NO", "PARTIAL"]}), 400
            analysis.doctor_agreement = DoctorAgreementEnum(data.get("doctor_agreement"))
        except Exception:
            return jsonify({"error": "doctor_agreement invalido", "allowed_values": ["YES", "NO", "PARTIAL"]}), 400
        analysis.doctor_final_assessment = data.get("doctor_final_assessment")
        analysis.doctor_notes = data.get("doctor_notes")
        analysis.validated_at = _utcnow()
        db.session.commit()
        return jsonify(serialize_ai_analysis(analysis)), 200
