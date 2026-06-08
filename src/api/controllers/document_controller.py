import uuid
from pathlib import Path

from flask import jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity
from werkzeug.utils import secure_filename

from ..decorators.auth import role_required
from ..database.extensions import db
from ..models_db.models import Document, MedicalRecord, RoleEnum, User
from ..services.clinic_scope import doctor_can_access_medical_record


MAX_DOCUMENTS_PER_MEDICAL_RECORD = 99
DEFAULT_DOCUMENT_CATEGORY = "OTHER_DOCUMENT"
ALLOWED_DOCUMENT_CATEGORIES = {"LESION_IMAGE", DEFAULT_DOCUMENT_CATEGORY}


def _document_download_url(document_id):
    return f"/api/v1/documents/{document_id}/download"


def serialize_document(document):
    path = Path(document.file_path) if document.file_path else Path("")
    return {
        "id": document.id,
        "medical_record_id": document.medical_record_id,
        "file_name": path.name,
        "file_type": document.file_type,
        "document_category": document.document_category or DEFAULT_DOCUMENT_CATEGORY,
        "uploaded_at": document.uploaded_at.isoformat() + "Z" if document.uploaded_at else None,
        "download_url": _document_download_url(document.id),
    }


class DocumentController:
    STORAGE_DIR = Path("storage") / "documents"

    def _get_actor(self):
        return User.query.get(int(get_jwt_identity()))

    def _can_access_record(self, actor, medical_record):
        if not actor or not medical_record:
            return False
        if actor.role != RoleEnum.SUPER_ADMIN and actor.clinic_id is not None and medical_record.clinic_id != actor.clinic_id:
            return False
        if actor.role == RoleEnum.DOCTOR:
            return doctor_can_access_medical_record(actor, medical_record)
        return True

    def _get_authorized_record(self, medical_record_id):
        actor = self._get_actor()
        try:
            medical_record_id = int(medical_record_id)
        except (TypeError, ValueError):
            return actor, None, (jsonify({"error": "medical_record_id deve ser inteiro"}), 400)
        medical_record = MedicalRecord.query.get(medical_record_id)
        if not medical_record or (
            actor.role != RoleEnum.SUPER_ADMIN
            and actor.clinic_id is not None
            and medical_record.clinic_id != actor.clinic_id
        ):
            return actor, None, (jsonify({"error": "Prontuário não encontrado"}), 404)
        if not self._can_access_record(actor, medical_record):
            return actor, None, (jsonify({"error": "Forbidden"}), 403)
        return actor, medical_record, None

    def _get_authorized_document(self, document_id):
        actor = self._get_actor()
        document = Document.query.get(document_id)
        if not document:
            return actor, None, None, (jsonify({"error": "Documento não encontrado"}), 404)
        medical_record = MedicalRecord.query.get(document.medical_record_id)
        if not medical_record or (
            actor.role != RoleEnum.SUPER_ADMIN
            and actor.clinic_id is not None
            and document.clinic_id != actor.clinic_id
        ):
            return actor, None, None, (jsonify({"error": "Documento não encontrado"}), 404)
        if not self._can_access_record(actor, medical_record):
            return actor, None, None, (jsonify({"error": "Forbidden"}), 403)
        return actor, document, medical_record, None

    def _safe_document_path(self, document):
        if not document.file_path:
            return None
        storage_root = self.STORAGE_DIR.resolve()
        document_path = Path(document.file_path).resolve()
        try:
            document_path.relative_to(storage_root)
        except ValueError:
            return None
        return document_path

    @role_required("DOCTOR", "CLINIC_ADMIN")
    def upload(self):
        if "file" not in request.files or "medical_record_id" not in request.form:
            return jsonify({"error": "file e medical_record_id são obrigatórios"}), 400
        file = request.files["file"]
        if not file or not file.filename:
            return jsonify({"error": "Arquivo inválido"}), 400

        document_category = request.form.get("document_category") or DEFAULT_DOCUMENT_CATEGORY
        if document_category not in ALLOWED_DOCUMENT_CATEGORIES:
            return jsonify({
                "error": "document_category inválido",
                "allowed_values": sorted(ALLOWED_DOCUMENT_CATEGORIES),
            }), 400

        actor, medical_record, error = self._get_authorized_record(request.form.get("medical_record_id"))
        if error:
            return error

        current_count = Document.query.filter_by(medical_record_id=medical_record.id).count()
        if current_count >= MAX_DOCUMENTS_PER_MEDICAL_RECORD:
            return jsonify({"error": "Limite de 99 documentos atingido para este prontuário."}), 409

        self.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        original_filename = secure_filename(file.filename)
        if not original_filename:
            return jsonify({"error": "Arquivo inválido"}), 400
        filename = f"{medical_record.id}_{uuid.uuid4().hex}_{original_filename}"
        path = self.STORAGE_DIR / filename
        file.save(path)

        document = Document(
            clinic_id=medical_record.clinic_id if actor.role == RoleEnum.SUPER_ADMIN else (actor.clinic_id or medical_record.clinic_id),
            medical_record_id=medical_record.id,
            file_path=str(path),
            file_type=file.mimetype or "application/octet-stream",
            document_category=document_category,
        )
        db.session.add(document)
        db.session.commit()
        return jsonify(serialize_document(document)), 201

    @role_required("DOCTOR", "CLINIC_ADMIN")
    def list_by_medical_record(self, medical_record_id):
        actor, medical_record, error = self._get_authorized_record(medical_record_id)
        if error:
            return error
        documents = (
            Document.query
            .filter_by(clinic_id=medical_record.clinic_id, medical_record_id=medical_record.id)
            .order_by(Document.uploaded_at.desc(), Document.id.desc())
            .all()
        )
        return jsonify([serialize_document(document) for document in documents]), 200

    @role_required("DOCTOR", "CLINIC_ADMIN")
    def download(self, document_id):
        _actor, document, _medical_record, error = self._get_authorized_document(document_id)
        if error:
            return error
        path = self._safe_document_path(document)
        if not path or not path.is_file():
            return jsonify({"error": "Arquivo não encontrado"}), 404
        return send_file(
            path,
            mimetype=document.file_type or "application/octet-stream",
            as_attachment=True,
            download_name=path.name,
        )

    @role_required("DOCTOR", "CLINIC_ADMIN")
    def delete(self, document_id):
        _actor, document, _medical_record, error = self._get_authorized_document(document_id)
        if error:
            return error
        db.session.delete(document)
        db.session.commit()
        return jsonify({"id": document_id}), 200
