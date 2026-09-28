"""Executable migration contract for the scheduling evolution."""
import importlib.util
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from alembic.migration import MigrationContext
from alembic.operations import Operations


MIGRATIONS = Path(__file__).parents[1] / "migrations" / "versions"


def _revision(filename, name):
    spec = importlib.util.spec_from_file_location(name, MIGRATIONS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(connection, revision, direction):
    op._proxy = Operations(MigrationContext.configure(connection))
    try:
        getattr(revision, direction)()
    finally:
        del op._proxy


def _legacy_schema(engine):
    metadata = sa.MetaData()
    sa.Table("clinics", metadata, sa.Column("id", sa.Integer, primary_key=True), sa.Column("name", sa.String(255)))
    sa.Table("users", metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table("doctor_profiles", metadata, sa.Column("id", sa.Integer, primary_key=True), sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id")))
    sa.Table("patients", metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table(
        "appointments", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("clinic_id", sa.Integer, sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("patient_id", sa.Integer, sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("doctor_profile_id", sa.Integer, sa.ForeignKey("doctor_profiles.id"), nullable=False),
        sa.Column("scheduled_at", sa.DateTime, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("notes", sa.Text),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
    )
    sa.Table(
        "schedule_blocks", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("clinic_id", sa.Integer, sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("doctor_profile_id", sa.Integer, sa.ForeignKey("doctor_profiles.id"), nullable=False),
        sa.Column("start_time", sa.DateTime, nullable=False),
        sa.Column("end_time", sa.DateTime, nullable=False),
        sa.Column("reason", sa.String(255)),
    )
    metadata.create_all(engine)
    return metadata


def test_scheduling_migrations_upgrade_backfill_downgrade_and_reupgrade(tmp_path):
    """Legacy appointments survive both directions and receive 30 minutes."""
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    legacy = _legacy_schema(engine)
    with engine.begin() as conn:
        conn.execute(legacy.tables["clinics"].insert(), {"id": 1, "name": "Legacy"})
        conn.execute(legacy.tables["users"].insert(), {"id": 1})
        conn.execute(legacy.tables["doctor_profiles"].insert(), {"id": 1, "user_id": 1})
        conn.execute(legacy.tables["patients"].insert(), {"id": 1})
        conn.execute(legacy.tables["appointments"].insert(), {
            "id": 7, "clinic_id": 1, "patient_id": 1, "doctor_profile_id": 1,
            "scheduled_at": datetime(2027, 1, 4, 9), "status": "SCHEDULED", "created_by": 1,
        })

    scheduling = _revision("20260909_0001_scheduling_availability.py", "scheduling_0001")
    origins = _revision("20260910_0002_reschedule_pending_origin.py", "scheduling_0002")
    with engine.begin() as conn:
        _run(conn, scheduling, "upgrade")
        _run(conn, origins, "upgrade")
        inspector = sa.inspect(conn)
        assert "duration_minutes" in {column["name"] for column in inspector.get_columns("appointments")}
        assert {"doctor_availabilities", "reschedule_pendings"} <= set(inspector.get_table_names())
        assert {"source_entity_type", "source_entity_id"} <= {column["name"] for column in inspector.get_columns("reschedule_pendings")}
        assert conn.execute(sa.text("SELECT duration_minutes FROM appointments WHERE id = 7")).scalar_one() == 30
        _run(conn, origins, "downgrade")
        _run(conn, scheduling, "downgrade")
        assert conn.execute(sa.text("SELECT id, clinic_id, patient_id FROM appointments WHERE id = 7")).one() == (7, 1, 1)
        _run(conn, scheduling, "upgrade")
        _run(conn, origins, "upgrade")
        assert conn.execute(sa.text("SELECT duration_minutes FROM appointments WHERE id = 7")).scalar_one() == 30
