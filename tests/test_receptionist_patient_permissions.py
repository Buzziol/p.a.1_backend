from datetime import date, datetime

import sys

import pytest
from flask_jwt_extended import create_access_token

sys.path.insert(0, ".")

from src.api.app import create_app
from src.api.api_config import APIConfig
from src.api.database.extensions import db as _db
from src.api.models_db.models import (
    Appointment,
    AppointmentStatus,
    Clinic,
    DoctorProfile,
    MedicalRecord,
    Patient,
    RoleEnum,
    User,
)


@pytest.fixture(scope="module")
def app():
    cfg = APIConfig()
    cfg.DATABASE_URL = "sqlite:///:memory:"
    application = create_app(cfg)
    with application.app_context():
        _db.create_all()
        yield application
        _db.drop_all()


@pytest.fixture(autouse=True)
def db_session(app):
    with app.app_context():
        connection = _db.engine.connect()
        transaction = connection.begin()
        session = _db.session
        session.bind = connection

        yield session

        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(app):
    return app.test_client()


def _make_clinic(name):
    clinic = Clinic(name=name, is_active=True)
    _db.session.add(clinic)
    _db.session.flush()
    return clinic


def _make_user(email, role, clinic_id=None):
    user = User(
        clinic_id=clinic_id,
        name=email,
        email=email,
        role=role,
        is_active=True,
    )
    user.set_password("test123")
    _db.session.add(user)
    _db.session.flush()
    return user


def _make_doctor(email, clinic_id):
    user = _make_user(email, RoleEnum.DOCTOR, clinic_id)
    profile = DoctorProfile(user_id=user.id, crm=f"CRM-{user.id}", phone="11999999999")
    _db.session.add(profile)
    _db.session.flush()
    return user, profile


def _make_patient(clinic_id, cpf):
    patient = Patient(
        clinic_id=clinic_id,
        name=f"Patient {cpf}",
        cpf=cpf,
        address="Rua A, 1",
        cep="01234567",
        phone="11999999999",
        birth_date=date(1990, 1, 1),
        blood_type="O",
        email=f"patient_{cpf}@test.com",
        marital_status="single",
        is_active=True,
    )
    _db.session.add(patient)
    _db.session.flush()
    return patient


def _auth_header(app, user):
    with app.app_context():
        token = create_access_token(
            identity=str(user.id),
            additional_claims={"role": user.role.value, "clinic_id": user.clinic_id},
        )
    return {"Authorization": f"Bearer {token}"}


def test_receptionist_can_load_and_update_own_clinic_patient(client, app):
    clinic = _make_clinic("Reception Clinic")
    receptionist = _make_user("reception@test.com", RoleEnum.RECEPTIONIST, clinic.id)
    patient = _make_patient(clinic.id, "91000000001")

    headers = _auth_header(app, receptionist)

    list_response = client.get("/api/v1/patients", headers=headers)
    assert list_response.status_code == 200
    assert list_response.get_json()["total"] == 1

    get_response = client.get(f"/api/v1/patients/{patient.id}", headers=headers)
    assert get_response.status_code == 200
    assert get_response.get_json()["id"] == patient.id

    update_response = client.put(
        f"/api/v1/patients/{patient.id}",
        headers=headers,
        json={
            "name": "Updated Patient",
            "phone": "11888888888",
            "email": "updated@test.com",
            "address": "Rua B, 2",
            "birth_date": "1991-02-03",
        },
    )
    assert update_response.status_code == 200

    updated = Patient.query.get(patient.id)
    assert updated.name == "Updated Patient"
    assert updated.phone == "11888888888"
    assert updated.email == "updated@test.com"
    assert updated.address == "Rua B, 2"
    assert updated.birth_date == date(1991, 2, 3)


def test_receptionist_cannot_update_patient_from_another_clinic(client, app):
    own_clinic = _make_clinic("Own Reception Clinic")
    other_clinic = _make_clinic("Other Reception Clinic")
    receptionist = _make_user("scoped-reception@test.com", RoleEnum.RECEPTIONIST, own_clinic.id)
    other_patient = _make_patient(other_clinic.id, "91000000002")

    response = client.put(
        f"/api/v1/patients/{other_patient.id}",
        headers=_auth_header(app, receptionist),
        json={"name": "Should Not Update"},
    )

    assert response.status_code == 404
    assert Patient.query.get(other_patient.id).name != "Should Not Update"


def test_receptionist_remains_blocked_from_clinical_resources(client, app):
    clinic = _make_clinic("Clinical Block Clinic")
    receptionist = _make_user("blocked-reception@test.com", RoleEnum.RECEPTIONIST, clinic.id)
    doctor, doctor_profile = _make_doctor("clinical-doctor@test.com", clinic.id)
    patient = _make_patient(clinic.id, "91000000003")
    appointment = Appointment(
        clinic_id=clinic.id,
        patient_id=patient.id,
        doctor_profile_id=doctor_profile.id,
        scheduled_at=datetime(2026, 5, 28, 9, 0),
        status=AppointmentStatus.SCHEDULED,
        created_by=receptionist.id,
    )
    _db.session.add(appointment)
    _db.session.flush()
    record = MedicalRecord(
        clinic_id=clinic.id,
        patient_id=patient.id,
        doctor_profile_id=doctor_profile.id,
        appointment_id=appointment.id,
    )
    _db.session.add(record)
    _db.session.flush()

    headers = _auth_header(app, receptionist)

    responses = [
        client.get(f"/api/v1/patients/{patient.id}/medical-records", headers=headers),
        client.get("/api/v1/medical-records", headers=headers),
        client.get(f"/api/v1/medical-records/{record.id}", headers=headers),
        client.get(f"/api/v1/medical-records/{record.id}/ai-analyses", headers=headers),
        client.post("/api/v1/ai/analyze", headers=headers, json={"medical_record_id": record.id}),
        client.put("/api/v1/ai/1/validate", headers=headers, json={"doctor_agreement": "YES"}),
        client.post(
            "/api/v1/documents/upload",
            headers=headers,
            data={"medical_record_id": str(record.id)},
        ),
    ]

    assert all(response.status_code == 403 for response in responses)
    assert all(response.is_json for response in responses)
