from datetime import datetime, time, timedelta

import pytest
from flask_jwt_extended import create_access_token

from src.api.api_config import APIConfig
from src.api.app import create_app
from src.api.database.extensions import db
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.api.models_db.models import (
    Appointment, AppointmentStatus, AuditLog, Clinic, DoctorAvailability, DoctorProfile,
    Patient, ReschedulePending, ReschedulePendingStatus, RoleEnum, ScheduleBlock, User,
)


@pytest.fixture()
def app():
    config = APIConfig(); config.DATABASE_URL = "sqlite:///:memory:"
    application = create_app(config)
    with application.app_context(): db.create_all()
    yield application
    with application.app_context(): db.drop_all()


@pytest.fixture()
def client(app): return app.test_client()


def token(app, user):
    with app.app_context(): return {"Authorization": f"Bearer {create_access_token(identity=str(user.id))}"}


def setup_clinic():
    clinic = Clinic(name="Scheduling Clinic", is_active=True); db.session.add(clinic); db.session.flush()
    users = {}
    for role in (RoleEnum.CLINIC_ADMIN, RoleEnum.RECEPTIONIST, RoleEnum.DOCTOR):
        user = User(clinic_id=clinic.id, name=role.value, email=f"{role.value.lower()}@schedule.test", role=role, is_active=True)
        user.set_password("Password1!"); db.session.add(user); db.session.flush(); users[role] = user
    profile = DoctorProfile(user_id=users[RoleEnum.DOCTOR].id, crm="CRM-SCHEDULE"); db.session.add(profile)
    patient = Patient(
        clinic_id=clinic.id, name="Patient", cpf="12345678901", address="Street", cep="00000000",
        phone="11999999999", birth_date=datetime(1990, 1, 1).date(), blood_type="O+",
        email="patient@schedule.test", marital_status="single", is_active=True,
    ); db.session.add(patient); db.session.flush()
    return clinic, users, profile, patient


def future_weekday(weekday=0):
    value = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
    while value.weekday() != weekday: value += timedelta(days=1)
    return value


def monday(hour=9, minute=0):
    """A fixed future Monday keeps scheduling assertions independent of the clock."""
    return datetime(2027, 1, 4, hour, minute)


def appointment_payload(patient, profile, start, duration=30):
    return {
        "patient_id": patient.id,
        "doctor_profile_id": profile.id,
        "scheduled_at": start.isoformat(),
        "duration_minutes": duration,
    }


def pending_for(appointment, source="BLOCK_CREATED", source_type="SCHEDULE_BLOCK", source_id=1):
    pending = ReschedulePending(
        clinic_id=appointment.clinic_id,
        appointment_id=appointment.id,
        open_appointment_id=appointment.id,
        status=ReschedulePendingStatus.PENDING,
        source=source,
        source_entity_type=source_type,
        source_entity_id=source_id,
        reason="Agenda alterada",
    )
    db.session.add(pending)
    return pending


def add_availability(clinic, profile, actor, weekday=1, start=time(8), end=time(18)):
    row = DoctorAvailability(clinic_id=clinic.id, doctor_profile_id=profile.id, weekday=weekday, start_time=start, end_time=end, created_by=actor.id)
    db.session.add(row); db.session.flush(); return row


def test_doctor_crud_is_own_and_receptionist_writes_are_forbidden(app, client):
    with app.app_context():
        clinic, users, profile, _ = setup_clinic(); db.session.commit()
        doctor_headers = token(app, users[RoleEnum.DOCTOR]); receptionist_headers = token(app, users[RoleEnum.RECEPTIONIST])
        response = client.post("/api/v1/doctor-availabilities", headers=doctor_headers, json={"weekday": 1, "start_time": "08:00", "end_time": "12:00"})
        assert response.status_code == 201
        assert client.get("/api/v1/doctor-availabilities", headers=doctor_headers).get_json()[0]["doctor_profile_id"] == profile.id
        assert client.post("/api/v1/doctor-availabilities", headers=receptionist_headers, json={"weekday": 1, "start_time": "13:00", "end_time": "17:00"}).status_code == 403


def test_overlapping_ranges_rejected_but_adjacent_ranges_allowed(app, client):
    with app.app_context():
        clinic, users, profile, _ = setup_clinic(); db.session.commit(); headers = token(app, users[RoleEnum.CLINIC_ADMIN])
        base = {"doctor_profile_id": profile.id, "weekday": 1}
        assert client.post("/api/v1/doctor-availabilities", headers=headers, json={**base, "start_time": "08:00", "end_time": "12:00"}).status_code == 201
        assert client.post("/api/v1/doctor-availabilities", headers=headers, json={**base, "start_time": "11:30", "end_time": "13:00"}).status_code == 409
        assert client.post("/api/v1/doctor-availabilities", headers=headers, json={**base, "start_time": "12:00", "end_time": "16:00"}).status_code == 201


