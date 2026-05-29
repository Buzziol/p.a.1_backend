from datetime import date, datetime

import sys

import pytest
from flask_jwt_extended import create_access_token

sys.path.insert(0, ".")

from src.api.app import create_app
from src.api.api_config import APIConfig
from src.api.controllers import admin_controller as dashboard_module
from src.api.database.extensions import db as _db
from src.api.models_db.models import (
    Appointment,
    AppointmentStatus,
    Clinic,
    DoctorProfile,
    Patient,
    RoleEnum,
    User,
)


FIXED_TODAY = date(2026, 5, 28)
EXPECTED_KEYS = {
    "active_clinics",
    "active_users",
    "total_patients",
    "appointments_today",
    "appointments_scheduled",
    "completed_month",
    "my_appointments_today",
    "weekly_appointments",
}
WEEK_DAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


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
def db_session(app, monkeypatch):
    monkeypatch.setattr(dashboard_module, "_today", lambda: FIXED_TODAY)
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


def _make_appointment(clinic_id, patient_id, doctor_profile_id, status, scheduled_at, created_by):
    appointment = Appointment(
        clinic_id=clinic_id,
        patient_id=patient_id,
        doctor_profile_id=doctor_profile_id,
        status=status,
        scheduled_at=scheduled_at,
        created_by=created_by,
    )
    _db.session.add(appointment)
    _db.session.flush()
    return appointment


def _auth_header(app, user):
    with app.app_context():
        token = create_access_token(
            identity=str(user.id),
            additional_claims={"role": user.role.value, "clinic_id": user.clinic_id},
        )
    return {"Authorization": f"Bearer {token}"}


def _get_dashboard(client, app, user):
    response = client.get("/api/v1/dashboard", headers=_auth_header(app, user))
    assert response.status_code == 200
    data = response.get_json()
    assert set(data) == EXPECTED_KEYS
    numeric_values = {key: value for key, value in data.items() if key != "weekly_appointments"}
    assert all(isinstance(value, int) for value in numeric_values.values())
    assert [item["day"] for item in data["weekly_appointments"]] == WEEK_DAYS
    assert all(isinstance(item["count"], int) for item in data["weekly_appointments"])
    return data


def _weekly_counts(*counts):
    return [{"day": day, "count": count} for day, count in zip(WEEK_DAYS, counts)]


