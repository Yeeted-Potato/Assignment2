from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
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
    product_id: int
    quantity: int = Field(gt=0)
    delivery_address: str | None = None
    latitude: float | None = None
    longitude: float | None = None

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
    
    #check the product exists
    product = db.query(models.Product).filter(models.Product.id == order.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    #check there is enough stock for this order
    if product.stock < order.quantity:
        raise HTTPException(status_code=400, detail=f"Not enough stock, only {product.stock} left")
   
    #check there is an address or a location to deliver to
    if not order.delivery_address and order.latitude is None:
        raise HTTPException(status_code=422, detail="Give a delivery address or allow location")
        
    #create the order with the new columns
    new_order = models.Order(
        customer_id=customer_id,
        product_id=order.product_id,
        quantity=order.quantity,
        delivery_address=order.delivery_address,
        latitude=order.latitude,
        longitude=order.longitude,
    )
    db.add(new_order)

    #take the ordered amount out of stock
    product.stock -= order.quantity

    #flush gives the new order its id so the history row can use it
    db.flush()
    db.add(models.OrderStatusHistory(order_id=new_order.id, old_status=None, new_status="pending"))

    #save the order, stock change and history all together
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
    #save the change in the history table
    db.add(models.OrderStatusHistory(order_id=order.id, old_status=current_status, new_status=new_status))
    db.commit()
    db.refresh(order)
    return order

#create a path to get all products from the database
@app.get("/products")
def get_products(db: Session = Depends(get_db)):
    products = db.query(models.Product).all()
    return products

class CustomerLogin(BaseModel):
    name: str
    email: str


@app.post("/customer-login")
def customer_login(customer: CustomerLogin, db: Session = Depends(get_db)):
    existing = db.query(models.Customer).filter(
        models.Customer.name == customer.name,
        models.Customer.email == customer.email
    ).first()

    if not existing:
        raise HTTPException(status_code=401, detail="Customer not found")

    return {
        "id": existing.id,
        "name": existing.name,
        "email": existing.email
    }
class StaffLogin(BaseModel):
    email: str
    password: str


@app.post("/staff-login")
def staff_login(staff: StaffLogin, db: Session = Depends(get_db)):
    if staff.password != "dummypw":
        raise HTTPException(status_code=401, detail="Invalid password")

    existing = db.query(models.Staff).filter(
        models.Staff.email == staff.email
    ).first()

    if not existing:
        raise HTTPException(status_code=401, detail="Staff email not found")

    return {
        "id": existing.id,
        "name": existing.name,
        "email": existing.email
    }
#serve files from the static folder
#app.mount("/", StaticFiles(directory="static", html=True), name="static")

#serve files from the static folder
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def customer_home():
    return FileResponse("static/customer-view.html")

@app.get("/staff")
def staff_home():
    return FileResponse("static/index.html")