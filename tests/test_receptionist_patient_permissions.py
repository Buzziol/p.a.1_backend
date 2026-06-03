import io
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
    AIAnalysis,
    Clinic,
    Document,
    DoctorProfile,
    MedicalRecord,
    Patient,
    RoleEnum,
    ScheduleBlock,
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

    create_response = client.post(
        "/api/v1/patients",
        headers=headers,
        json={
            "name": "Insurance Patient",
            "cpf": "91000000004",
            "address": "Rua Conv, 10",
            "cep": "01234567",
            "phone": "11777777777",
            "sex": "F",
            "mother_name": "Maria Insurance",
            "birthplace": "Sao Paulo",
            "street": "Rua Conv",
            "address_number": "10",
            "address_complement": "Sala 2",
            "neighborhood": "Centro",
            "city": "Sao Paulo",
            "state": "SP",
            "birth_date": "1995-05-06",
            "blood_type": "A",
            "email": "insurance@test.com",
            "marital_status": "single",
            "health_insurance_name": "Amil",
            "health_insurance_plan": "Amil 400",
            "health_insurance_card_number": "CARD-123",
            "health_insurance_valid_until": "2027-12-31",
            "health_insurance_notes": "Autorizacao previa para procedimentos.",
        },
    )
    assert create_response.status_code == 201
    created_payload = create_response.get_json()
    assert created_payload["clinic_id"] == clinic.id
    assert created_payload["sex"] == "F"
    assert created_payload["mother_name"] == "Maria Insurance"
    assert created_payload["birthplace"] == "Sao Paulo"
    assert created_payload["street"] == "Rua Conv"
    assert created_payload["address_number"] == "10"
    assert created_payload["address_complement"] == "Sala 2"
    assert created_payload["neighborhood"] == "Centro"
    assert created_payload["city"] == "Sao Paulo"
    assert created_payload["state"] == "SP"
    assert created_payload["has_health_insurance"] is True
    assert created_payload["health_insurance_name"] == "Amil"
    assert created_payload["health_insurance_valid_until"] == "2027-12-31"

    no_insurance_response = client.post(
        "/api/v1/patients",
        headers=headers,
        json={
            "name": "No Insurance Patient",
            "cpf": "91000000006",
            "address": "Rua Sem Convenio, 10",
            "cep": "01234567",
            "phone": "11777777776",
            "birth_date": "1996-05-06",
            "blood_type": "B",
            "email": "no-insurance@test.com",
            "marital_status": "single",
            "has_health_insurance": False,
            "health_insurance_name": "Should be cleared",
            "health_insurance_plan": "Should be cleared",
            "health_insurance_card_number": "CLEAR-123",
            "health_insurance_valid_until": "2027-12-31",
            "health_insurance_notes": "Should be cleared",
        },
    )
    assert no_insurance_response.status_code == 201
    no_insurance_payload = no_insurance_response.get_json()
    assert no_insurance_payload["has_health_insurance"] is False
    assert no_insurance_payload["health_insurance_name"] == ""
    assert no_insurance_payload["health_insurance_plan"] == ""
    assert no_insurance_payload["health_insurance_card_number"] == ""
    assert no_insurance_payload["health_insurance_valid_until"] is None
    assert no_insurance_payload["health_insurance_notes"] == ""

    structured_address_response = client.post(
        "/api/v1/patients",
        headers=headers,
        json={
            "name": "Structured Address Patient",
            "cpf": "91000000008",
            "cep": "04567000",
            "phone": "11777777778",
            "sex": "M",
            "mother_name": "Ana Structured",
            "birthplace": "Campinas",
            "street": "Rua Estruturada",
            "address_number": "123",
            "address_complement": "",
            "neighborhood": "Jardins",
            "city": "Sao Paulo",
            "state": "SP",
            "birth_date": "1997-05-06",
            "blood_type": "AB",
            "email": "structured@test.com",
            "marital_status": "single",
        },
    )
    assert structured_address_response.status_code == 201
    structured_payload = structured_address_response.get_json()
    assert structured_payload["address"] == "Rua Estruturada, 123, Jardins, Sao Paulo - SP, CEP 04567000"
    assert structured_payload["address_complement"] is None

    list_response = client.get("/api/v1/patients", headers=headers)
    assert list_response.status_code == 200
    list_payload = list_response.get_json()
    assert list_payload["total"] == 4
    created_list_item = next(item for item in list_payload["items"] if item["id"] == created_payload["id"])
    assert created_list_item["sex"] == "F"
    assert created_list_item["mother_name"] == "Maria Insurance"
    assert created_list_item["street"] == "Rua Conv"
    assert created_list_item["city"] == "Sao Paulo"
    assert created_list_item["has_health_insurance"] is True
    assert created_list_item["health_insurance_plan"] == "Amil 400"

    get_response = client.get(f"/api/v1/patients/{patient.id}", headers=headers)
    assert get_response.status_code == 200
    get_payload = get_response.get_json()
    assert get_payload["id"] == patient.id
    assert get_payload["has_health_insurance"] is False
    assert get_payload["health_insurance_name"] == ""
    assert get_payload["health_insurance_valid_until"] is None

    update_response = client.put(
        f"/api/v1/patients/{patient.id}",
        headers=headers,
        json={
            "name": "Updated Patient",
            "phone": "11888888888",
            "email": "updated@test.com",
            "address": "Rua B, 2",
            "sex": "M",
            "mother_name": "Mother Updated",
            "birthplace": "Rio de Janeiro",
            "street": "Rua B",
            "address_number": "2",
            "address_complement": "Casa",
            "neighborhood": "Bairro B",
            "city": "Rio de Janeiro",
            "state": "RJ",
            "birth_date": "1991-02-03",
            "health_insurance_name": "SulAmerica",
            "health_insurance_plan": "Especial",
            "health_insurance_card_number": "CARD-999",
            "health_insurance_valid_until": "2028-01-31",
            "health_insurance_notes": "Paciente titular.",
        },
    )
    assert update_response.status_code == 200
    update_payload = update_response.get_json()
    assert update_payload["sex"] == "M"
    assert update_payload["mother_name"] == "Mother Updated"
    assert update_payload["birthplace"] == "Rio de Janeiro"
    assert update_payload["street"] == "Rua B"
    assert update_payload["address_number"] == "2"
    assert update_payload["address_complement"] == "Casa"
    assert update_payload["neighborhood"] == "Bairro B"
    assert update_payload["city"] == "Rio de Janeiro"
    assert update_payload["state"] == "RJ"
    assert update_payload["has_health_insurance"] is True
    assert update_payload["health_insurance_name"] == "SulAmerica"
    assert update_payload["health_insurance_valid_until"] == "2028-01-31"

    updated = Patient.query.get(patient.id)
    assert updated.name == "Updated Patient"
    assert updated.phone == "11888888888"
    assert updated.email == "updated@test.com"
    assert updated.address == "Rua B, 2"
    assert updated.sex == "M"
    assert updated.mother_name == "Mother Updated"
    assert updated.birthplace == "Rio de Janeiro"
    assert updated.street == "Rua B"
    assert updated.address_number == "2"
    assert updated.address_complement == "Casa"
    assert updated.neighborhood == "Bairro B"
    assert updated.city == "Rio de Janeiro"
    assert updated.state == "RJ"
    assert updated.birth_date == date(1991, 2, 3)
    assert updated.health_insurance_name == "SulAmerica"
    assert updated.health_insurance_plan == "Especial"
    assert updated.health_insurance_card_number == "CARD-999"
    assert updated.health_insurance_valid_until == date(2028, 1, 31)
    assert updated.health_insurance_notes == "Paciente titular."

    clear_response = client.put(
        f"/api/v1/patients/{patient.id}",
        headers=headers,
        json={
            "has_health_insurance": False,
            "health_insurance_name": "Should Not Stay",
            "health_insurance_valid_until": "2029-01-31",
        },
    )
    assert clear_response.status_code == 200
    clear_payload = clear_response.get_json()
    assert clear_payload["has_health_insurance"] is False
    assert clear_payload["health_insurance_name"] == ""
    assert clear_payload["health_insurance_valid_until"] is None
    assert updated.health_insurance_name is None
    assert updated.health_insurance_plan is None
    assert updated.health_insurance_card_number is None
    assert updated.health_insurance_valid_until is None
    assert updated.health_insurance_notes is None

    reactivate_response = client.put(
        f"/api/v1/patients/{patient.id}",
        headers=headers,
        json={
            "has_health_insurance": True,
            "health_insurance_name": "Bradesco",
            "health_insurance_plan": "Top",
        },
    )
    assert reactivate_response.status_code == 200
    reactivate_payload = reactivate_response.get_json()
    assert reactivate_payload["has_health_insurance"] is True
    assert reactivate_payload["health_insurance_name"] == "Bradesco"
    assert reactivate_payload["health_insurance_plan"] == "Top"

    address_update_response = client.put(
        f"/api/v1/patients/{patient.id}",
        headers=headers,
        json={
            "street": "Rua Nova",
            "address_number": "55",
            "address_complement": None,
            "neighborhood": "Novo Bairro",
            "city": "Curitiba",
            "state": "PR",
            "cep": "80000000",
        },
    )
    assert address_update_response.status_code == 200
    address_update_payload = address_update_response.get_json()
    assert address_update_payload["address"] == "Rua Nova, 55, Novo Bairro, Curitiba - PR, CEP 80000000"
    assert address_update_payload["cep"] == "80000000"


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