def test_dashboard_counts_are_scoped_by_role_and_status(client, app):
    clinic_a = _make_clinic("Clinic Dashboard A")
    clinic_b = _make_clinic("Clinic Dashboard B")
    super_admin = _make_user("dash-super@test.com", RoleEnum.SUPER_ADMIN)
    clinic_admin = _make_user("dash-admin@test.com", RoleEnum.CLINIC_ADMIN, clinic_a.id)
    receptionist = _make_user("dash-reception@test.com", RoleEnum.RECEPTIONIST, clinic_a.id)
    doctor, doctor_profile = _make_doctor("dash-doctor@test.com", clinic_a.id)
    other_doctor, other_doctor_profile = _make_doctor("dash-other-doctor@test.com", clinic_a.id)
    remote_doctor, remote_doctor_profile = _make_doctor("dash-remote-doctor@test.com", clinic_b.id)

    patient_a = _make_patient(clinic_a.id, "90000000001")
    patient_other_doctor = _make_patient(clinic_a.id, "90000000002")
    patient_b = _make_patient(clinic_b.id, "90000000003")

    today_early = datetime(2026, 5, 28, 2, 5)
    today_midday = datetime(2026, 5, 28, 12, 0)
    today_late = datetime(2026, 5, 28, 23, 30)
    week_monday = datetime(2026, 5, 25, 9, 0)
    week_tuesday = datetime(2026, 5, 26, 9, 0)
    week_wednesday = datetime(2026, 5, 27, 9, 0)
    week_friday = datetime(2026, 5, 29, 9, 0)
    week_sunday = datetime(2026, 5, 31, 9, 0)
    current_month = datetime(2026, 5, 10, 9, 0)
    previous_month = datetime(2026, 4, 28, 9, 0)

    for status, scheduled_at in [
        (AppointmentStatus.SCHEDULED, today_early),
        (AppointmentStatus.CONFIRMED, today_midday),
        (AppointmentStatus.IN_PROGRESS, today_late),
        (AppointmentStatus.COMPLETED, current_month),
        (AppointmentStatus.CANCELLED, today_midday),
        (AppointmentStatus.NO_SHOW, today_midday),
        (AppointmentStatus.COMPLETED, previous_month),
    ]:
        _make_appointment(
            clinic_a.id,
            patient_a.id,
            doctor_profile.id,
            status,
            scheduled_at,
            clinic_admin.id,
        )

    _make_appointment(
        clinic_a.id,
        patient_other_doctor.id,
        other_doctor_profile.id,
        AppointmentStatus.SCHEDULED,
        today_midday,
        clinic_admin.id,
    )
    _make_appointment(
        clinic_b.id,
        patient_b.id,
        remote_doctor_profile.id,
        AppointmentStatus.SCHEDULED,
        today_midday,
        remote_doctor.id,
    )
    _make_appointment(
        clinic_b.id,
        patient_b.id,
        remote_doctor_profile.id,
        AppointmentStatus.COMPLETED,
        current_month,
        remote_doctor.id,
    )
    _make_appointment(
        clinic_a.id,
        patient_a.id,
        doctor_profile.id,
        AppointmentStatus.COMPLETED,
        week_monday,
        clinic_admin.id,
    )
    _make_appointment(
        clinic_a.id,
        patient_a.id,
        doctor_profile.id,
        AppointmentStatus.CANCELLED,
        week_tuesday,
        clinic_admin.id,
    )
    _make_appointment(
        clinic_a.id,
        patient_other_doctor.id,
        other_doctor_profile.id,
        AppointmentStatus.CONFIRMED,
        week_wednesday,
        clinic_admin.id,
    )
    _make_appointment(
        clinic_b.id,
        patient_b.id,
        remote_doctor_profile.id,
        AppointmentStatus.NO_SHOW,
        week_friday,
        remote_doctor.id,
    )
    _make_appointment(
        clinic_b.id,
        patient_b.id,
        remote_doctor_profile.id,
        AppointmentStatus.IN_PROGRESS,
        week_sunday,
        remote_doctor.id,
    )

    _db.session.flush()

    assert _get_dashboard(client, app, super_admin) == {
        "active_clinics": Clinic.query.filter(Clinic.is_active.is_(True)).count(),
        "active_users": User.query.filter(User.is_active.is_(True)).count(),
        "total_patients": 3,
        "appointments_today": 5,
        "appointments_scheduled": 5,
        "completed_month": 3,
        "my_appointments_today": 0,
        "weekly_appointments": _weekly_counts(1, 0, 1, 5, 0, 0, 1),
    }
    expected_clinic = {
        "active_clinics": 0,
        "active_users": 0,
        "total_patients": 2,
        "appointments_today": 4,
        "appointments_scheduled": 4,
        "completed_month": 2,
        "my_appointments_today": 0,
        "weekly_appointments": _weekly_counts(1, 0, 1, 4, 0, 0, 0),
    }
    assert _get_dashboard(client, app, clinic_admin) == expected_clinic
    assert _get_dashboard(client, app, receptionist) == expected_clinic
    assert _get_dashboard(client, app, doctor) == {
        "active_clinics": 0,
        "active_users": 0,
        "total_patients": 1,
        "appointments_today": 3,
        "appointments_scheduled": 2,
        "completed_month": 2,
        "my_appointments_today": 3,
        "weekly_appointments": _weekly_counts(1, 0, 0, 3, 0, 0, 0),
    }


def test_dashboard_without_clinic_data_returns_zeroes(client, app):
    empty_clinic = _make_clinic("Empty Dashboard Clinic")
    clinic_admin = _make_user("empty-admin@test.com", RoleEnum.CLINIC_ADMIN, empty_clinic.id)

    assert _get_dashboard(client, app, clinic_admin) == {
        "active_clinics": 0,
        "active_users": 0,
        "total_patients": 0,
        "appointments_today": 0,
        "appointments_scheduled": 0,
        "completed_month": 0,
        "my_appointments_today": 0,
        "weekly_appointments": _weekly_counts(0, 0, 0, 0, 0, 0, 0),
    }


def test_dashboard_internal_error_returns_json(client, app, monkeypatch):
    user = _make_user("dashboard-error@test.com", RoleEnum.SUPER_ADMIN)

    def fail_today():
        raise RuntimeError("forced dashboard failure")

    monkeypatch.setattr(dashboard_module, "_today", fail_today)

    response = client.get("/api/v1/dashboard", headers=_auth_header(app, user))

    assert response.status_code == 500
    assert response.is_json
    assert "<html" not in response.get_data(as_text=True).lower()
    assert response.get_json()["code"] == "INTERNAL_ERROR"
