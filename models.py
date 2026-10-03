#get three tools from the sqlalchemy library
from sqlalchemy import Column, Integer, String, Float, ForeignKey, CheckConstraint
from database import Base

#create class with table name customers and three columns for database
class Customer(Base):
    __tablename__ = "customers"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)

#create class with table name staff and three columns for database
class Staff(Base):
    __tablename__ = "staff"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)

#create class with table name products, with name, price and stock columns
class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    price = Column(Float, nullable=False)
    stock = Column(Integer, nullable=False, default=0)

    #rules the database checks itself
    __table_args__ = (
        CheckConstraint("price >= 0", name="price_not_negative"),
        CheckConstraint("stock >= 0", name="stock_not_negative"),
    )
    
#create class order with columns and foreign key to customer table
class Order(Base):
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    product = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="pending")
    