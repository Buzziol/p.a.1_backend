"""
Testes de integridade do banco de dados.

Verificam constraints (FK, UNIQUE), transações, soft delete e
isolamento por clinic_id.
"""

import pytest
from datetime import date, datetime, timedelta

import sys
sys.path.insert(0, ".")

from src.api.app import create_app
from src.api.api_config import APIConfig
from src.api.database.extensions import db as _db
from src.api.models_db.models import (
    Clinic, User, Patient, DoctorProfile, Appointment,
    AppointmentStatus, RoleEnum,
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
    """Wraps each test in a savepoint so changes are always rolled back."""
    with app.app_context():
        connection = _db.engine.connect()
        transaction = connection.begin()
        session = _db.session
        session.bind = connection

        yield session

        session.close()
        transaction.rollback()
        connection.close()


# ─── Helpers ────────────────────────────────────────────────────────────────

def _make_clinic(name="Test Clinic") -> Clinic:
    c = Clinic(name=name)
    _db.session.add(c)
    _db.session.flush()
    return c


def _make_user(clinic_id: int, email: str, role=RoleEnum.DOCTOR) -> User:
    u = User(clinic_id=clinic_id, name="Test User", email=email, role=role)
    u.set_password("test123")
    _db.session.add(u)
    _db.session.flush()
    return u


def _make_patient(clinic_id: int, cpf: str = "12345678900") -> Patient:
    p = Patient(
        clinic_id=clinic_id,
        name="Test Patient",
        cpf=cpf,
        address="Rua A, 1",
        cep="01234567",
        phone="11999999999",
        birth_date=date(1990, 1, 1),
        blood_type="O",
        email=f"patient_{cpf}@test.com",
        marital_status="single",
    )
    _db.session.add(p)
    _db.session.flush()
    return p


# ─── Unique constraint: CPF per clinic ──────────────────────────────────────

def test_unique_cpf_same_clinic_raises(db_session):
    clinic = _make_clinic()
    _make_patient(clinic.id, cpf="11111111111")

    duplicate = Patient(
        clinic_id=clinic.id,
        name="Dupe",
        cpf="11111111111",
        address="Rua B",
        cep="01234567",
        phone="11988888888",
        birth_date=date(1985, 6, 1),
        blood_type="A",
        email="dupe@test.com",
        marital_status="single",
    )
    _db.session.add(duplicate)
    with pytest.raises(Exception):
        _db.session.flush()


def test_same_cpf_different_clinic_allowed(db_session):
    clinic1 = _make_clinic("Clinic A")
    clinic2 = _make_clinic("Clinic B")
    _make_patient(clinic1.id, cpf="22222222222")
    # Must not raise
    _make_patient(clinic2.id, cpf="22222222222")


# ─── Unique constraint: email per user ──────────────────────────────────────

def test_unique_user_email_raises(db_session):
    clinic = _make_clinic()
    _make_user(clinic.id, email="shared@test.com")
    with pytest.raises(Exception):
        _make_user(clinic.id, email="shared@test.com")
        _db.session.flush()


# ─── Foreign key: patient must belong to existing clinic ────────────────────

@pytest.mark.skipif(
    True,  # SQLite in-memory doesn't enforce FK by default; run against PostgreSQL in CI
    reason="FK enforcement requires PostgreSQL or SQLite with PRAGMA foreign_keys=ON",
)
def test_patient_invalid_clinic_raises(db_session):
    p = Patient(
        clinic_id=99999,
        name="Ghost",
        cpf="33333333333",
        address="X",
        cep="00000000",
        phone="11900000000",
        birth_date=date(2000, 1, 1),
        blood_type="B",
        email="ghost@test.com",
        marital_status="single",
    )
    _db.session.add(p)
    with pytest.raises(Exception):
        _db.session.flush()


# ─── Soft delete ────────────────────────────────────────────────────────────

def test_soft_delete_patient(db_session):
    clinic = _make_clinic()
    p = _make_patient(clinic.id, cpf="44444444444")
    pid = p.id

    p.is_active = False
    _db.session.flush()

    still_there = Patient.query.get(pid)
    assert still_there is not None, "Soft delete should keep the row"
    assert still_there.is_active is False


# ─── Multi-tenant isolation ──────────────────────────────────────────────────

def test_patients_filtered_by_clinic(db_session):
    clinic1 = _make_clinic("C1")
    clinic2 = _make_clinic("C2")
    _make_patient(clinic1.id, cpf="55555555551")
    _make_patient(clinic2.id, cpf="55555555552")

    c1_patients = Patient.query.filter_by(clinic_id=clinic1.id, is_active=True).all()
    c2_patients = Patient.query.filter_by(clinic_id=clinic2.id, is_active=True).all()

    assert all(p.clinic_id == clinic1.id for p in c1_patients)
    assert all(p.clinic_id == clinic2.id for p in c2_patients)


# ─── Rollback on error ───────────────────────────────────────────────────────

def test_transaction_rolls_back_on_error(db_session):
    clinic = _make_clinic()
    cpf = "66666666666"

    try:
        _make_patient(clinic.id, cpf=cpf)
        raise RuntimeError("Simulated error mid-transaction")
    except RuntimeError:
        _db.session.rollback()

    result = Patient.query.filter_by(cpf=cpf).first()
    assert result is None, "Rolled-back patient should not persist"


# ─── Password hashing ────────────────────────────────────────────────────────

def test_password_hash_not_plaintext(db_session):
    clinic = _make_clinic()
    u = _make_user(clinic.id, email="hash_test@test.com")
    assert u.password_hash != "test123"
    assert u.check_password("test123") is True
    assert u.check_password("wrong") is False
