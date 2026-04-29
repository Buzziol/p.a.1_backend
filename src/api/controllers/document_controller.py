from pathlib import Path
from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity
from werkzeug.utils import secure_filename
from ..decorators.auth import role_required
from ..database.extensions import db
from ..models_db.models import Document, MedicalRecord, User, RoleEnum, DoctorProfile


class DocumentController:
    STORAGE_DIR = Path("storage") / "documents"

    @role_required("DOCTOR")
    def upload(self):
        actor = User.query.get(int(get_jwt_identity()))
        dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
        if not dp:
            return jsonify({"error": "Doctor profile não encontrado"}), 400
        if 'file' not in request.files or 'medical_record_id' not in request.form:
            return jsonify({"error": "file e medical_record_id são obrigatórios"}), 400
        file = request.files['file']
        mr = MedicalRecord.query.get(int(request.form['medical_record_id']))
        if not mr or mr.clinic_id != actor.clinic_id:
            return jsonify({"error": "Prontuário não encontrado"}), 404
        if mr.doctor_profile_id != dp.id:
            return jsonify({"error": "Forbidden"}), 403
        self.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        filename = secure_filename(file.filename)
        path = self.STORAGE_DIR / f"{mr.id}_{filename}"
        file.save(path)
        doc = Document(clinic_id=actor.clinic_id, medical_record_id=mr.id, file_path=str(path), file_type=file.mimetype or "application/octet-stream")
        db.session.add(doc)
        db.session.commit()
        return jsonify({"id": doc.id, "file_path": doc.file_path}), 201
