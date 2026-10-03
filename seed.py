#fills the database with test accounts and sample data
#run with: python seed.py  (this deletes all existing data first)
from database import Base, engine, SessionLocal
import models

def seed():
    #delete every table and make them again so we always start the same
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    try:
        #test accounts for both roles
        evan = models.Customer(name="Evan", email="evan@test.com")
        bob = models.Customer(name="Bob", email="bob@test.com")
        sam = models.Staff(name="Sam", email="sam@test.com")

        #products to order
        keyboard = models.Product(name="Keyboard", price=49.99, stock=20)
        mouse = models.Product(name="Mouse", price=19.99, stock=50)
        monitor = models.Product(name="Monitor", price=249.00, stock=5)

        db.add_all([evan, bob, sam, keyboard, mouse, monitor])
        db.commit()
        print("Seed data added: 2 customers, 1 staff, 3 products")
    finally:
        db.close()
        
if __name__ == "__main__":
    seed()