def test_doctor_cannot_target_another_profile_or_cross_clinic(app, client):
    with app.app_context():
        clinic, users, profile, _ = setup_clinic()
        other_clinic = Clinic(name="Other Clinic", is_active=True); db.session.add(other_clinic); db.session.flush()
        other_user = User(clinic_id=other_clinic.id, name="Other Doctor", email="other-doctor@schedule.test", role=RoleEnum.DOCTOR, is_active=True); other_user.set_password("Password1!")
        db.session.add(other_user); db.session.flush(); other_profile = DoctorProfile(user_id=other_user.id, crm="CRM-OTHER"); db.session.add(other_profile); db.session.commit()
        payload = {"doctor_profile_id": other_profile.id, "weekday": 1, "start_time": "08:00", "end_time": "12:00"}
        assert client.post("/api/v1/doctor-availabilities", headers=token(app, users[RoleEnum.DOCTOR]), json=payload).status_code == 403
        assert client.post("/api/v1/doctor-availabilities", headers=token(app, users[RoleEnum.CLINIC_ADMIN]), json=payload).status_code == 404


def test_booking_uses_full_duration_availability_and_conflicts(app, client):
    with app.app_context():
        clinic, users, profile, patient = setup_clinic(); start = future_weekday(0)
        add_availability(clinic, profile, users[RoleEnum.CLINIC_ADMIN], weekday=1, start=time(9), end=time(10)); db.session.commit()
        headers = token(app, users[RoleEnum.RECEPTIONIST])
        payload = {"patient_id": patient.id, "doctor_profile_id": profile.id, "scheduled_at": start.isoformat(), "duration_minutes": 60}
        created = client.post("/api/v1/appointments", headers=headers, json=payload)
        assert created.status_code == 201 and created.get_json()["duration_minutes"] == 60
        assert client.post("/api/v1/appointments", headers=headers, json={**payload, "scheduled_at": (start + timedelta(minutes=30)).isoformat(), "duration_minutes": 30}).status_code in (409, 422)
        assert client.post("/api/v1/appointments", headers=headers, json={**payload, "scheduled_at": (start + timedelta(minutes=30)).isoformat(), "duration_minutes": 60}).status_code == 422
        assert client.post("/api/v1/appointments", headers=headers, json={**payload, "duration_minutes": 45}).status_code == 422


def test_block_preserves_appointment_and_creates_one_pending(app, client):
    with app.app_context():
        clinic, users, profile, patient = setup_clinic(); start = future_weekday(0)
        add_availability(clinic, profile, users[RoleEnum.CLINIC_ADMIN]); appointment = Appointment(
            clinic_id=clinic.id, patient_id=patient.id, doctor_profile_id=profile.id,
            scheduled_at=start, duration_minutes=60, status=AppointmentStatus.SCHEDULED,
            created_by=users[RoleEnum.RECEPTIONIST].id,
        ); db.session.add(appointment); db.session.commit(); headers = token(app, users[RoleEnum.CLINIC_ADMIN])
        payload = {"doctor_profile_id": profile.id, "start_time": (start + timedelta(minutes=30)).isoformat(), "end_time": (start + timedelta(hours=2)).isoformat(), "reason": "Leave"}
        first = client.post("/api/v1/schedule-blocks", headers=headers, json=payload)
        assert first.status_code == 201 and first.get_json()["affected_appointments"] == 1
        assert Appointment.query.get(appointment.id).status == AppointmentStatus.SCHEDULED
        assert ReschedulePending.query.filter_by(open_appointment_id=appointment.id).count() == 1
        block_id = first.get_json()["id"]
        assert client.put(f"/api/v1/schedule-blocks/{block_id}", headers=headers, json=payload).status_code == 200
        assert ReschedulePending.query.filter_by(open_appointment_id=appointment.id).count() == 1


def test_removing_availability_creates_pending_without_moving_appointment(app, client):
    with app.app_context():
        clinic, users, profile, patient = setup_clinic(); start = future_weekday(0)
        availability = add_availability(clinic, profile, users[RoleEnum.CLINIC_ADMIN])
        appointment = Appointment(clinic_id=clinic.id, patient_id=patient.id, doctor_profile_id=profile.id, scheduled_at=start, duration_minutes=30, status=AppointmentStatus.CONFIRMED, created_by=users[RoleEnum.RECEPTIONIST].id)
        db.session.add(appointment); db.session.commit(); original = appointment.scheduled_at
        response = client.delete(f"/api/v1/doctor-availabilities/{availability.id}", headers=token(app, users[RoleEnum.CLINIC_ADMIN]))
        assert response.status_code == 200 and response.get_json()["affected_appointments"] == 1
        db.session.expire_all(); assert Appointment.query.get(appointment.id).scheduled_at == original
        assert ReschedulePending.query.filter_by(open_appointment_id=appointment.id).count() == 1


def test_all_day_multiday_block_uses_inclusive_end_date(app, client):
    with app.app_context():
        clinic, users, profile, _ = setup_clinic(); start = future_weekday(0).date(); end = start + timedelta(days=2); db.session.commit()
        response = client.post("/api/v1/schedule-blocks", headers=token(app, users[RoleEnum.CLINIC_ADMIN]), json={"doctor_profile_id": profile.id, "all_day": True, "start_date": start.isoformat(), "end_date": end.isoformat(), "reason": "Vacation"})
        assert response.status_code == 201
        body = response.get_json(); assert body["start_date"] == start.isoformat() and body["end_date"] == end.isoformat()
        assert datetime.fromisoformat(body["end_time"]).date() == end + timedelta(days=1)


