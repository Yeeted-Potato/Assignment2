import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import consumer
import customer_service
import models
import staff_service
from database import Base, get_db


@pytest.fixture
def service_clients(tmp_path, monkeypatch):
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'test-orders.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=test_engine)
    test_session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_db():
        db = test_session()
        try:
            yield db
        finally:
            db.close()

    customer_service.app.dependency_overrides[get_db] = override_get_db
    staff_service.app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(staff_service, "publish_order_event", lambda *_args: False)

    db = test_session()
    customer = models.Customer(name="Evan", email="evan@test.com")
    product = models.Product(name="Keyboard", price=49.99, stock=5)
    staff = models.Staff(name="Sam", email="sam@test.com")
    db.add_all([customer, product, staff])
    db.commit()
    customer_id = customer.id
    product_id = product.id
    db.close()

    with TestClient(customer_service.app) as customer_client:
        with TestClient(staff_service.app) as staff_client:
            yield customer_client, staff_client, test_session, customer_id, product_id

    customer_service.app.dependency_overrides.clear()
    staff_service.app.dependency_overrides.clear()
    test_engine.dispose()


def test_customer_order_and_staff_status_workflow(service_clients):
    customer_client, staff_client, test_session, customer_id, product_id = service_clients

    created = customer_client.post(
        f"/customers/{customer_id}/orders",
        json={
            "product_id": product_id,
            "quantity": 2,
            "delivery_address": "123 Queen Street",
        },
    )
    assert created.status_code == 200
    assert all(
        key in created.json()
        for key in (
            "id",
            "customer_id",
            "product_id",
            "quantity",
            "status",
            "delivery_address",
            "latitude",
            "longitude",
        )
    )
    order_id = created.json()["id"]

    invalid = customer_client.post(
        f"/customers/{customer_id}/orders",
        json={"product_id": product_id, "quantity": 1},
    )
    assert invalid.status_code == 422

    updated = staff_client.patch(
        f"/staff/orders/{order_id}",
        json={"status": "paid"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "paid"
    assert updated.json()["event_delivery"] == "pending"

    invalid_transition = staff_client.patch(
        f"/staff/orders/{order_id}",
        json={"status": "delivered"},
    )
    assert invalid_transition.status_code == 400

    orders = customer_client.get(f"/customers/{customer_id}/orders").json()
    assert orders[0]["status"] == "paid"
    db = test_session()
    try:
        assert db.query(models.Product).filter_by(id=product_id).one().stock == 3
        outbox = db.query(models.DomainEventOutbox).one()
        assert outbox.published_at is None
        assert json.loads(outbox.payload)["new_status"] == "paid"
    finally:
        db.close()


def test_notification_consumer_is_idempotent(service_clients):
    _, _, test_session, customer_id, _ = service_clients
    event = {
        "event_id": "same-event-twice",
        "event_type": "order.status_changed",
        "payload": {
            "customer_id": customer_id,
            "order_id": 41,
            "old_status": "pending",
            "new_status": "paid",
        },
    }
    db = test_session()
    try:
        first = consumer.persist_notification(db, event)
        second = consumer.persist_notification(db, event)
        assert first.id == second.id
        assert db.query(models.Notification).count() == 1
    finally:
        db.close()


def test_customer_websocket_receives_internal_order_event(service_clients):
    customer_client, _, _, customer_id, _ = service_clients
    event = {
        "event_id": "websocket-test-event",
        "event_type": "order.status_changed",
        "payload": {
            "customer_id": customer_id,
            "order_id": 12,
            "old_status": "pending",
            "new_status": "paid",
        },
    }
    with customer_client.websocket_connect(
        f"/ws/customers/{customer_id}/orders"
    ) as websocket:
        rejected = customer_client.post("/internal/events", json=event)
        assert rejected.status_code == 401

        delivered = customer_client.post(
            "/internal/events",
            json=event,
            headers={"X-Internal-Token": "local-development-token"},
        )
        assert delivered.status_code == 200
        assert websocket.receive_json() == event


def test_services_have_distinct_route_responsibilities():
    customer_paths = {route.path for route in customer_service.app.routes}
    staff_paths = {route.path for route in staff_service.app.routes}
    assert "/customers/{customer_id}/orders" in customer_paths
    assert "/staff/orders/{order_id}" in staff_paths
    assert "/staff/orders/{order_id}" not in customer_paths
