from ..database.extensions import db
from ..models_db.models import Clinic, User, RoleEnum, DoctorProfile


def run_seed():
    super_admin = User.query.filter_by(email="superadmin@dermato.local").first()
    if not super_admin:
        super_admin = User(name="Super Admin", email="superadmin@dermato.local", role=RoleEnum.SUPER_ADMIN, clinic_id=None, is_active=True)
        super_admin.set_password("Admin123!")
        db.session.add(super_admin)
    elif super_admin.is_active is not True:
        super_admin.is_active = True

    clinic = Clinic.query.filter_by(name="Clínica Dermatológica Exemplo").first()
    if not clinic:
        clinic = Clinic(name="Clínica Dermatológica Exemplo", is_active=True)
        db.session.add(clinic)
        db.session.flush()

    for name, email, role in [
        ("Admin Clínica", "admin@dermato.local", RoleEnum.CLINIC_ADMIN),
        ("Médico Exemplo", "medico@dermato.local", RoleEnum.DOCTOR),
        ("Recepção Exemplo", "recepcao@dermato.local", RoleEnum.RECEPTIONIST),
    ]:
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(name=name, email=email, role=role, clinic_id=clinic.id, is_active=True)
            user.set_password("Admin123!")
            db.session.add(user)
            db.session.flush()
            if role == RoleEnum.DOCTOR:
                dp = DoctorProfile.query.filter_by(user_id=user.id).first()
                if not dp:
                    db.session.add(DoctorProfile(user_id=user.id, crm="CRM-TESTE-0001", phone="11999999999"))
        elif user.is_active is not True:
            user.is_active = True

    db.session.commit()