def test_patient_health_insurance_valid_until_must_be_iso_date(client, app):
    clinic = _make_clinic("Validation Clinic")
    receptionist = _make_user("validation-reception@test.com", RoleEnum.RECEPTIONIST, clinic.id)

    response = client.post(
        "/api/v1/patients",
        headers=_auth_header(app, receptionist),
        json={
            "name": "Invalid Date Patient",
            "cpf": "91000000005",
            "address": "Rua Validacao, 1",
            "cep": "01234567",
            "phone": "11666666666",
            "birth_date": "1992-03-04",
            "blood_type": "B",
            "email": "invalid-date@test.com",
            "marital_status": "single",
            "health_insurance_valid_until": "31/12/2027",
        },
    )

    assert response.status_code == 400
    assert "health_insurance_valid_until" in response.get_json()["error"]

    invalid_bool_response = client.post(
        "/api/v1/patients",
        headers=_auth_header(app, receptionist),
        json={
            "name": "Invalid Bool Patient",
            "cpf": "91000000007",
            "address": "Rua Validacao, 2",
            "cep": "01234567",
            "phone": "11666666667",
            "birth_date": "1992-03-04",
            "blood_type": "B",
            "email": "invalid-bool@test.com",
            "marital_status": "single",
            "has_health_insurance": "false",
        },
    )

    assert invalid_bool_response.status_code == 400
    assert "has_health_insurance" in invalid_bool_response.get_json()["error"]