def test_suggestions_are_valid_and_reschedule_resolves_pending(app, client):
    with app.app_context():
        clinic, users, profile, patient = setup_clinic(); current = future_weekday(0)
        add_availability(clinic, profile, users[RoleEnum.CLINIC_ADMIN]); appointment = Appointment(
            clinic_id=clinic.id, patient_id=patient.id, doctor_profile_id=profile.id, scheduled_at=current,
            duration_minutes=30, status=AppointmentStatus.SCHEDULED, created_by=users[RoleEnum.RECEPTIONIST].id,
        ); db.session.add(appointment); db.session.flush()
        pending = ReschedulePending(clinic_id=clinic.id, appointment_id=appointment.id, open_appointment_id=appointment.id, status=ReschedulePendingStatus.PENDING, source="AVAILABILITY_UPDATED", reason="Disponibilidade alterada")
        db.session.add(pending); db.session.commit(); headers = token(app, users[RoleEnum.RECEPTIONIST])
        suggestions = client.get(f"/api/v1/reschedule-pendings/{pending.id}/suggestions", headers=headers)
        assert suggestions.status_code == 200 and suggestions.get_json()["items"]
        selected = suggestions.get_json()["items"][0]
        response = client.put(f"/api/v1/appointments/{appointment.id}/reschedule", headers=headers, json={"scheduled_at": selected["start"]})
        assert response.status_code == 200
        db.session.expire_all(); resolved = ReschedulePending.query.get(pending.id)
        assert resolved.status == ReschedulePendingStatus.RESOLVED and resolved.open_appointment_id is None


def test_doctor_full_availability_crud_and_cannot_mutate_another_doctor(app, client):
    with app.app_context():
        clinic, users, profile, _ = setup_clinic()
        other = User(clinic_id=clinic.id, name="Other", email="other-own@test", role=RoleEnum.DOCTOR, is_active=True)
        other.set_password("Password1!"); db.session.add(other); db.session.flush()
        other_profile = DoctorProfile(user_id=other.id, crm="CRM-OTHER-OWN"); db.session.add(other_profile); db.session.commit()
        headers = token(app, users[RoleEnum.DOCTOR])
        created = client.post("/api/v1/doctor-availabilities", headers=headers, json={"weekday": 1, "start_time": "08:00", "end_time": "12:00"})
        assert created.status_code == 201
        row_id = created.get_json()["id"]
        assert client.get("/api/v1/doctor-availabilities", headers=headers).get_json()[0]["id"] == row_id
        assert client.put(f"/api/v1/doctor-availabilities/{row_id}", headers=headers, json={"end_time": "13:00"}).status_code == 200
        foreign = DoctorAvailability(clinic_id=clinic.id, doctor_profile_id=other_profile.id, weekday=1, start_time=time(8), end_time=time(12))
        db.session.add(foreign); db.session.commit()
        assert client.post("/api/v1/doctor-availabilities", headers=headers, json={"doctor_profile_id": other_profile.id, "weekday": 2, "start_time": "08:00", "end_time": "12:00"}).status_code == 403
        assert client.put(f"/api/v1/doctor-availabilities/{foreign.id}", headers=headers, json={"end_time": "13:00"}).status_code == 403
        assert client.delete(f"/api/v1/doctor-availabilities/{foreign.id}", headers=headers).status_code == 403
        assert client.delete(f"/api/v1/doctor-availabilities/{row_id}", headers=headers).status_code == 200


def test_admin_crud_is_clinic_scoped_and_receptionist_all_writes_are_forbidden(app, client):
    with app.app_context():
        clinic, users, profile, _ = setup_clinic()
        other_clinic = Clinic(name="Other scoped", is_active=True); db.session.add(other_clinic); db.session.flush()
        other_user = User(clinic_id=other_clinic.id, name="Other doctor", email="other-scoped@test", role=RoleEnum.DOCTOR, is_active=True)
        other_user.set_password("Password1!"); db.session.add(other_user); db.session.flush()
        other_profile = DoctorProfile(user_id=other_user.id, crm="CRM-SCOPED"); db.session.add(other_profile); db.session.commit()
        admin = token(app, users[RoleEnum.CLINIC_ADMIN]); receptionist = token(app, users[RoleEnum.RECEPTIONIST])
        created = client.post("/api/v1/doctor-availabilities", headers=admin, json={"doctor_profile_id": profile.id, "weekday": 1, "start_time": "08:00", "end_time": "12:00"})
        assert created.status_code == 201
        row_id = created.get_json()["id"]
        assert client.put(f"/api/v1/doctor-availabilities/{row_id}", headers=admin, json={"end_time": "13:00"}).status_code == 200
        assert client.post("/api/v1/doctor-availabilities", headers=admin, json={"doctor_profile_id": other_profile.id, "weekday": 1, "start_time": "08:00", "end_time": "12:00"}).status_code == 404
        for method, path, body in (
            (client.post, "/api/v1/doctor-availabilities", {"doctor_profile_id": profile.id, "weekday": 2, "start_time": "08:00", "end_time": "12:00"}),
            (client.put, f"/api/v1/doctor-availabilities/{row_id}", {"end_time": "14:00"}),
            (client.delete, f"/api/v1/doctor-availabilities/{row_id}", None),
        ):
            response = method(path, headers=receptionist, json=body) if body is not None else method(path, headers=receptionist)
            assert response.status_code == 403
        assert client.delete(f"/api/v1/doctor-availabilities/{row_id}", headers=admin).status_code == 200


