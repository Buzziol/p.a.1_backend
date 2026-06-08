from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity
from ..decorators.auth import role_required
from ..models_db.models import Patient, User, RoleEnum, DoctorProfile, Appointment, Clinic, MedicalRecord
from ..database.extensions import db
from ..utils.request_utils import get_json_body
from ..utils.date_validation import parse_iso_date
from ..services.clinic_scope import doctor_can_access_patient, get_doctor_profile


def _resolve_clinic_id(actor, data=None):
    if actor.clinic_id is not None:
        return actor.clinic_id
    if data:
        cid = data.get("clinic_id")
        if cid:
            return int(cid)
    clinic = Clinic.query.filter_by(is_active=True).first()
    return clinic.id if clinic else None


HEALTH_INSURANCE_TEXT_FIELDS = [
    "health_insurance_name",
    "health_insurance_plan",
    "health_insurance_card_number",
    "health_insurance_notes",
]

PATIENT_PROFILE_TEXT_FIELDS = [
    "sex",
    "mother_name",
    "birthplace",
    "street",
    "address_number",
    "address_complement",
    "neighborhood",
    "city",
    "state",
]

ADDRESS_DETAIL_FIELDS = [
    "street",
    "address_number",
    "address_complement",
    "neighborhood",
    "city",
    "state",
]

STRUCTURED_ADDRESS_FIELDS = [
    *ADDRESS_DETAIL_FIELDS,
    "cep",
]


