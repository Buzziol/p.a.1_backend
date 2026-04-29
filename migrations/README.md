Migrations serão geradas com Flask-Migrate/Alembic.

Comandos:
1) export FLASK_APP=src.api.app:create_app
2) flask db init
3) flask db migrate -m "init foundation"
4) flask db upgrade