def test_receptionist_cannot_create_update_or_delete_schedule_blocks(app, client):
    with app.app_context():
        clinic, users, profile, _ = setup_clinic(); start = monday(); db.session.commit()
        block = ScheduleBlock(clinic_id=clinic.id, doctor_profile_id=profile.id, start_time=start, end_time=start + timedelta(hours=1))
        db.session.add(block); db.session.commit(); headers = token(app, users[RoleEnum.RECEPTIONIST])
        payload = {"doctor_profile_id": profile.id, "start_time": (start + timedelta(hours=2)).isoformat(), "end_time": (start + timedelta(hours=3)).isoformat()}
        assert client.post("/api/v1/schedule-blocks", headers=headers, json=payload).status_code == 403
        assert client.put(f"/api/v1/schedule-blocks/{block.id}", headers=headers, json=payload).status_code == 403
        assert client.delete(f"/api/v1/schedule-blocks/{block.id}", headers=headers).status_code == 403


def test_availability_validation_rejects_invalid_weekday_empty_and_inverted_ranges(app, client):
    with app.app_context():
        clinic, users, profile, _ = setup_clinic(); db.session.commit(); headers = token(app, users[RoleEnum.CLINIC_ADMIN])
        base = {"doctor_profile_id": profile.id}
        assert client.post("/api/v1/doctor-availabilities", headers=headers, json={**base, "weekday": 0, "start_time": "08:00", "end_time": "12:00"}).status_code == 422
        assert client.post("/api/v1/doctor-availabilities", headers=headers, json={**base, "weekday": 1, "start_time": "12:00", "end_time": "08:00"}).status_code == 422
        assert client.post("/api/v1/doctor-availabilities", headers=headers, json={**base, "weekday": 1, "start_time": "08:00", "end_time": "08:00"}).status_code == 422


def test_booking_requires_availability_duration_and_full_interval(app, client):
    with app.app_context():
        clinic, users, profile, patient = setup_clinic(); start = monday(9); db.session.commit(); headers = token(app, users[RoleEnum.RECEPTIONIST])
        base = appointment_payload(patient, profile, start)
        assert client.post("/api/v1/appointments", headers=headers, json=base).status_code == 422
        add_availability(clinic, profile, users[RoleEnum.CLINIC_ADMIN], weekday=1, start=time(9), end=time(10)); db.session.commit()
        assert client.post("/api/v1/appointments", headers=headers, json={k: v for k, v in base.items() if k != "duration_minutes"}).status_code == 400
        assert client.post("/api/v1/appointments", headers=headers, json=base).status_code == 201
        assert client.post("/api/v1/appointments", headers=headers, json=appointment_payload(patient, profile, start, 60)).status_code == 409
        assert client.post("/api/v1/appointments", headers=headers, json=appointment_payload(patient, profile, monday(9, 30), 60)).status_code == 422


def test_different_durations_conflict_with_exact_409_and_partial_block_rejects_60(app, client):
    with app.app_context():
        clinic, users, profile, patient = setup_clinic(); start = monday(9); db.session.commit()
        add_availability(clinic, profile, users[RoleEnum.CLINIC_ADMIN], weekday=1, start=time(9), end=time(12)); db.session.commit(); reception = token(app, users[RoleEnum.RECEPTIONIST])
        assert client.post("/api/v1/appointments", headers=reception, json=appointment_payload(patient, profile, start, 60)).status_code == 201
        assert client.post("/api/v1/appointments", headers=reception, json=appointment_payload(patient, profile, monday(9, 30), 30)).status_code == 409
        admin = token(app, users[RoleEnum.CLINIC_ADMIN])
        block = client.post("/api/v1/schedule-blocks", headers=admin, json={"doctor_profile_id": profile.id, "start_time": monday(10).isoformat(), "end_time": monday(10, 30).isoformat()})
        assert block.status_code == 201
        assert client.post("/api/v1/appointments", headers=reception, json=appointment_payload(patient, profile, monday(10), 60)).status_code == 409


