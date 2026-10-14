import json
import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

import models
from broker import publish_order_event
from database import Base, engine, get_db
from schemas import CustomerCreate, OrderStatusUpdate, StaffLogin


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_TRANSITIONS = {
    "pending": {"paid"},
    "paid": {"shipped"},
    "shipped": {"delivered"},
    "delivered": set(),
}

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Customer Orders - Staff Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv(
        "WEB_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
    ).split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "healthy", "service": "staff"}


@app.post("/staff-login")
def staff_login(staff: StaffLogin, db: Session = Depends(get_db)):
    if staff.password != os.getenv("STAFF_PASSWORD", "dummypw"):
        raise HTTPException(status_code=401, detail="Invalid password")
    existing = db.query(models.Staff).filter(models.Staff.email == staff.email).first()
    if existing is None:
        raise HTTPException(status_code=401, detail="Staff email not found")
    return {"id": existing.id, "name": existing.name, "email": existing.email}


@app.get("/staff/customers")
def list_staff_customers(db: Session = Depends(get_db)):
    return db.query(models.Customer).order_by(models.Customer.id).all()


@app.post("/staff/customers")
def create_staff_customer(customer: CustomerCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Customer).filter(models.Customer.email == customer.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    new_customer = models.Customer(name=customer.name, email=customer.email)
    db.add(new_customer)
    db.commit()
    db.refresh(new_customer)
    return new_customer


@app.get("/staff/products")
def list_staff_products(db: Session = Depends(get_db)):
    return db.query(models.Product).order_by(models.Product.id).all()


@app.get("/staff/customers/{customer_id}/orders")
def list_staff_customer_orders(customer_id: int, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return (
        db.query(models.Order)
        .filter(models.Order.customer_id == customer_id)
        .order_by(models.Order.id)
        .all()
    )


@app.get("/staff/orders")
def list_staff_orders(db: Session = Depends(get_db)):
    orders = db.query(models.Order).order_by(models.Order.id.desc()).all()
    customers = {c.id: c.name for c in db.query(models.Customer).all()}
    products = {p.id: p.name for p in db.query(models.Product).all()}
    result = []
    for order in orders:
        item = {column.name: getattr(order, column.name) for column in models.Order.__table__.columns}
        item["customer_name"] = customers.get(order.customer_id, "Unknown customer")
        item["product_name"] = products.get(order.product_id, "Unknown product")
        result.append(item)
    return result


@app.patch("/staff/orders/{order_id}")
def update_order_status(
    order_id: int, update: OrderStatusUpdate, db: Session = Depends(get_db)
):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    current_status = order.status
    if update.status not in ALLOWED_TRANSITIONS.get(current_status, set()):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status transition from {current_status} to {update.status}",
        )

    event_id = str(uuid.uuid4())
    event_type = "order.status_changed"
    payload = {
        "customer_id": order.customer_id,
        "order_id": order.id,
        "old_status": current_status,
        "new_status": update.status,
    }
    order.status = update.status
    db.add(
        models.OrderStatusHistory(
            order_id=order.id,
            old_status=current_status,
            new_status=update.status,
        )
    )
    db.add(
        models.DomainEventOutbox(
            id=event_id,
            event_type=event_type,
            payload=json.dumps(payload),
        )
    )
    db.commit()
    db.refresh(order)

    published = publish_order_event(event_id, event_type, payload)
    if published:
        outbox_event = db.query(models.DomainEventOutbox).filter(
            models.DomainEventOutbox.id == event_id
        ).first()
        if outbox_event is not None:
            outbox_event.published_at = datetime.now(timezone.utc)
            db.commit()
    else:
        logger.info("Order event %s is queued for broker retry", event_id)

    result = {column.name: getattr(order, column.name) for column in models.Order.__table__.columns}
    result["event_delivery"] = "published" if published else "pending"
    result["event_id"] = event_id
    return result


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def staff_home():
    return FileResponse("static/index.html")
