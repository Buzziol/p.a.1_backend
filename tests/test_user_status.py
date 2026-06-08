import sys

import pytest
from flask_jwt_extended import create_access_token

sys.path.insert(0, ".")

from src.api.api_config import APIConfig
from src.api.app import create_app
from src.api.database.extensions import db as _db
from src.api.models_db.models import Clinic, RoleEnum, User
from src.api.seed.seed_data import run_seed


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


def _make_user(email, role, clinic_id=None, is_active=True):
    user = User(
        clinic_id=clinic_id,
        name=email,
        email=email,
        role=role,
        is_active=is_active,
    )
    user.set_password("test123")
    _db.session.add(user)
    _db.session.flush()
    return user


def _auth_header(app, user):
    with app.app_context():
        token = create_access_token(
            identity=str(user.id),
            additional_claims={"role": user.role.value, "clinic_id": user.clinic_id},
        )
    return {"Authorization": f"Bearer {token}"}


def test_seed_users_are_active(app):
    with app.app_context():
        run_seed()
        seed_users = User.query.filter(
            User.email.in_([
                "superadmin@dermato.local",
                "admin@dermato.local",
                "medico@dermato.local",
                "recepcao@dermato.local",
            ])
        ).all()

        assert len(seed_users) == 4
        assert all(user.is_active is True for user in seed_users)


def test_create_user_defaults_to_active_and_auth_responses_expose_is_active(client, app):
    clinic = _make_clinic("User Status Clinic")
    super_admin = _make_user("user-status-super@test.com", RoleEnum.SUPER_ADMIN)

    create_response = client.post(
        "/api/v1/users",
        headers=_auth_header(app, super_admin),
        json={
            "name": "Reception Active",
            "email": "created-active@test.com",
            "password": "test123",
            "role": "RECEPTIONIST",
            "clinic_id": clinic.id,
        },
    )

    assert create_response.status_code == 201
    create_payload = create_response.get_json()
    assert create_payload["is_active"] is True

    list_response = client.get("/api/v1/users", headers=_auth_header(app, super_admin))
    assert list_response.status_code == 200
    listed_user = next(user for user in list_response.get_json() if user["email"] == "created-active@test.com")
    assert listed_user["is_active"] is True

    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "created-active@test.com", "password": "test123"},
    )
    assert login_response.status_code == 200
    assert login_response.get_json()["user"]["is_active"] is True

    me_response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login_response.get_json()['access_token']}"},
    )
    assert me_response.status_code == 200
    assert me_response.get_json()["is_active"] is True


def test_create_user_can_explicitly_create_inactive_user(client, app):
    clinic = _make_clinic("Inactive User Status Clinic")
    super_admin = _make_user("inactive-user-status-super@test.com", RoleEnum.SUPER_ADMIN)

    create_response = client.post(
        "/api/v1/users",
        headers=_auth_header(app, super_admin),
        json={
            "name": "Reception Inactive",
            "email": "created-inactive@test.com",
            "password": "test123",
            "role": "RECEPTIONIST",
            "clinic_id": clinic.id,
            "is_active": False,
        },
    )

    assert create_response.status_code == 201
    assert create_response.get_json()["is_active"] is False

    list_response = client.get("/api/v1/users", headers=_auth_header(app, super_admin))
    assert list_response.status_code == 200
    listed_user = next(user for user in list_response.get_json() if user["email"] == "created-inactive@test.com")
    assert listed_user["is_active"] is False

    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "created-inactive@test.com", "password": "test123"},
    )
    assert login_response.status_code == 401