def test_all_day_single_and_multiday_blocks_are_normalized(app, client):
    with app.app_context():
        clinic, users, profile, _ = setup_clinic(); headers = token(app, users[RoleEnum.CLINIC_ADMIN]); db.session.commit()
        single = client.post("/api/v1/schedule-blocks", headers=headers, json={"doctor_profile_id": profile.id, "all_day": True, "start_date": "2027-01-05", "end_date": "2027-01-05"})
        assert single.status_code == 201 and single.get_json()["end_time"] == "2027-01-06T00:00:00"
        multi = client.post("/api/v1/schedule-blocks", headers=headers, json={"doctor_profile_id": profile.id, "all_day": True, "start_date": "2027-01-08", "end_date": "2027-01-10"})
        assert multi.status_code == 201 and multi.get_json()["end_time"] == "2027-01-11T00:00:00"


def test_block_edit_reconciles_only_stale_origin_pending_and_preserves_history(app, client):
    with app.app_context():
        clinic, users, profile, patient = setup_clinic(); start = monday(9)
        add_availability(clinic, profile, users[RoleEnum.CLINIC_ADMIN], weekday=1, start=time(8), end=time(18))
        appointment = Appointment(clinic_id=clinic.id, patient_id=patient.id, doctor_profile_id=profile.id, scheduled_at=start, duration_minutes=60, status=AppointmentStatus.SCHEDULED, created_by=users[RoleEnum.RECEPTIONIST].id)
        db.session.add(appointment); db.session.commit(); headers = token(app, users[RoleEnum.CLINIC_ADMIN])
        created = client.post("/api/v1/schedule-blocks", headers=headers, json={"doctor_profile_id": profile.id, "start_time": monday(9, 30).isoformat(), "end_time": monday(10, 30).isoformat()})
        assert created.status_code == 201
        block_id = created.get_json()["id"]
        pending = ReschedulePending.query.filter_by(open_appointment_id=appointment.id).one()
        pending_id = pending.id
        assert pending.source_entity_type == "SCHEDULE_BLOCK" and pending.source_entity_id == block_id
        moved = client.put(f"/api/v1/schedule-blocks/{block_id}", headers=headers, json={"start_time": monday(12).isoformat(), "end_time": monday(13).isoformat()})
        assert moved.status_code == 200
        db.session.expire_all(); historical = ReschedulePending.query.get(pending_id)
        assert historical.status == ReschedulePendingStatus.RESOLVED
        assert historical.appointment_id == appointment.id and historical.open_appointment_id is None


def test_reduced_block_keeps_pending_when_another_rule_still_invalid(app, client):
    with app.app_context():
        clinic, users, profile, patient = setup_clinic(); start = monday(9)
        availability = add_availability(clinic, profile, users[RoleEnum.CLINIC_ADMIN], weekday=1, start=time(8), end=time(18))
        appointment = Appointment(clinic_id=clinic.id, patient_id=patient.id, doctor_profile_id=profile.id, scheduled_at=start, duration_minutes=60, status=AppointmentStatus.SCHEDULED, created_by=users[RoleEnum.RECEPTIONIST].id)
        db.session.add(appointment); db.session.commit(); headers = token(app, users[RoleEnum.CLINIC_ADMIN])
        first = client.post("/api/v1/schedule-blocks", headers=headers, json={"doctor_profile_id": profile.id, "start_time": monday(9).isoformat(), "end_time": monday(9, 30).isoformat()})
        second = client.post("/api/v1/schedule-blocks", headers=headers, json={"doctor_profile_id": profile.id, "start_time": monday(9, 30).isoformat(), "end_time": monday(10).isoformat()})
        assert first.status_code == second.status_code == 201
        assert client.put(f"/api/v1/schedule-blocks/{first.get_json()['id']}", headers=headers, json={"start_time": monday(12).isoformat(), "end_time": monday(13).isoformat()}).status_code == 200
        assert ReschedulePending.query.filter_by(open_appointment_id=appointment.id, status=ReschedulePendingStatus.PENDING).count() == 1
        # Availability is independently invalidated; moving the second block must not resolve it.
        assert client.put(f"/api/v1/doctor-availabilities/{availability.id}", headers=headers, json={"end_time": "09:30"}).status_code == 200
        assert client.put(f"/api/v1/schedule-blocks/{second.get_json()['id']}", headers=headers, json={"start_time": monday(9, 30).isoformat(), "end_time": monday(10).isoformat()}).status_code == 200
        assert client.put(f"/api/v1/schedule-blocks/{second.get_json()['id']}", headers=headers, json={"start_time": monday(13).isoformat(), "end_time": monday(14).isoformat()}).status_code == 200
        assert ReschedulePending.query.filter_by(open_appointment_id=appointment.id, status=ReschedulePendingStatus.PENDING).count() == 1