def test_doctor_only_accesses_patients_linked_by_appointments(client, app):
    clinic = _make_clinic("Doctor Scope Clinic")
    receptionist = _make_user("scope-reception@test.com", RoleEnum.RECEPTIONIST, clinic.id)
    doctor_a, profile_a = _make_doctor("doctor-a@test.com", clinic.id)
    doctor_b, profile_b = _make_doctor("doctor-b@test.com", clinic.id)
    patient_past = _make_patient(clinic.id, "92000000001")
    patient_future = _make_patient(clinic.id, "92000000002")
    patient_other_doctor = _make_patient(clinic.id, "92000000003")
    patient_without_appointment = _make_patient(clinic.id, "92000000004")
    patient_future.sex = "F"
    patient_future.mother_name = "Mae do Paciente"
    patient_future.birthplace = "Sao Paulo"
    patient_future.street = "Rua Medico"
    patient_future.address_number = "123"
    patient_future.address_complement = "Apto 9"
    patient_future.neighborhood = "Centro"
    patient_future.city = "Sao Paulo"
    patient_future.state = "SP"
    patient_future.has_health_insurance = True
    patient_future.health_insurance_name = "Amil"
    patient_future.health_insurance_plan = "Amil 400"
    patient_future.health_insurance_card_number = "CARD-DOCTOR"
    patient_future.health_insurance_valid_until = date(2027, 12, 31)
    patient_future.health_insurance_notes = "Cadastro visivel para medico."

    appointments = [
        Appointment(
            clinic_id=clinic.id,
            patient_id=patient_past.id,
            doctor_profile_id=profile_a.id,
            scheduled_at=datetime(2026, 5, 28, 9, 0),
            status=AppointmentStatus.COMPLETED,
            created_by=receptionist.id,
        ),
        Appointment(
            clinic_id=clinic.id,
            patient_id=patient_future.id,
            doctor_profile_id=profile_a.id,
            scheduled_at=datetime(2026, 5, 30, 9, 0),
            status=AppointmentStatus.SCHEDULED,
            created_by=receptionist.id,
        ),
        Appointment(
            clinic_id=clinic.id,
            patient_id=patient_other_doctor.id,
            doctor_profile_id=profile_b.id,
            scheduled_at=datetime(2026, 5, 29, 9, 0),
            status=AppointmentStatus.CONFIRMED,
            created_by=receptionist.id,
        ),
    ]
    _db.session.add_all(appointments)
    _db.session.flush()

    other_record = MedicalRecord(
        clinic_id=clinic.id,
        patient_id=patient_other_doctor.id,
        doctor_profile_id=profile_b.id,
        appointment_id=appointments[2].id,
    )
    _db.session.add(other_record)
    _db.session.flush()

    headers = _auth_header(app, doctor_a)

    list_response = client.get("/api/v1/patients", headers=headers)
    assert list_response.status_code == 200
    listed_ids = {item["id"] for item in list_response.get_json()["items"]}
    assert patient_past.id in listed_ids
    assert patient_future.id in listed_ids
    assert patient_other_doctor.id not in listed_ids
    assert patient_without_appointment.id not in listed_ids

    own_detail = client.get(f"/api/v1/patients/{patient_future.id}", headers=headers)
    assert own_detail.status_code == 200
    own_detail_payload = own_detail.get_json()
    assert own_detail_payload["id"] == patient_future.id
    assert own_detail_payload["name"] == patient_future.name
    assert own_detail_payload["cpf"] == patient_future.cpf
    assert own_detail_payload["birth_date"] == "1990-01-01"
    assert own_detail_payload["sex"] == "F"
    assert own_detail_payload["mother_name"] == "Mae do Paciente"
    assert own_detail_payload["birthplace"] == "Sao Paulo"
    assert own_detail_payload["blood_type"] == "O"
    assert own_detail_payload["marital_status"] == "single"
    assert own_detail_payload["email"] == patient_future.email
    assert own_detail_payload["phone"] == patient_future.phone
    assert own_detail_payload["address"] == patient_future.address
    assert own_detail_payload["street"] == "Rua Medico"
    assert own_detail_payload["address_number"] == "123"
    assert own_detail_payload["address_complement"] == "Apto 9"
    assert own_detail_payload["neighborhood"] == "Centro"
    assert own_detail_payload["city"] == "Sao Paulo"
    assert own_detail_payload["state"] == "SP"
    assert own_detail_payload["cep"] == patient_future.cep
    assert own_detail_payload["has_health_insurance"] is True
    assert own_detail_payload["health_insurance_name"] == "Amil"
    assert own_detail_payload["health_insurance_plan"] == "Amil 400"
    assert own_detail_payload["health_insurance_card_number"] == "CARD-DOCTOR"
    assert own_detail_payload["health_insurance_valid_until"] == "2027-12-31"
    assert own_detail_payload["health_insurance_notes"] == "Cadastro visivel para medico."

    update_as_doctor = client.put(
        f"/api/v1/patients/{patient_future.id}",
        headers=headers,
        json={"name": "Doctor Should Not Edit"},
    )
    patch_as_doctor = client.patch(
        f"/api/v1/patients/{patient_future.id}",
        headers=headers,
        json={"phone": "11000000000"},
    )
    delete_as_doctor = client.delete(f"/api/v1/patients/{patient_future.id}", headers=headers)
    assert update_as_doctor.status_code == 403
    assert patch_as_doctor.status_code == 403
    assert delete_as_doctor.status_code == 403
    assert Patient.query.get(patient_future.id).name != "Doctor Should Not Edit"
    assert Patient.query.get(patient_future.id).phone != "11000000000"

    other_detail = client.get(f"/api/v1/patients/{patient_other_doctor.id}", headers=headers)
    assert other_detail.status_code == 404

    no_appointment_detail = client.get(f"/api/v1/patients/{patient_without_appointment.id}", headers=headers)
    assert no_appointment_detail.status_code == 404

    create_other_record = client.post(
        "/api/v1/medical-records",
        headers=headers,
        json={
            "patient_id": patient_other_doctor.id,
            "appointment_id": appointments[2].id,
            "diagnosis": "Should not be created",
        },
    )
    assert create_other_record.status_code == 404

    other_record_responses = [
        client.get(f"/api/v1/patients/{patient_other_doctor.id}/medical-records", headers=headers),
        client.get(f"/api/v1/medical-records/{other_record.id}", headers=headers),
        client.put(
            f"/api/v1/medical-records/{other_record.id}",
            headers=headers,
            json={"diagnosis": "Should not update"},
        ),
        client.get(f"/api/v1/medical-records/{other_record.id}/ai-analyses", headers=headers),
        client.post("/api/v1/ai/analyze", headers=headers, json={"medical_record_id": other_record.id}),
        client.post(
            "/api/v1/documents/upload",
            headers=headers,
            data={
                "medical_record_id": str(other_record.id),
                "file": (io.BytesIO(b"fake image"), "lesion.jpg"),
            },
            content_type="multipart/form-data",
        ),
    ]
    assert [response.status_code for response in other_record_responses] == [404, 403, 403, 403, 403, 403]


