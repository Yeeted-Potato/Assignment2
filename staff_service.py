import hmac
import logging
import os

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import models
from schemas import CustomerCreate, OrderStatusUpdate, StaffLogin
from staff_database import get_staff_db, initialize_staff_database


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
INTERNAL_EVENT_TOKEN = os.getenv("INTERNAL_EVENT_TOKEN", "local-development-token")
CUSTOMER_SERVICE_URL = os.getenv("CUSTOMER_SERVICE_URL", "http://127.0.0.1:8000")
initialize_staff_database()
app = FastAPI(title="Customer Orders - Staff Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv(
        "WEB_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
    ).split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


def customer_service_request(method: str, path: str, body: dict | None = None):
    try:
        response = httpx.request(
            method,
            f"{CUSTOMER_SERVICE_URL}{path}",
            json=body,
            headers={"X-Internal-Token": INTERNAL_EVENT_TOKEN},
            timeout=5.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", exc.response.text)
        except ValueError:
            detail = exc.response.text
        raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
    except httpx.HTTPError as exc:
        logger.exception("Customer service request failed: %s %s", method, path)
        raise HTTPException(
            status_code=503,
            detail="Customer service is unavailable; please retry.",
        ) from exc
    return response.json()


class StaffConnections:
    def __init__(self):
        self.connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.connections.discard(websocket)

    async def broadcast(self, event: dict):
        disconnected = []
        for websocket in self.connections:
            try:
                await websocket.send_json(event)
            except (WebSocketDisconnect, RuntimeError):
                disconnected.append(websocket)
        for websocket in disconnected:
            self.disconnect(websocket)


staff_connections = StaffConnections()


@app.get("/health")
def health():
    return {"status": "healthy", "service": "staff"}


@app.post("/staff-login")
def staff_login(staff: StaffLogin, db=Depends(get_staff_db)):
    if staff.password != os.getenv("STAFF_PASSWORD", "dummypw"):
        raise HTTPException(status_code=401, detail="Invalid password")
    existing = db.query(models.Staff).filter(models.Staff.email == staff.email).first()
    if existing is None:
        raise HTTPException(status_code=401, detail="Staff email not found")
    return {"id": existing.id, "name": existing.name, "email": existing.email}


@app.get("/staff/customers")
def list_staff_customers():
    return customer_service_request("GET", "/internal/staff/customers")


@app.post("/staff/customers")
def create_staff_customer(customer: CustomerCreate):
    return customer_service_request(
        "POST", "/internal/staff/customers", customer.model_dump()
    )


@app.get("/staff/products")
def list_staff_products():
    return customer_service_request("GET", "/internal/staff/products")


@app.get("/staff/customers/{customer_id}/orders")
def list_staff_customer_orders(customer_id: int):
    return customer_service_request(
        "GET", f"/internal/staff/customers/{customer_id}/orders"
    )


@app.get("/staff/orders")
def list_staff_orders():
    return customer_service_request("GET", "/internal/staff/orders")


@app.get("/staff/notifications")
def list_staff_notifications(db=Depends(get_staff_db)):
    return (
        db.query(models.StaffNotification)
        .order_by(models.StaffNotification.id.desc())
        .limit(50)
        .all()
    )


@app.websocket("/ws/staff/orders")
async def staff_order_updates(websocket: WebSocket):
    await staff_connections.connect(websocket)
    try:
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        staff_connections.disconnect(websocket)


@app.post("/internal/events")
async def deliver_internal_event(
    event: dict,
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
):
    if not x_internal_token or not hmac.compare_digest(x_internal_token, INTERNAL_EVENT_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid internal event token")
    if event.get("event_type") != "order.created":
        raise HTTPException(status_code=422, detail="Unsupported staff event type")
    payload = event.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("order_id"), int):
        raise HTTPException(status_code=422, detail="Event is missing a valid order_id")
    await staff_connections.broadcast(event)
    return {"delivered": True}


@app.patch("/staff/orders/{order_id}")
def update_order_status(
    order_id: int, update: OrderStatusUpdate
):
    return customer_service_request(
        "PATCH",
        f"/internal/staff/orders/{order_id}/status",
        update.model_dump(),
    )


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def staff_home():
    return FileResponse("static/index.html")
