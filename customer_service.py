import hmac
import json
import logging
import os
import uuid
from collections import defaultdict

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

import models
from base import Base
from database import engine, get_db
from schemas import CustomerCreate, CustomerLogin, OrderCreate, OrderStatusUpdate


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
INTERNAL_EVENT_TOKEN = os.getenv("INTERNAL_EVENT_TOKEN", "local-development-token")

Base.metadata.create_all(bind=engine, tables=models.CUSTOMER_TABLES)
app = FastAPI(title="Customer Orders - Customer Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv(
        "WEB_ORIGINS", "http://localhost:8001,http://127.0.0.1:8001"
    ).split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


class CustomerConnections:
    def __init__(self):
        self.connections: dict[int, set[WebSocket]] = defaultdict(set)
        self.inventory_connections: set[WebSocket] = set()

    async def connect(self, customer_id: int, websocket: WebSocket):
        await websocket.accept()
        self.connections[customer_id].add(websocket)

    def disconnect(self, customer_id: int, websocket: WebSocket):
        self.connections[customer_id].discard(websocket)
        if not self.connections[customer_id]:
            del self.connections[customer_id]

    async def broadcast(self, customer_id: int, event: dict):
        disconnected = []
        for websocket in self.connections.get(customer_id, set()):
            try:
                await websocket.send_json(event)
            except (WebSocketDisconnect, RuntimeError):
                disconnected.append(websocket)
        for websocket in disconnected:
            self.disconnect(customer_id, websocket)

    async def broadcast_inventory(self, event: dict):
        disconnected = []
        for websocket in self.inventory_connections:
            try:
                await websocket.send_json(event)
            except (WebSocketDisconnect, RuntimeError):
                disconnected.append(websocket)
        for websocket in disconnected:
            self.inventory_connections.discard(websocket)


connections = CustomerConnections()