def test_doctor_can_access_record_through_record_or_linked_appointment(client, app):
    clinic = _make_clinic("Medical Record Scope Clinic")
    receptionist = _make_user("record-scope-reception@test.com", RoleEnum.RECEPTIONIST, clinic.id)
    doctor_a, profile_a = _make_doctor("record-scope-doctor-a@test.com", clinic.id)
    doctor_b, profile_b = _make_doctor("record-scope-doctor-b@test.com", clinic.id)

    patient_by_record = _make_patient(clinic.id, "94000000001")
    patient_by_linked_appointment = _make_patient(clinic.id, "94000000002")
    patient_without_link = _make_patient(clinic.id, "94000000003")

    appointment_other_doctor = Appointment(
        clinic_id=clinic.id,
        patient_id=patient_by_record.id,
        doctor_profile_id=profile_b.id,
        scheduled_at=datetime(2026, 6, 1, 9, 0),
        status=AppointmentStatus.COMPLETED,
        created_by=receptionist.id,
    )
    appointment_for_doctor = Appointment(
        clinic_id=clinic.id,
        patient_id=patient_by_linked_appointment.id,
        doctor_profile_id=profile_a.id,
        scheduled_at=datetime(2026, 6, 2, 9, 0),
        status=AppointmentStatus.SCHEDULED,
        created_by=receptionist.id,
    )
    appointment_unlinked = Appointment(
        clinic_id=clinic.id,
        patient_id=patient_without_link.id,
        doctor_profile_id=profile_b.id,
        scheduled_at=datetime(2026, 6, 3, 9, 0),
        status=AppointmentStatus.CONFIRMED,
        created_by=receptionist.id,
    )
    _db.session.add_all([appointment_other_doctor, appointment_for_doctor, appointment_unlinked])
    _db.session.flush()

    record_created_by_doctor = MedicalRecord(
        clinic_id=clinic.id,
        patient_id=patient_by_record.id,
        doctor_profile_id=profile_a.id,
        appointment_id=appointment_other_doctor.id,
        diagnosis="Created by doctor A",
    )
    record_linked_to_doctor_appointment = MedicalRecord(
        clinic_id=clinic.id,
        patient_id=patient_by_linked_appointment.id,
        doctor_profile_id=profile_b.id,
        appointment_id=appointment_for_doctor.id,
        diagnosis="Linked to doctor A appointment",
    )
    record_without_link = MedicalRecord(
        clinic_id=clinic.id,
        patient_id=patient_without_link.id,
        doctor_profile_id=profile_b.id,
        appointment_id=appointment_unlinked.id,
        diagnosis="Not linked to doctor A",
    )
    _db.session.add_all([
        record_created_by_doctor,
        record_linked_to_doctor_appointment,
        record_without_link,
    ])
    _db.session.flush()

    headers = _auth_header(app, doctor_a)

    by_record_response = client.get(f"/api/v1/medical-records/{record_created_by_doctor.id}", headers=headers)
    linked_appointment_response = client.get(
        f"/api/v1/medical-records/{record_linked_to_doctor_appointment.id}",
        headers=headers,
    )
    blocked_response = client.get(f"/api/v1/medical-records/{record_without_link.id}", headers=headers)

    assert by_record_response.status_code == 200
    assert linked_appointment_response.status_code == 200
    assert blocked_response.status_code == 403

    patient_records_response = client.get(
        f"/api/v1/patients/{patient_by_record.id}/medical-records",
        headers=headers,
    )
    assert patient_records_response.status_code == 200
    listed_record_ids = {item["id"] for item in patient_records_response.get_json()}
    assert record_created_by_doctor.id in listed_record_ids

    list_response = client.get("/api/v1/patients", headers=headers)
    listed_patient_ids = {item["id"] for item in list_response.get_json()["items"]}
    assert patient_by_record.id in listed_patient_ids
    assert patient_by_linked_appointment.id in listed_patient_ids
    assert patient_without_link.id not in listed_patient_ids