def test_availability_edit_removal_and_repeated_changes_do_not_duplicate_pending(app, client):
    with app.app_context():
        clinic, users, profile, patient = setup_clinic(); start = monday(11)
        row = add_availability(clinic, profile, users[RoleEnum.CLINIC_ADMIN], weekday=1, start=time(8), end=time(12))
        appointment = Appointment(clinic_id=clinic.id, patient_id=patient.id, doctor_profile_id=profile.id, scheduled_at=start, duration_minutes=60, status=AppointmentStatus.SCHEDULED, created_by=users[RoleEnum.RECEPTIONIST].id)
        db.session.add(appointment); db.session.commit(); headers = token(app, users[RoleEnum.CLINIC_ADMIN])
        assert client.put(f"/api/v1/doctor-availabilities/{row.id}", headers=headers, json={"end_time": "11:30"}).status_code == 200
        assert client.put(f"/api/v1/doctor-availabilities/{row.id}", headers=headers, json={"end_time": "11:15"}).status_code == 200
        assert ReschedulePending.query.filter_by(open_appointment_id=appointment.id).count() == 1
        assert client.delete(f"/api/v1/doctor-availabilities/{row.id}", headers=headers).status_code == 200
        assert ReschedulePending.query.filter_by(open_appointment_id=appointment.id).count() == 1


def test_past_and_terminal_appointments_do_not_create_pendings_or_occupy_slots(app, client):
    with app.app_context():
        clinic, users, profile, patient = setup_clinic()
        add_availability(clinic, profile, users[RoleEnum.CLINIC_ADMIN], weekday=1, start=time(8), end=time(18))
        rows = [
            Appointment(clinic_id=clinic.id, patient_id=patient.id, doctor_profile_id=profile.id, scheduled_at=datetime(2020, 1, 6, 9), duration_minutes=60, status=AppointmentStatus.SCHEDULED, created_by=users[RoleEnum.RECEPTIONIST].id),
        ] + [
            Appointment(clinic_id=clinic.id, patient_id=patient.id, doctor_profile_id=profile.id, scheduled_at=monday(9), duration_minutes=60, status=status, created_by=users[RoleEnum.RECEPTIONIST].id)
            for status in (AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW)
        ]
        db.session.add_all(rows); db.session.commit(); headers = token(app, users[RoleEnum.CLINIC_ADMIN])
        slots = client.get("/api/v1/doctor-availabilities/slots", headers=headers, query_string={"doctor_profile_id": profile.id, "date_from": "2027-01-04", "date_to": "2027-01-04", "duration_minutes": 60})
        assert slots.status_code == 200
        assert any(item["start"] == monday(9).isoformat() for item in slots.get_json()["items"])
        created = client.post("/api/v1/schedule-blocks", headers=headers, json={"doctor_profile_id": profile.id, "start_time": monday(9).isoformat(), "end_time": monday(10).isoformat()})
        assert created.status_code == 201 and created.get_json()["affected_appointments"] == 0


def test_clinic_isolation_covers_availability_slots_appointments_blocks_pendings_and_suggestions(app, client):
    with app.app_context():
        clinic, users, profile, patient = setup_clinic()
        other_clinic = Clinic(name="Isolation Other", is_active=True); db.session.add(other_clinic); db.session.flush()
        other_admin = User(clinic_id=other_clinic.id, name="Other admin", email="isolation-admin@test", role=RoleEnum.CLINIC_ADMIN, is_active=True)
        other_admin.set_password("Password1!"); other_doctor = User(clinic_id=other_clinic.id, name="Other doc", email="isolation-doc@test", role=RoleEnum.DOCTOR, is_active=True); other_doctor.set_password("Password1!")
        db.session.add_all([other_admin, other_doctor]); db.session.flush(); other_profile = DoctorProfile(user_id=other_doctor.id, crm="CRM-ISO"); db.session.add(other_profile)
        other_patient = Patient(clinic_id=other_clinic.id, name="Other patient", cpf="99999999999", address="Street", cep="00000000", phone="11999999999", birth_date=datetime(1990, 1, 1).date(), blood_type="O+", email="other-patient@test", marital_status="single", is_active=True)
        db.session.add(other_patient); db.session.flush(); add_availability(other_clinic, other_profile, other_admin, weekday=1, start=time(8), end=time(18))
        other_appointment = Appointment(clinic_id=other_clinic.id, patient_id=other_patient.id, doctor_profile_id=other_profile.id, scheduled_at=monday(9), duration_minutes=30, status=AppointmentStatus.SCHEDULED, created_by=other_admin.id)
        db.session.add(other_appointment); db.session.flush(); pending = pending_for(other_appointment, source_id=77); db.session.commit()
        headers = token(app, users[RoleEnum.CLINIC_ADMIN])
        assert client.get("/api/v1/doctor-availabilities", headers=headers, query_string={"doctor_profile_id": other_profile.id}).status_code == 404
        assert client.get("/api/v1/doctor-availabilities/slots", headers=headers, query_string={"doctor_profile_id": other_profile.id, "date_from": "2027-01-04", "date_to": "2027-01-04", "duration_minutes": 30}).status_code == 404
        assert client.post("/api/v1/appointments", headers=headers, json=appointment_payload(other_patient, other_profile, monday())).status_code == 404
        assert client.post("/api/v1/schedule-blocks", headers=headers, json={"doctor_profile_id": other_profile.id, "start_time": monday().isoformat(), "end_time": monday(10).isoformat()}).status_code == 404
        assert client.get("/api/v1/reschedule-pendings", headers=headers).get_json() == []
        assert client.get(f"/api/v1/reschedule-pendings/{pending.id}/suggestions", headers=headers).status_code == 404


