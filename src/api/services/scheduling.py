"""Single source of truth for half-open scheduling intervals."""
from datetime import date, datetime, time, timedelta

from ..database.extensions import db
from ..models_db.models import (
    Appointment,
    AppointmentStatus,
    AuditLog,
    DoctorAvailability,
    DoctorClinic,
    DoctorProfile,
    ReschedulePending,
    ReschedulePendingStatus,
    ScheduleBlock,
    User,
)


VALID_DURATIONS = (30, 60)
SLOT_STEP_MINUTES = 30
MAX_SLOT_RANGE_DAYS = 31
ACTIVE_APPOINTMENT_STATUSES = (
    AppointmentStatus.SCHEDULED,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.IN_PROGRESS,
    AppointmentStatus.RESCHEDULED,
)


def naive(value: datetime) -> datetime:
    """Store clinic wall-clock datetimes consistently with the legacy naive schema."""
    if value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


def utcnow_naive() -> datetime:
    return datetime.now()


def interval_end(start: datetime, duration_minutes: int) -> datetime:
    return start + timedelta(minutes=duration_minutes)


def overlaps(start_a, end_a, start_b, end_b) -> bool:
    return start_a < end_b and end_a > start_b


def doctor_belongs_to_clinic(doctor_profile_id: int, clinic_id: int) -> bool:
    profile = DoctorProfile.query.get(doctor_profile_id)
    if not profile:
        return False
    user = User.query.get(profile.user_id)
    if user and user.clinic_id == clinic_id:
        return True
    return DoctorClinic.query.filter_by(
        doctor_profile_id=doctor_profile_id, clinic_id=clinic_id
    ).first() is not None


def is_contained_in_availability(clinic_id, doctor_profile_id, start, duration_minutes):
    start = naive(start)
    end = interval_end(start, duration_minutes)
    availability = DoctorAvailability.query.filter(
        DoctorAvailability.clinic_id == clinic_id,
        DoctorAvailability.doctor_profile_id == doctor_profile_id,
        DoctorAvailability.weekday == start.isoweekday(),
        DoctorAvailability.start_time <= start.time(),
        DoctorAvailability.end_time >= end.time(),
    ).first()
    return availability is not None and end.date() == start.date()


def interval_is_available(clinic_id, doctor_profile_id, start, duration_minutes):
    """Return (ok, code, message) in the business validation order."""
    if duration_minutes not in VALID_DURATIONS:
        return False, 422, "duration_minutes deve ser 30 ou 60"
    start = naive(start)
    end = interval_end(start, duration_minutes)
    if not is_contained_in_availability(clinic_id, doctor_profile_id, start, duration_minutes):
        return False, 422, "Intervalo fora da disponibilidade médica"
    block = ScheduleBlock.query.filter(
        ScheduleBlock.clinic_id == clinic_id,
        ScheduleBlock.doctor_profile_id == doctor_profile_id,
        ScheduleBlock.start_time < end,
        ScheduleBlock.end_time > start,
    ).first()
    if block:
        return False, 409, "Horário bloqueado"
    return True, None, None


def conflicting_appointment(clinic_id, doctor_profile_id, start, duration_minutes, exclude_id=None):
    start = naive(start)
    end = interval_end(start, duration_minutes)
    # 60 minutes is the maximum supported duration, bounding the SQL scan.
    query = Appointment.query.filter(
        Appointment.clinic_id == clinic_id,
        Appointment.doctor_profile_id == doctor_profile_id,
        Appointment.scheduled_at >= start - timedelta(minutes=max(VALID_DURATIONS)),
        Appointment.scheduled_at < end,
        Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
    )
    if exclude_id is not None:
        query = query.filter(Appointment.id != exclude_id)
    for appointment in query.all():
        other_end = interval_end(appointment.scheduled_at, appointment.duration_minutes or 30)
        if overlaps(start, end, appointment.scheduled_at, other_end):
            return appointment
    return None


def validate_booking(clinic_id, doctor_profile_id, start, duration_minutes, exclude_id=None):
    ok, status, message = interval_is_available(
        clinic_id, doctor_profile_id, start, duration_minutes
    )
    if not ok:
        return ok, status, message
    if conflicting_appointment(
        clinic_id, doctor_profile_id, start, duration_minutes, exclude_id
    ):
        return False, 409, "Conflito de agenda"
    return True, None, None


def appointments_overlapping(clinic_id, doctor_profile_id, start, end):
    rows = Appointment.query.filter(
        Appointment.clinic_id == clinic_id,
        Appointment.doctor_profile_id == doctor_profile_id,
        Appointment.scheduled_at >= start - timedelta(minutes=max(VALID_DURATIONS)),
        Appointment.scheduled_at < end,
        Appointment.scheduled_at >= utcnow_naive(),
        Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
    ).all()
    return [
        row for row in rows
        if overlaps(start, end, row.scheduled_at, interval_end(row.scheduled_at, row.duration_minutes or 30))
    ]