def test_appointments_list_supports_cors_and_role_scoping(client, app):
    clinic = _make_clinic("Appointment CORS Clinic")
    other_clinic = _make_clinic("Other Appointment CORS Clinic")
    receptionist = _make_user("appointment-reception@test.com", RoleEnum.RECEPTIONIST, clinic.id)
    clinic_admin = _make_user("appointment-admin@test.com", RoleEnum.CLINIC_ADMIN, clinic.id)
    super_admin = _make_user("appointment-super@test.com", RoleEnum.SUPER_ADMIN)
    doctor_a, profile_a = _make_doctor("appointment-doctor-a@test.com", clinic.id)
    doctor_b, profile_b = _make_doctor("appointment-doctor-b@test.com", clinic.id)
    patient_a = _make_patient(clinic.id, "93000000001")
    patient_b = _make_patient(clinic.id, "93000000002")
    patient_other = _make_patient(other_clinic.id, "93000000003")

    appointments = [
        Appointment(
            clinic_id=clinic.id,
            patient_id=patient_a.id,
            doctor_profile_id=profile_a.id,
            scheduled_at=datetime(2026, 6, 2, 9, 0),
            status=AppointmentStatus.SCHEDULED,
            created_by=receptionist.id,
        ),
        Appointment(
            clinic_id=clinic.id,
            patient_id=patient_b.id,
            doctor_profile_id=profile_b.id,
            scheduled_at=datetime(2026, 6, 2, 10, 0),
            status=AppointmentStatus.CONFIRMED,
            created_by=receptionist.id,
        ),
        Appointment(
            clinic_id=other_clinic.id,
            patient_id=patient_other.id,
            doctor_profile_id=profile_a.id,
            scheduled_at=datetime(2026, 6, 2, 11, 0),
            status=AppointmentStatus.SCHEDULED,
            created_by=receptionist.id,
        ),
    ]
    _db.session.add_all(appointments)
    _db.session.flush()

    origin_headers = {
        "Origin": "http://localhost:8080",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "Authorization",
    }
    options_response = client.open("/api/v1/appointments", method="OPTIONS", headers=origin_headers)
    assert options_response.status_code in (200, 204)
    assert options_response.headers["Access-Control-Allow-Origin"] == "http://localhost:8080"

    unauthenticated = client.get("/api/v1/appointments", headers={"Origin": "http://localhost:8080"})
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["Access-Control-Allow-Origin"] == "http://localhost:8080"

    role_expectations = [
        (receptionist, {appointments[0].id, appointments[1].id}),
        (clinic_admin, {appointments[0].id, appointments[1].id}),
        (doctor_a, {appointments[0].id}),
        (super_admin, {appointments[0].id, appointments[1].id, appointments[2].id}),
    ]

    for user, expected_ids in role_expectations:
        response = client.get(
            "/api/v1/appointments",
            headers={**_auth_header(app, user), "Origin": "http://localhost:8080"},
        )
        assert response.status_code == 200
        assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:8080"
        assert {item["id"] for item in response.get_json()} == expected_ids