def verify_internal_token(
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
):
    if not x_internal_token or not hmac.compare_digest(x_internal_token, INTERNAL_EVENT_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid internal event token")


@app.get("/health")
def health():
    return {"status": "healthy", "service": "customer"}


@app.get("/customers")
def list_customers(db: Session = Depends(get_db)):
    return db.query(models.Customer).order_by(models.Customer.id).all()


@app.get("/customers/{customer_id}")
def get_customer(customer_id: int, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


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


@app.post("/customer-login")
def customer_login(customer: CustomerLogin, db: Session = Depends(get_db)):
    existing = db.query(models.Customer).filter(
        models.Customer.name == customer.name,
        models.Customer.email == customer.email,
    ).first()
    if existing is None:
        raise HTTPException(status_code=401, detail="Customer not found")
    return {"id": existing.id, "name": existing.name, "email": existing.email}


@app.get("/products")
def get_products(db: Session = Depends(get_db)):
    return db.query(models.Product).order_by(models.Product.id).all()


@app.post("/customers/{customer_id}/orders")
def create_order(customer_id: int, order: OrderCreate, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    product = db.query(models.Product).filter(models.Product.id == order.product_id).first()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.stock < order.quantity:
        raise HTTPException(status_code=400, detail=f"Not enough stock, only {product.stock} left")

    new_order = models.Order(
        customer_id=customer_id,
        product_id=order.product_id,
        quantity=order.quantity,
        delivery_address=order.delivery_address,
        latitude=order.latitude,
        longitude=order.longitude,
    )
    db.add(new_order)
    product.stock -= order.quantity
    db.flush()
    db.add(models.OrderStatusHistory(order_id=new_order.id, old_status=None, new_status="pending"))
    event_id = str(uuid.uuid4())
    event_payload = {
        "order_id": new_order.id,
        "customer_id": customer.id,
        "customer_name": customer.name,
        "product_id": product.id,
        "product_name": product.name,
        "quantity": new_order.quantity,
        "status": new_order.status,
        "stock_remaining": product.stock,
    }
    db.add(
        models.DomainEventOutbox(
            id=event_id,
            event_type="order.created",
            payload=json.dumps(event_payload),
        )
    )
    db.commit()
    db.refresh(new_order)
    return new_order


@app.get("/customers/{customer_id}/orders")
def list_orders(customer_id: int, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return (
        db.query(models.Order)
        .filter(models.Order.customer_id == customer_id)
        .order_by(models.Order.id)
        .all()
    )


@app.get("/customers/{customer_id}/notifications")
def list_notifications(customer_id: int, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return (
        db.query(models.Notification)
        .filter(models.Notification.customer_id == customer_id)
        .order_by(models.Notification.id.desc())
        .all()
    )


@app.get("/internal/staff/customers", dependencies=[Depends(verify_internal_token)])
def internal_list_customers(db: Session = Depends(get_db)):
    return db.query(models.Customer).order_by(models.Customer.id).all()


@app.post("/internal/staff/customers", dependencies=[Depends(verify_internal_token)])
def internal_create_customer(customer: CustomerCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Customer).filter(models.Customer.email == customer.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    new_customer = models.Customer(name=customer.name, email=customer.email)
    db.add(new_customer)
    db.commit()
    db.refresh(new_customer)
    return new_customer


@app.get("/internal/staff/products", dependencies=[Depends(verify_internal_token)])
def internal_list_products(db: Session = Depends(get_db)):
    return db.query(models.Product).order_by(models.Product.id).all()


@app.get("/internal/staff/customers/{customer_id}/orders",
         dependencies=[Depends(verify_internal_token)])
def internal_list_staff_customer_orders(customer_id: int, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return (
        db.query(models.Order)
        .filter(models.Order.customer_id == customer_id)
        .order_by(models.Order.id)
        .all()
    )


@app.get("/internal/staff/orders", dependencies=[Depends(verify_internal_token)])
def internal_list_staff_orders(db: Session = Depends(get_db)):
    rows = (
        db.query(models.Order, models.Customer.name, models.Product.name)
        .join(models.Customer, models.Customer.id == models.Order.customer_id)
        .join(models.Product, models.Product.id == models.Order.product_id)
        .order_by(models.Order.id.desc())
        .all()
    )
    result = []
    for order, customer_name, product_name in rows:
        item = {
            column.name: getattr(order, column.name)
            for column in models.Order.__table__.columns
        }
        item["customer_name"] = customer_name
        item["product_name"] = product_name
        result.append(item)
    return result


@app.patch("/internal/staff/orders/{order_id}/status",
           dependencies=[Depends(verify_internal_token)])
def internal_update_order_status(
    order_id: int, update: OrderStatusUpdate, db: Session = Depends(get_db)
):
    allowed_transitions = {
        "pending": {"paid"},
        "paid": {"shipped"},
        "shipped": {"delivered"},
        "delivered": set(),
    }
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    current_status = order.status
    if update.status not in allowed_transitions.get(current_status, set()):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status transition from {current_status} to {update.status}",
        )

    event_id = str(uuid.uuid4())
    event_payload = {
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
            event_type="order.status_changed",
            payload=json.dumps(event_payload),
        )
    )
    db.commit()
    db.refresh(order)
    result = {
        column.name: getattr(order, column.name)
        for column in models.Order.__table__.columns
    }
    result["event_delivery"] = "pending"
    result["event_id"] = event_id
    return result


@app.websocket("/ws/customer-updates")
async def customer_inventory_updates(websocket: WebSocket):
    await websocket.accept()
    connections.inventory_connections.add(websocket)
    try:
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        connections.inventory_connections.discard(websocket)


@app.websocket("/ws/customers/{customer_id}/orders")
async def customer_order_updates(websocket: WebSocket, customer_id: int):
    await connections.connect(customer_id, websocket)
    try:
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        connections.disconnect(customer_id, websocket)


@app.post("/internal/events")
async def deliver_internal_event(
    event: dict,
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
):
    verify_internal_token(x_internal_token)
    payload = event.get("payload", {})
    if event.get("event_type") == "order.created":
        customer_id = payload.get("customer_id")
        product_id = payload.get("product_id")
        stock_remaining = payload.get("stock_remaining")
        if not isinstance(customer_id, int) or not isinstance(product_id, int):
            raise HTTPException(status_code=422, detail="Event is missing order identifiers")
        await connections.broadcast(customer_id, event)
        await connections.broadcast_inventory(
            {
                "event_id": event.get("event_id"),
                "event_type": "inventory.updated",
                "payload": {
                    "product_id": product_id,
                    "stock_remaining": stock_remaining,
                },
            }
        )
    elif event.get("event_type") == "order.status_changed":
        customer_id = payload.get("customer_id")
        if not isinstance(customer_id, int):
            raise HTTPException(status_code=422, detail="Event is missing a valid customer_id")
        await connections.broadcast(customer_id, event)
    else:
        raise HTTPException(status_code=422, detail="Unsupported customer event type")
    return {"delivered": True}


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def customer_home():
    return FileResponse("static/customer-view.html")


@app.get("/staff")
def staff_home(request: Request):
    return RedirectResponse(url=f"{request.url.scheme}://{request.url.hostname}:8001/")
