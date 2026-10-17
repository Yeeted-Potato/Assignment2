import settings  # noqa: F401  loads .env before the values below are read
import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from base import Base


STAFF_DATABASE_URL = os.getenv("STAFF_DATABASE_URL", "sqlite:///./staff.db")
connect_args = {"check_same_thread": False} if STAFF_DATABASE_URL.startswith("sqlite") else {}
staff_engine = create_engine(STAFF_DATABASE_URL, connect_args=connect_args)

if STAFF_DATABASE_URL.startswith("sqlite"):
    @event.listens_for(staff_engine, "connect")
    def turn_on_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

StaffSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=staff_engine,
)


def get_staff_db():
    db = StaffSessionLocal()
    try:
        yield db
    finally:
        db.close()


def initialize_staff_database(database_engine=staff_engine):
    from models import STAFF_TABLES

    Base.metadata.create_all(bind=database_engine, tables=STAFF_TABLES)