def future_invalid_appointments(clinic_id, doctor_profile_id):
    rows = Appointment.query.filter(
        Appointment.clinic_id == clinic_id,
        Appointment.doctor_profile_id == doctor_profile_id,
        Appointment.scheduled_at >= utcnow_naive(),
        Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
    ).all()
    invalid = []
    for appointment in rows:
        if not is_contained_in_availability(
            clinic_id, doctor_profile_id, appointment.scheduled_at,
            appointment.duration_minutes or 30,
        ):
            invalid.append(appointment)
    return invalid


def ensure_pending(
    appointment,
    source,
    reason,
    actor_id,
    source_entity_type=None,
    source_entity_id=None,
):
    existing = ReschedulePending.query.filter_by(
        open_appointment_id=appointment.id,
        status=ReschedulePendingStatus.PENDING,
    ).first()
    if existing:
        existing.source = source
        existing.reason = reason
        existing.originated_by = actor_id
        existing.source_entity_type = source_entity_type
        existing.source_entity_id = source_entity_id
        db.session.add(AuditLog(
            clinic_id=appointment.clinic_id, user_id=actor_id, action="UPDATE",
            entity_type="ReschedulePending", entity_id=str(existing.id),
            metadata_json={"source": source, "appointment_id": appointment.id},
        ))
        return existing, False
    pending = ReschedulePending(
        clinic_id=appointment.clinic_id,
        appointment_id=appointment.id,
        open_appointment_id=appointment.id,
        status=ReschedulePendingStatus.PENDING,
        source=source,
        reason=reason,
        originated_by=actor_id,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
    )
    db.session.add(pending)
    db.session.flush()
    db.session.add(AuditLog(
        clinic_id=appointment.clinic_id, user_id=actor_id, action="CREATE",
        entity_type="ReschedulePending", entity_id=str(pending.id),
        metadata_json={"source": source, "appointment_id": appointment.id},
    ))
    return pending, True


def resolve_pending(appointment_id, actor_id, resolution_reason=None):
    pending = ReschedulePending.query.filter_by(
        open_appointment_id=appointment_id,
        status=ReschedulePendingStatus.PENDING,
    ).first()
    if pending:
        pending.status = ReschedulePendingStatus.RESOLVED
        pending.open_appointment_id = None
        pending.resolved_at = utcnow_naive()
        pending.resolved_by = actor_id
        db.session.add(AuditLog(
            clinic_id=pending.clinic_id, user_id=actor_id, action="RESOLVE",
            entity_type="ReschedulePending", entity_id=str(pending.id),
            metadata_json={"appointment_id": appointment_id, "reason": resolution_reason},
        ))
    return pending


def appointment_requires_reschedule(appointment):
    """Whether a future active appointment is invalid in the current agenda.

    The appointment itself is excluded from conflict detection.  This is used
    only when reconciling a pending source and intentionally checks every
    current scheduling rule, not merely the source that changed.
    """
    if appointment.status not in ACTIVE_APPOINTMENT_STATUSES:
        return False
    if appointment.scheduled_at < utcnow_naive():
        return False
    ok, _, _ = validate_booking(
        appointment.clinic_id,
        appointment.doctor_profile_id,
        appointment.scheduled_at,
        appointment.duration_minutes or 30,
        exclude_id=appointment.id,
    )
    return not ok


def reconcile_block_pendings(block_id, actor_id):
    """Resolve only stale pendings originated by one edited schedule block.

    A single open pending is shared by all causes for an appointment.  Before
    resolving it we therefore revalidate the complete current agenda, so a
    different block, missing availability, or another active conflict keeps it
    open.  Resolved records are never deleted.
    """
    pendings = ReschedulePending.query.filter_by(
        source_entity_type="SCHEDULE_BLOCK",
        source_entity_id=block_id,
        status=ReschedulePendingStatus.PENDING,
    ).all()
    resolved = 0
    for pending in pendings:
        appointment = Appointment.query.get(pending.appointment_id)
        if appointment and not appointment_requires_reschedule(appointment):
            resolve_pending(
                appointment.id,
                actor_id,
                resolution_reason="block_no_longer_affects_appointment",
            )
            resolved += 1
    return resolved


def generate_slots(clinic_id, doctor_profile_id, date_from: date, date_to: date,
                   duration_minutes: int, exclude_appointment_id=None, limit=None):
    result = []
    current = date_from
    now = utcnow_naive()
    while current <= date_to:
        ranges = DoctorAvailability.query.filter_by(
            clinic_id=clinic_id,
            doctor_profile_id=doctor_profile_id,
            weekday=current.isoweekday(),
        ).order_by(DoctorAvailability.start_time).all()
        for available in ranges:
            cursor = datetime.combine(current, available.start_time)
            boundary = datetime.combine(current, available.end_time)
            duration = timedelta(minutes=duration_minutes)
            while cursor + duration <= boundary:
                if cursor > now:
                    ok, _, _ = validate_booking(
                        clinic_id, doctor_profile_id, cursor, duration_minutes,
                        exclude_id=exclude_appointment_id,
                    )
                    if ok:
                        result.append({
                            "start": cursor.isoformat(),
                            "end": (cursor + duration).isoformat(),
                            "duration_minutes": duration_minutes,
                        })
                        if limit and len(result) >= limit:
                            return result
                cursor += timedelta(minutes=SLOT_STEP_MINUTES)
        current += timedelta(days=1)
    return result
