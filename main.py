from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from database import Base, engine, get_db
from sqlalchemy.orm import Session
import models

app = FastAPI()

#order status transitions allowed in the system
ALLOWED_TRANSITIONS = {
    "pending": ["paid"],
    "paid": ["shipped"],
    "shipped": ["delivered"],
    "delivered": [],
}

#create each table in the database
Base.metadata.create_all(bind=engine)

#define the shape of the data for customers and orders using Pydantic models
class CustomerCreate(BaseModel):
    name: str = Field(min_length=1)
    email: str = Field(min_length=1)
    
class OrderCreate(BaseModel):
    product: str
    quantity: int

class OrderStatusUpdate(BaseModel):
    status: str


@app.get("/health")
def health():
    return {"status": "healthy"}


#create a path to get a specific customer by id, find that customer in the database and return their information
@app.get("/customers/{customer_id}")
def get_customer(customer_id: int, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer

#give all customers in the database
@app.get("/customers")
def list_customers(db: Session = Depends(get_db)):
    return db.query(models.Customer).all()

#create a path for customers to create a new customer, with columns of info for the database
@app.post("/customers")
def create_customer(customer: CustomerCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Customer).filter(models.Customer.email == customer.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    new_customer = models.Customer(name=customer.name, email=customer.email)
    db.add(new_customer)
    db.commit()
    db.refresh(new_customer)
    return new_customer

#create a path for customers to create an order, match customer id and have columns of info for database
@app.post("/customers/{customer_id}/orders")
def create_order(customer_id: int, order: OrderCreate, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    new_order = models.Order(
        customer_id=customer_id,
        product=order.product,
        quantity=order.quantity,
    )
    
    db.add(new_order)
    db.commit()
    db.refresh(new_order)
    return new_order
    
#create a path to list orders for a specific customer, match customer id and return all their orders
@app.get("/customers/{customer_id}/orders")
def list_orders(customer_id: int, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    return db.query(models.Order).filter(models.Order.customer_id == customer_id).all()

#update order status, match order id and check if the new status is allowed
@app.patch("/orders/{order_id}")
def update_order_status(order_id: int, update: OrderStatusUpdate, db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    current_status = order.status
    new_status = update.status
    
    if new_status not in ALLOWED_TRANSITIONS[current_status]:
        raise HTTPException(status_code=400, 
                            detail=f"Invalid status transition from {current_status} to {new_status}"
                            )
    
    order.status = new_status
    db.commit()
    db.refresh(order)
    return order

#serve files from the static folder
app.mount("/", StaticFiles(directory="static", html=True), name="static")