def test_medical_record_contract_uses_canonical_clinical_fields(client, app):
    clinic = _make_clinic("Medical Record Contract Clinic")
    receptionist = _make_user("record-contract-reception@test.com", RoleEnum.RECEPTIONIST, clinic.id)
    clinic_admin = _make_user("record-contract-admin@test.com", RoleEnum.CLINIC_ADMIN, clinic.id)
    doctor, profile = _make_doctor("record-contract-doctor@test.com", clinic.id)
    patient = _make_patient(clinic.id, "95000000001")
    appointment = Appointment(
        clinic_id=clinic.id,
        patient_id=patient.id,
        doctor_profile_id=profile.id,
        scheduled_at=datetime(2026, 6, 4, 9, 0),
        status=AppointmentStatus.SCHEDULED,
        created_by=receptionist.id,
    )
    _db.session.add(appointment)
    _db.session.flush()

    headers = _auth_header(app, doctor)
    create_response = client.post(
        "/api/v1/medical-records",
        headers=headers,
        json={
            "patient_id": patient.id,
            "appointment_id": appointment.id,
            "anamnesis": "Patient history",
            "physical_exam": "Skin exam",
            "diagnostic_hypothesis": "Nevus",
            "diagnosis": "Benign lesion",
            "conduct": "Follow-up",
            "prescriptions": "Sunscreen",
            "exams_requested": "Dermoscopy",
            "evolution": "Stable",
            "consultation_type": "Lesion assessment",
            "chief_complaint": "Lesao pigmentada",
            "problem_onset": "3 dias",
            "clinical_evolution": "Crescimento progressivo",
            "associated_symptoms": ["Coceira", "Sangramento"],
            "symptom_other": None,
            "had_previous_treatment": True,
            "previous_treatments": "Pomada topica",
            "has_skin_cancer_history": True,
            "skin_cancer_history_description": "Pai com melanoma",
            "frequent_sun_exposure": True,
            "sunscreen_use": "Irregular",
            "skin_phototype": "III — Morena clara",
            "lesion_location": "Dorso",
            "lesion_description": "Papula pigmentada assimetrica",
            "has_measurable_lesion": True,
            "lesion_size": "8",
            "lesion_size_unit": "mm",
            "lesion_color": "Múltiplas cores",
            "lesion_borders": "Irregulares",
            "lesion_symptoms": ["Coceira"],
            "wants_image_attachment": True,
            "image_attachment_notes": "Imagem enviada pelo fluxo de documentos",
            "has_suspicious_lesion": True,
            "asymmetry": True,
            "irregular_borders": True,
            "varied_color": True,
            "diameter_greater_than_6mm": True,
            "recent_evolution_change": True,
            "suspicion_level": "Alto",
            "has_requested_exams": True,
            "has_prescription": True,
            "needs_follow_up": True,
            "suggested_return_date": "2026-07-10",
            "return_guidance": "Retornar com exames",
            "has_referral": True,
            "referral_target": "Cirurgia dermatologica",
            "referral_reason": "Excisao diagnostica",
            "general_observations": "Orientado sinais de alerta",
        },
    )
    assert create_response.status_code == 201

    record_id = create_response.get_json()["id"]
    detail_response = client.get(f"/api/v1/medical-records/{record_id}", headers=headers)
    assert detail_response.status_code == 200
    detail_payload = detail_response.get_json()
    assert detail_payload["diagnostic_hypothesis"] == "Nevus"
    assert detail_payload["exams_requested"] == "Dermoscopy"
    assert detail_payload["prescriptions"] == "Sunscreen"
    assert detail_payload["attendance_datetime"].startswith("2026-06-04T09:00:00")
    assert detail_payload["doctor_name"] == doctor.name
    assert detail_payload["doctor_crm"] == profile.crm
    assert detail_payload["doctor_signature"] == f"{doctor.name} - CRM {profile.crm}"
    assert detail_payload["record_datetime"]
    assert detail_payload["consultation_type"] == "Lesion assessment"
    assert detail_payload["chief_complaint"] == "Lesao pigmentada"
    assert detail_payload["associated_symptoms"] == ["Coceira", "Sangramento"]
    assert detail_payload["has_suspicious_lesion"] is True
    assert detail_payload["irregular_borders"] is True
    assert detail_payload["diameter_greater_than_6mm"] is True
    assert detail_payload["suggested_return_date"] == "2026-07-10"
    assert detail_payload["updated_at"]
    assert "prescription" not in detail_payload
    assert "observations" not in detail_payload

    update_response = client.put(
        f"/api/v1/medical-records/{record_id}",
        headers=headers,
        json={
            "diagnostic_hypothesis": "Seborrheic keratosis",
            "exams_requested": "Biopsy if change occurs",
            "prescriptions": "Moisturizer",
            "has_suspicious_lesion": False,
            "asymmetry": False,
            "suspicion_level": "Baixo",
            "needs_follow_up": False,
            "suggested_return_date": None,
            "return_guidance": "",
        },
    )
    assert update_response.status_code == 200
    assert update_response.get_json() == {"id": record_id}

    updated_detail_response = client.get(f"/api/v1/medical-records/{record_id}", headers=headers)
    updated_detail_payload = updated_detail_response.get_json()
    assert updated_detail_payload["diagnostic_hypothesis"] == "Seborrheic keratosis"
    assert updated_detail_payload["exams_requested"] == "Biopsy if change occurs"
    assert updated_detail_payload["prescriptions"] == "Moisturizer"
    assert updated_detail_payload["has_suspicious_lesion"] is False
    assert updated_detail_payload["asymmetry"] is False
    assert updated_detail_payload["suspicion_level"] == "Baixo"
    assert updated_detail_payload["needs_follow_up"] is False
    assert updated_detail_payload["suggested_return_date"] is None
    assert updated_detail_payload["return_guidance"] == ""
    assert updated_detail_payload["updated_at"]
    assert updated_detail_payload["updated_at"] != detail_payload["updated_at"]

    admin_update_response = client.put(
        f"/api/v1/medical-records/{record_id}",
        headers=_auth_header(app, clinic_admin),
        json={
            "diagnosis": "Updated by clinic admin",
            "patient_id": patient.id + 999,
            "appointment_id": appointment.id + 999,
            "doctor_profile_id": profile.id + 999,
            "clinic_id": clinic.id + 999,
            "updated_at": "2000-01-01T00:00:00Z",
            "ai_analyses": [{"id": 999}],
        },
    )
    assert admin_update_response.status_code == 200

    admin_detail_payload = client.get(
        f"/api/v1/medical-records/{record_id}",
        headers=_auth_header(app, clinic_admin),
    ).get_json()
    assert admin_detail_payload["diagnosis"] == "Updated by clinic admin"
    assert admin_detail_payload["patient_id"] == patient.id
    assert admin_detail_payload["appointment_id"] == appointment.id
    assert admin_detail_payload["doctor_profile_id"] == profile.id
    assert admin_detail_payload["clinic_id"] == clinic.id


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
        client.put(f"/api/v1/medical-records/{record.id}", headers=headers, json={"diagnosis": "Blocked"}),
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