def test_suggestions_are_complete_operational_only_and_limited(app, client):
    with app.app_context():
        clinic, users, profile, patient = setup_clinic(); start = monday(9)
        add_availability(clinic, profile, users[RoleEnum.CLINIC_ADMIN], weekday=1, start=time(8), end=time(18))
        appointment = Appointment(clinic_id=clinic.id, patient_id=patient.id, doctor_profile_id=profile.id, scheduled_at=start, duration_minutes=60, status=AppointmentStatus.SCHEDULED, created_by=users[RoleEnum.RECEPTIONIST].id)
        block = ScheduleBlock(clinic_id=clinic.id, doctor_profile_id=profile.id, start_time=start, end_time=monday(10))
        conflict = Appointment(clinic_id=clinic.id, patient_id=patient.id, doctor_profile_id=profile.id, scheduled_at=monday(10), duration_minutes=60, status=AppointmentStatus.SCHEDULED, created_by=users[RoleEnum.RECEPTIONIST].id)
        db.session.add_all([appointment, block, conflict]); db.session.flush(); pending = pending_for(appointment, source_id=block.id); db.session.commit()
        headers = token(app, users[RoleEnum.RECEPTIONIST])
        response = client.get(f"/api/v1/reschedule-pendings/{pending.id}/suggestions", headers=headers)
        assert response.status_code == 200
        body = response.get_json(); assert len(body["items"]) <= 10 and body["limit"] == 10
        for slot in body["items"]:
            slot_start = datetime.fromisoformat(slot["start"]); slot_end = datetime.fromisoformat(slot["end"])
            assert slot_start > datetime.now() and slot["duration_minutes"] == 60
            assert slot_start.date() == slot_end.date() and time(8) <= slot_start.time() and slot_end.time() <= time(18)
            assert slot["start"] != appointment.scheduled_at.isoformat()
            assert not (slot_start < block.end_time and slot_end > block.start_time)
            assert not (slot_start < monday(11) and slot_end > monday(10))
        queue_item = client.get("/api/v1/reschedule-pendings", headers=headers).get_json()[0]
        assert queue_item["duration_minutes"] == 60 and queue_item["doctor"]["profile_id"] == profile.id
        assert not ({"diagnosis", "medical_record", "documents", "ai_analysis"} & set(queue_item))


def test_reschedule_revalidates_occupied_slot_and_cancel_preserves_pending_history(app, client):
    with app.app_context():
        clinic, users, profile, patient = setup_clinic(); start = monday(9)
        add_availability(clinic, profile, users[RoleEnum.CLINIC_ADMIN], weekday=1, start=time(8), end=time(18))
        appointment = Appointment(clinic_id=clinic.id, patient_id=patient.id, doctor_profile_id=profile.id, scheduled_at=start, duration_minutes=30, status=AppointmentStatus.SCHEDULED, created_by=users[RoleEnum.RECEPTIONIST].id)
        db.session.add(appointment); db.session.flush(); pending = pending_for(appointment); db.session.commit(); headers = token(app, users[RoleEnum.RECEPTIONIST])
        occupied = Appointment(clinic_id=clinic.id, patient_id=patient.id, doctor_profile_id=profile.id, scheduled_at=monday(10), duration_minutes=30, status=AppointmentStatus.SCHEDULED, created_by=users[RoleEnum.RECEPTIONIST].id)
        db.session.add(occupied); db.session.commit()
        rejected = client.put(f"/api/v1/appointments/{appointment.id}/reschedule", headers=headers, json={"scheduled_at": monday(10).isoformat()})
        assert rejected.status_code == 409
        db.session.expire_all(); assert Appointment.query.get(appointment.id).scheduled_at == start
        assert ReschedulePending.query.get(pending.id).status == ReschedulePendingStatus.PENDING
        cancelled = client.delete(f"/api/v1/appointments/{appointment.id}", headers=token(app, users[RoleEnum.CLINIC_ADMIN]))
        assert cancelled.status_code == 200
        historical = ReschedulePending.query.get(pending.id)
        assert historical.status == ReschedulePendingStatus.RESOLVED and historical.appointment_id == appointment.id and historical.open_appointment_id is None


def test_sqlalchemy_failure_rolls_back_block_and_pending_generation(app, client, monkeypatch):
    with app.app_context():
        clinic, users, profile, patient = setup_clinic(); start = monday(9)
        add_availability(clinic, profile, users[RoleEnum.CLINIC_ADMIN], weekday=1, start=time(8), end=time(18))
        appointment = Appointment(clinic_id=clinic.id, patient_id=patient.id, doctor_profile_id=profile.id, scheduled_at=start, duration_minutes=30, status=AppointmentStatus.SCHEDULED, created_by=users[RoleEnum.RECEPTIONIST].id)
        db.session.add(appointment); db.session.commit()
        def fail_pending(*args, **kwargs): raise SQLAlchemyError("injected pending failure")
        monkeypatch.setattr("src.api.controllers.schedule_block_controller.ensure_pending", fail_pending)
        response = client.post("/api/v1/schedule-blocks", headers=token(app, users[RoleEnum.CLINIC_ADMIN]), json={"doctor_profile_id": profile.id, "start_time": start.isoformat(), "end_time": monday(10).isoformat()})
        assert response.status_code == 500
        assert ScheduleBlock.query.count() == 0 and ReschedulePending.query.count() == 0


