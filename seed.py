#fills both service-owned databases with test accounts and sample data
#run with: python seed.py (this deletes all existing data first)
from base import Base
from database import engine, SessionLocal
import models
from models import CUSTOMER_TABLES, STAFF_TABLES
from staff_database import StaffSessionLocal, initialize_staff_database, staff_engine
from scripts.migrate_staff_accounts import remove_legacy_staff_tables


def seed(
    customer_engine=engine,
    customer_session_factory=SessionLocal,
    staff_session_factory=StaffSessionLocal,
    staff_database_engine=staff_engine,
):
    #Reset only tables owned by each service in its own database.
    # Remove the old shared-schema staff tables before dropping orders, since
    # legacy staff_notifications may still have a foreign key to orders.
    remove_legacy_staff_tables(customer_engine)
    Base.metadata.drop_all(bind=customer_engine, tables=CUSTOMER_TABLES)
    Base.metadata.create_all(bind=customer_engine, tables=CUSTOMER_TABLES)
    Base.metadata.drop_all(bind=staff_database_engine, tables=STAFF_TABLES)
    initialize_staff_database(staff_database_engine)

    db = customer_session_factory()
    staff_db = staff_session_factory()

    try:
        #Customer-owned records
        evan = models.Customer(name="Evan", email="evan@test.com")
        bob = models.Customer(name="Bob", email="bob@test.com")

        #products to order
        keyboard = models.Product(name="Keyboard", price=49.99, stock=20)
        mouse = models.Product(name="Mouse", price=19.99, stock=50)
        monitor = models.Product(name="Monitor", price=249.00, stock=5)

        db.add_all([evan, bob, keyboard, mouse, monitor])
        db.commit()

        #Staff-owned account lives only in the staff database.
        sam = models.Staff(name="Sam", email="sam@test.com")
        staff_db.add(sam)
        staff_db.commit()
        print("Seed data added: 2 customers, 1 staff account, 3 products")
    finally:
        db.close()
        staff_db.close()
        
if __name__ == "__main__":
    seed()