"""Copy existing staff accounts from the original shared DB into the staff DB."""

from datetime import datetime

from sqlalchemy import inspect, text

import models
from database import engine
from staff_database import StaffSessionLocal, initialize_staff_database


def migrate(
    customer_engine=engine,
    staff_session_factory=StaffSessionLocal,
    staff_database_engine=None,
):
    if staff_database_engine is None:
        staff_database_engine = staff_session_factory.kw["bind"]
    initialize_staff_database(staff_database_engine)
    inspector = inspect(customer_engine)
    has_legacy_staff = inspector.has_table("staff")
    has_legacy_notifications = inspector.has_table("staff_notifications")
    if not has_legacy_staff and not has_legacy_notifications:
        print("No legacy staff data found; no migration is needed.")
        return

    with customer_engine.connect() as connection:
        accounts = (
            connection.execute(
                text("SELECT id, name, email FROM staff ORDER BY id")
            ).mappings().all()
            if has_legacy_staff
            else []
        )
        notifications = (
            connection.execute(
                text(
                    "SELECT id, event_id, order_id, message, created_at "
                    "FROM staff_notifications ORDER BY id"
                )
            ).mappings().all()
            if has_legacy_notifications
            else []
        )

    db = staff_session_factory()
    try:
        existing_emails = {
            email for (email,) in db.query(models.Staff.email).all()
        }
        existing_event_ids = {
            event_id for (event_id,) in db.query(models.StaffNotification.event_id).all()
        }
        copied = 0
        for account in accounts:
            if account["email"] in existing_emails:
                continue
            db.add(
                models.Staff(
                    id=account["id"],
                    name=account["name"],
                    email=account["email"],
                )
            )
            existing_emails.add(account["email"])
            copied += 1
        copied_notifications = 0
        for notification in notifications:
            if notification["event_id"] in existing_event_ids:
                continue
            created_at = notification["created_at"]
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at)
            db.add(
                models.StaffNotification(
                    id=notification["id"],
                    event_id=notification["event_id"],
                    order_id=notification["order_id"],
                    message=notification["message"],
                    created_at=created_at,
                )
            )
            existing_event_ids.add(notification["event_id"])
            copied_notifications += 1
        db.commit()
        print(
            f"Migrated {copied} staff account(s) and "
            f"{copied_notifications} staff notification(s)."
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    remove_legacy_staff_tables(customer_engine)


def remove_legacy_staff_tables(customer_engine=engine):
    inspector = inspect(customer_engine)
    has_legacy_staff = inspector.has_table("staff")
    has_legacy_notifications = inspector.has_table("staff_notifications")
    has_staff_history_fk = inspector.has_table("order_status_history") and any(
        foreign_key.get("referred_table") == "staff"
        for foreign_key in inspector.get_foreign_keys("order_status_history")
    )
    if not has_legacy_staff and not has_legacy_notifications and not has_staff_history_fk:
        return

    raw_connection = customer_engine.raw_connection()
    cursor = raw_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("BEGIN IMMEDIATE")
        if has_staff_history_fk:
            cursor.execute(
                """
                CREATE TABLE order_status_history_new (
                    id INTEGER NOT NULL PRIMARY KEY,
                    order_id INTEGER NOT NULL,
                    old_status VARCHAR,
                    new_status VARCHAR NOT NULL,
                    changed_by_staff_id INTEGER,
                    changed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(order_id) REFERENCES orders (id)
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO order_status_history_new
                    (id, order_id, old_status, new_status, changed_by_staff_id, changed_at)
                SELECT id, order_id, old_status, new_status, changed_by_staff_id, changed_at
                FROM order_status_history
                """
            )
            cursor.execute("DROP TABLE order_status_history")
            cursor.execute(
                "ALTER TABLE order_status_history_new RENAME TO order_status_history"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS ix_order_status_history_id "
                "ON order_status_history (id)"
            )
        if has_legacy_notifications:
            cursor.execute("DROP TABLE staff_notifications")
        if has_legacy_staff:
            cursor.execute("DROP TABLE staff")
        raw_connection.commit()
        print("Removed the legacy staff tables and cross-database foreign key.")
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
        raw_connection.close()


if __name__ == "__main__":
    migrate()