def test_concurrent_pending_integrity_error_is_controlled_and_rolls_back(app, client, monkeypatch):
    with app.app_context():
        clinic, users, profile, patient = setup_clinic(); start = monday(9); db.session.commit()
        add_availability(clinic, profile, users[RoleEnum.CLINIC_ADMIN], weekday=1, start=time(8), end=time(18))
        appointment = Appointment(clinic_id=clinic.id, patient_id=patient.id, doctor_profile_id=profile.id, scheduled_at=start, duration_minutes=30, status=AppointmentStatus.SCHEDULED, created_by=users[RoleEnum.RECEPTIONIST].id)
        db.session.add(appointment); db.session.commit()
        def duplicate_pending(*args, **kwargs): raise IntegrityError("INSERT", {}, Exception("uq_reschedule_pendings_open_appointment_id"))
        monkeypatch.setattr("src.api.controllers.schedule_block_controller.ensure_pending", duplicate_pending)
        response = client.post("/api/v1/schedule-blocks", headers=token(app, users[RoleEnum.CLINIC_ADMIN]), json={"doctor_profile_id": profile.id, "start_time": start.isoformat(), "end_time": monday(10).isoformat()})
        assert response.status_code == 409
        assert ScheduleBlock.query.count() == 0 and ReschedulePending.query.count() == 0


def test_sqlalchemy_failure_rolls_back_availability_audit_and_reschedule_resolution(app, client, monkeypatch):
    with app.app_context():
        clinic, users, profile, patient = setup_clinic(); start = monday(9); db.session.commit()
        def fail_audit(*args, **kwargs): raise SQLAlchemyError("injected audit failure")
        monkeypatch.setattr("src.api.controllers.doctor_availability_controller._audit", fail_audit)
        failed_create = client.post("/api/v1/doctor-availabilities", headers=token(app, users[RoleEnum.CLINIC_ADMIN]), json={"doctor_profile_id": profile.id, "weekday": 1, "start_time": "08:00", "end_time": "18:00"})
        assert failed_create.status_code == 500 and DoctorAvailability.query.count() == 0
        monkeypatch.undo()
        availability = add_availability(clinic, profile, users[RoleEnum.CLINIC_ADMIN], weekday=1, start=time(8), end=time(18))
        appointment = Appointment(clinic_id=clinic.id, patient_id=patient.id, doctor_profile_id=profile.id, scheduled_at=start, duration_minutes=30, status=AppointmentStatus.SCHEDULED, created_by=users[RoleEnum.RECEPTIONIST].id)
        db.session.add(appointment); db.session.flush(); pending = pending_for(appointment); db.session.commit()
        def fail_resolution(*args, **kwargs): raise SQLAlchemyError("injected resolution failure")
        monkeypatch.setattr("src.api.controllers.appointment_controller.resolve_pending", fail_resolution)
        response = client.put(f"/api/v1/appointments/{appointment.id}/reschedule", headers=token(app, users[RoleEnum.RECEPTIONIST]), json={"scheduled_at": monday(10).isoformat()})
        assert response.status_code == 500
        db.session.expire_all(); assert Appointment.query.get(appointment.id).scheduled_at == start
        assert ReschedulePending.query.get(pending.id).status == ReschedulePendingStatus.PENDING
        assert availability.id is not None


def test_audit_contains_actor_clinic_action_entity_and_no_clinical_payload(app, client):
    with app.app_context():
        clinic, users, profile, _ = setup_clinic(); db.session.commit()
        response = client.post("/api/v1/doctor-availabilities", headers=token(app, users[RoleEnum.CLINIC_ADMIN]), json={"doctor_profile_id": profile.id, "weekday": 1, "start_time": "08:00", "end_time": "12:00"})
        assert response.status_code == 201
        log = AuditLog.query.filter_by(entity_type="DoctorAvailability", entity_id=str(response.get_json()["id"])).one()
        assert log.user_id == users[RoleEnum.CLINIC_ADMIN].id and log.clinic_id == clinic.id and log.action == "CREATE"
        assert not ({"diagnosis", "medical_record", "ai_analysis", "documents"} & set(log.metadata_json))


def test_slots_enforce_maximum_31_day_range(app, client):
    with app.app_context():
        clinic, users, profile, _ = setup_clinic(); db.session.commit()
        response = client.get("/api/v1/doctor-availabilities/slots", headers=token(app, users[RoleEnum.RECEPTIONIST]), query_string={"doctor_profile_id": profile.id, "date_from": "2027-01-01", "date_to": "2027-02-01", "duration_minutes": 30})
        assert response.status_code == 422