def _optional_text(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _text_or_empty(value):
    return _optional_text(value) or ""


def _has_structured_address_data(data):
    return any(_optional_text(data.get(field)) for field in STRUCTURED_ADDRESS_FIELDS)


def _has_address_detail_data(data):
    return any(_optional_text(data.get(field)) for field in ADDRESS_DETAIL_FIELDS)


def _compose_legacy_address(data):
    parts = []
    street = _optional_text(data.get("street"))
    number = _optional_text(data.get("address_number"))
    complement = _optional_text(data.get("address_complement"))
    neighborhood = _optional_text(data.get("neighborhood"))
    city = _optional_text(data.get("city"))
    state = _optional_text(data.get("state"))
    cep = _optional_text(data.get("cep"))

    if street and number:
        parts.append(f"{street}, {number}")
    elif street:
        parts.append(street)
    elif number:
        parts.append(number)
    if complement:
        parts.append(complement)
    if neighborhood:
        parts.append(neighborhood)

    city_state = " - ".join(part for part in [city, state] if part)
    if city_state:
        parts.append(city_state)
    if cep:
        parts.append(f"CEP {cep}")

    return ", ".join(parts)


def _patient_current_address_data(patient):
    return {
        "street": patient.street,
        "address_number": patient.address_number,
        "address_complement": patient.address_complement,
        "neighborhood": patient.neighborhood,
        "city": patient.city,
        "state": patient.state,
        "cep": patient.cep,
    }


def _apply_patient_profile_data(patient, data):
    for field in PATIENT_PROFILE_TEXT_FIELDS:
        if field in data:
            setattr(patient, field, _optional_text(data.get(field)))


def _apply_legacy_address(patient, data):
    if "address" in data:
        patient.address = _text_or_empty(data.get("address"))
        return

    if not _has_structured_address_data(data):
        return

    merged_data = _patient_current_address_data(patient)
    merged_data.update({field: data.get(field) for field in STRUCTURED_ADDRESS_FIELDS if field in data})
    composed_address = _compose_legacy_address(merged_data)
    if composed_address:
        patient.address = composed_address


def _parse_optional_date(value, field_name):
    return parse_iso_date(value, field_name)


def _parse_optional_bool(value, field_name):
    if isinstance(value, bool):
        return value, None
    return None, f"{field_name} deve ser boolean"


def _has_health_insurance_details(data):
    return any(_optional_text(data.get(field)) for field in HEALTH_INSURANCE_TEXT_FIELDS) or bool(
        data.get("health_insurance_valid_until")
    )


def _clear_health_insurance_details(patient):
    for field in HEALTH_INSURANCE_TEXT_FIELDS:
        setattr(patient, field, None)
    patient.health_insurance_valid_until = None


def _apply_health_insurance_data(patient, data):
    if "has_health_insurance" in data:
        parsed, error = _parse_optional_bool(data.get("has_health_insurance"), "has_health_insurance")
        if error:
            return error
        patient.has_health_insurance = parsed
    elif _has_health_insurance_details(data):
        patient.has_health_insurance = True

    if not patient.has_health_insurance:
        _clear_health_insurance_details(patient)
        return None

    for field in HEALTH_INSURANCE_TEXT_FIELDS:
        if field in data:
            setattr(patient, field, _optional_text(data.get(field)))
    if "health_insurance_valid_until" in data:
        parsed, error = _parse_optional_date(
            data.get("health_insurance_valid_until"),
            "health_insurance_valid_until",
        )
        if error:
            return error
        patient.health_insurance_valid_until = parsed
    return None


def _patient_health_insurance_payload(patient):
    return {
        "has_health_insurance": bool(patient.has_health_insurance),
        "health_insurance_name": patient.health_insurance_name or "",
        "health_insurance_plan": patient.health_insurance_plan or "",
        "health_insurance_card_number": patient.health_insurance_card_number or "",
        "health_insurance_valid_until": (
            patient.health_insurance_valid_until.isoformat()
            if patient.health_insurance_valid_until
            else None
        ),
        "health_insurance_notes": patient.health_insurance_notes or "",
    }


def _patient_detail_payload(patient):
    payload = {
        "id": patient.id,
        "clinic_id": patient.clinic_id,
        "name": patient.name,
        "cpf": patient.cpf,
        "address": patient.address,
        "cep": patient.cep,
        "phone": patient.phone,
        "sex": patient.sex,
        "mother_name": patient.mother_name,
        "birthplace": patient.birthplace,
        "street": patient.street,
        "address_number": patient.address_number,
        "address_complement": patient.address_complement,
        "neighborhood": patient.neighborhood,
        "city": patient.city,
        "state": patient.state,
        "birth_date": patient.birth_date.isoformat() if patient.birth_date else None,
        "blood_type": patient.blood_type,
        "email": patient.email,
        "marital_status": patient.marital_status,
        "is_active": patient.is_active,
    }
    payload.update(_patient_health_insurance_payload(patient))
    return payload


def _patient_list_payload(patient):
    payload = {
        "id": patient.id,
        "name": patient.name,
        "cpf": patient.cpf,
        "address": patient.address,
        "cep": patient.cep,
        "phone": patient.phone,
        "sex": patient.sex,
        "mother_name": patient.mother_name,
        "birthplace": patient.birthplace,
        "street": patient.street,
        "address_number": patient.address_number,
        "address_complement": patient.address_complement,
        "neighborhood": patient.neighborhood,
        "city": patient.city,
        "state": patient.state,
        "email": patient.email,
        "birth_date": patient.birth_date.isoformat() if patient.birth_date else None,
    }
    payload.update(_patient_health_insurance_payload(patient))
    return payload


class PatientController:
    @role_required("CLINIC_ADMIN", "RECEPTIONIST")
    def create_patient(self):
        actor = User.query.get(int(get_jwt_identity()))
        data = get_json_body()
        if not data:
            return jsonify({"error": "Body JSON inválido ou vazio"}), 400
        required = ["name", "cpf", "cep", "phone", "birth_date", "blood_type", "email", "marital_status"]
        missing = [k for k in required if not data.get(k)]
        address = _optional_text(data.get("address"))
        if not address and _has_address_detail_data(data):
            address = _compose_legacy_address(data)
        if not address:
            missing.append("address")
        if missing:
            return jsonify({"error": f"Campos obrigatórios ausentes: {', '.join(missing)}"}), 400
        clinic_id = _resolve_clinic_id(actor, data)
        if not clinic_id:
            return jsonify({"error": "Nenhuma clínica disponível"}), 400
        if Patient.query.filter_by(clinic_id=clinic_id, cpf=data["cpf"]).first():
            return jsonify({"error": "CPF já cadastrado nesta clínica"}), 409
        birth_date, error = parse_iso_date(data["birth_date"], "birth_date")
        if error:
            return jsonify({"error": error}), 400
        patient = Patient(
            clinic_id=clinic_id,
            name=data["name"],
            cpf=data["cpf"],
            address=address,
            cep=data["cep"],
            phone=data["phone"],
            birth_date=birth_date,
            blood_type=data["blood_type"],
            email=data["email"],
            marital_status=data["marital_status"],
            is_active=True,
        )
        _apply_patient_profile_data(patient, data)
        error = _apply_health_insurance_data(patient, data)
        if error:
            return jsonify({"error": error}), 400
        db.session.add(patient)
        db.session.commit()
        return jsonify(_patient_detail_payload(patient)), 201

    @role_required("CLINIC_ADMIN", "RECEPTIONIST", "DOCTOR")
    def list_patients(self):
        actor = User.query.get(int(get_jwt_identity()))
        q = Patient.query.filter_by(is_active=True)
        if actor.clinic_id is not None:
            q = q.filter_by(clinic_id=actor.clinic_id)
        if actor.role == RoleEnum.DOCTOR:
            dp = get_doctor_profile(actor)
            if not dp:
                return jsonify({"items": [], "total": 0, "page": 1, "pages": 0}), 200
            q = q.filter(
                db.or_(
                    db.exists().where(
                        db.and_(
                            Appointment.patient_id == Patient.id,
                            Appointment.doctor_profile_id == dp.id,
                            Appointment.clinic_id == Patient.clinic_id,
                        )
                    ),
                    db.exists().where(
                        db.and_(
                            MedicalRecord.patient_id == Patient.id,
                            MedicalRecord.doctor_profile_id == dp.id,
                            MedicalRecord.clinic_id == Patient.clinic_id,
                        )
                    ),
                    db.exists().where(
                        db.and_(
                            MedicalRecord.patient_id == Patient.id,
                            MedicalRecord.clinic_id == Patient.clinic_id,
                            Appointment.id == MedicalRecord.appointment_id,
                            Appointment.doctor_profile_id == dp.id,
                            Appointment.clinic_id == MedicalRecord.clinic_id,
                        )
                    ),
                )
            )
        search = request.args.get("search", "").strip()
        if search:
            q = q.filter(
                db.or_(
                    Patient.name.ilike(f"%{search}%"),
                    Patient.cpf.ilike(f"%{search}%"),
                    Patient.email.ilike(f"%{search}%"),
                )
            )
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        per_page = min(per_page, 100)
        pagination = q.order_by(Patient.name.asc()).paginate(page=page, per_page=per_page, error_out=False)
        return jsonify({
            "items": [_patient_list_payload(p) for p in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "pages": pagination.pages,
        }), 200

    @role_required("CLINIC_ADMIN", "RECEPTIONIST", "DOCTOR")
    def get_patient(self, patient_id):
        actor = User.query.get(int(get_jwt_identity()))
        p = Patient.query.get(patient_id)
        if not p or (actor.clinic_id is not None and p.clinic_id != actor.clinic_id):
            return jsonify({"error": "Not found"}), 404
        if actor.role == RoleEnum.DOCTOR and not doctor_can_access_patient(actor, p):
            return jsonify({"error": "Not found"}), 404
        return jsonify(_patient_detail_payload(p)), 200

    @role_required("CLINIC_ADMIN", "RECEPTIONIST")
    def update_patient(self, patient_id):
        actor = User.query.get(int(get_jwt_identity()))
        p = Patient.query.get(patient_id)
        if not p or (actor.clinic_id is not None and p.clinic_id != actor.clinic_id):
            return jsonify({"error": "Not found"}), 404
        data = get_json_body()
        if not data:
            return jsonify({"error": "Body JSON inválido ou vazio"}), 400
        for field in ["name", "cep", "phone", "blood_type", "email", "marital_status"]:
            if field in data:
                setattr(p, field, data[field])
        _apply_patient_profile_data(p, data)
        _apply_legacy_address(p, data)
        if "birth_date" in data:
            birth_date, error = parse_iso_date(data["birth_date"], "birth_date")
            if error:
                return jsonify({"error": error}), 400
            p.birth_date = birth_date
        error = _apply_health_insurance_data(p, data)
        if error:
            return jsonify({"error": error}), 400
        db.session.commit()
        return jsonify(_patient_detail_payload(p)), 200

    @role_required("CLINIC_ADMIN")
    def delete_patient(self, patient_id):
        actor = User.query.get(int(get_jwt_identity()))
        p = Patient.query.get(patient_id)
        if not p or (actor.clinic_id is not None and p.clinic_id != actor.clinic_id):
            return jsonify({"error": "Not found"}), 404
        p.is_active = False
        db.session.commit()
        return jsonify({"message": "Paciente desativado"}), 200

    @role_required("DOCTOR")
    def my_patients(self):
        """Retorna pacientes que possuem consultas com este médico."""
        actor = User.query.get(int(get_jwt_identity()))
        dp = DoctorProfile.query.filter_by(user_id=actor.id).first()
        if not dp:
            return jsonify([]), 200
        patient_ids = (
            db.session.query(Appointment.patient_id)
            .filter(
                Appointment.clinic_id == actor.clinic_id,
                Appointment.doctor_profile_id == dp.id,
            )
            .distinct()
            .subquery()
        )
        patients = Patient.query.filter(
            Patient.id.in_(patient_ids),
            Patient.is_active == True,
        ).order_by(Patient.name.asc()).all()
        return jsonify([{
            "id": p.id,
            "name": p.name,
            "cpf": p.cpf,
            "address": p.address,
            "cep": p.cep,
            "phone": p.phone,
            "sex": p.sex,
            "mother_name": p.mother_name,
            "birthplace": p.birthplace,
            "street": p.street,
            "address_number": p.address_number,
            "address_complement": p.address_complement,
            "neighborhood": p.neighborhood,
            "city": p.city,
            "state": p.state,
            "email": p.email,
        } for p in patients]), 200