def test_clear_clinical_data_cli_is_confirmed_and_preserves_registration_data(app, monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("FLASK_ENV", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    clinic = _make_clinic("CLI Clear Clinic")
    admin = _make_user("cli-admin@test.com", RoleEnum.CLINIC_ADMIN, clinic.id)
    doctor, doctor_profile = _make_doctor("cli-doctor@test.com", clinic.id)
    patient = _make_patient(clinic.id, "91000000008")
    appointment = Appointment(
        clinic_id=clinic.id,
        patient_id=patient.id,
        doctor_profile_id=doctor_profile.id,
        scheduled_at=datetime(2026, 6, 5, 9, 0),
        status=AppointmentStatus.SCHEDULED,
        created_by=admin.id,
    )
    block = ScheduleBlock(
        clinic_id=clinic.id,
        doctor_profile_id=doctor_profile.id,
        start_time=datetime(2026, 6, 5, 12, 0),
        end_time=datetime(2026, 6, 5, 13, 0),
        reason="Lunch",
    )
    _db.session.add_all([appointment, block])
    _db.session.flush()

    record = MedicalRecord(
        clinic_id=clinic.id,
        patient_id=patient.id,
        doctor_profile_id=doctor_profile.id,
        appointment_id=appointment.id,
        diagnosis="CLI diagnosis",
    )
    _db.session.add(record)
    _db.session.flush()

    document = Document(
        clinic_id=clinic.id,
        medical_record_id=record.id,
        file_path="uploads/test-image.jpg",
        file_type="image/jpeg",
    )
    _db.session.add(document)
    _db.session.flush()

    analysis = AIAnalysis(
        clinic_id=clinic.id,
        medical_record_id=record.id,
        document_id=document.id,
        ai_diagnosis="benign",
        probability=0.2,
        confidence_level="high",
        recommendation="Follow up",
        model_version="test",
        disclaimer="test",
    )
    _db.session.add(analysis)
    _db.session.commit()
    expected_medical_records = MedicalRecord.query.count()
    expected_appointments = Appointment.query.count()
    expected_schedule_blocks = ScheduleBlock.query.count()

    runner = app.test_cli_runner()

    dry_run = runner.invoke(args=["clear-clinical-data", "--dry-run"])
    assert dry_run.exit_code == 0
    assert f"- medical_records: {expected_medical_records}" in dry_run.output
    assert f"- appointments: {expected_appointments}" in dry_run.output
    assert f"- schedule_blocks: {expected_schedule_blocks}" in dry_run.output
    assert MedicalRecord.query.count() == expected_medical_records
    assert Appointment.query.count() == expected_appointments
    assert ScheduleBlock.query.count() == expected_schedule_blocks

    missing_confirmation = runner.invoke(args=["clear-clinical-data"])
    assert missing_confirmation.exit_code != 0
    assert "Confirmacao obrigatoria" in missing_confirmation.output
    assert MedicalRecord.query.count() == expected_medical_records

    monkeypatch.setenv("ENVIRONMENT", "production")
    production_attempt = runner.invoke(
        args=["clear-clinical-data", "--confirm", "DELETE_CLINICAL_DATA"]
    )
    assert production_attempt.exit_code != 0
    assert "ambiente de producao" in production_attempt.output
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    executed = runner.invoke(
        args=["clear-clinical-data", "--confirm", "DELETE_CLINICAL_DATA"]
    )
    assert executed.exit_code == 0
    assert "Limpeza concluida com sucesso" in executed.output

    assert AIAnalysis.query.count() == 0
    assert Document.query.count() == 0
    assert MedicalRecord.query.count() == 0
    assert Appointment.query.count() == 0
    assert ScheduleBlock.query.count() == 0
    assert Clinic.query.get(clinic.id) is not None
    assert User.query.get(admin.id) is not None
    assert User.query.get(doctor.id) is not None
    assert DoctorProfile.query.get(doctor_profile.id) is not None
    assert Patient.query.get(patient.id) is not None
