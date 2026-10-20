import json
from datetime import datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

import consumer
import customer_service
import models
import staff_service
import seed as seed_module
from base import Base
from database import get_db
from scripts.migrate_staff_accounts import migrate as migrate_staff_accounts
from staff_database import get_staff_db


@pytest.fixture
def service_clients(tmp_path, monkeypatch):
    customer_engine = create_engine(
        f"sqlite:///{tmp_path / 'customer-test.db'}",
        connect_args={"check_same_thread": False},
    )
    staff_engine = create_engine(
        f"sqlite:///{tmp_path / 'staff-test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=customer_engine, tables=models.CUSTOMER_TABLES)
    Base.metadata.create_all(bind=staff_engine, tables=models.STAFF_TABLES)
    assert "orders" in inspect(customer_engine).get_table_names()
    assert "staff_notifications" not in inspect(customer_engine).get_table_names()
    assert "staff" in inspect(staff_engine).get_table_names()
    assert "orders" not in inspect(staff_engine).get_table_names()
    customer_session = sessionmaker(
        autocommit=False, autoflush=False, bind=customer_engine
    )
    staff_session = sessionmaker(autocommit=False, autoflush=False, bind=staff_engine)

    def override_customer_db():
        db = customer_session()
        try:
            yield db
        finally:
            db.close()

    def override_staff_db():
        db = staff_session()
        try:
            yield db
        finally:
            db.close()

    customer_service.app.dependency_overrides[get_db] = override_customer_db
    staff_service.app.dependency_overrides[get_staff_db] = override_staff_db

    db = customer_session()
    customer = models.Customer(name="Evan", email="evan@test.com")
    product = models.Product(name="Keyboard", price=49.99, stock=5)
    db.add_all([customer, product])
    db.commit()
    customer_id = customer.id
    product_id = product.id
    db.close()
    staff_db = staff_session()
    staff_db.add(models.Staff(name="Sam", email="sam@test.com"))
    staff_db.commit()
    staff_db.close()

    with TestClient(customer_service.app) as customer_client:
        with TestClient(staff_service.app) as staff_client:
            def customer_service_request(method, path, body=None):
                response = customer_client.request(
                    method,
                    path,
                    json=body,
                    headers={"X-Internal-Token": "local-development-token"},
                )
                if response.status_code >= 400:
                    from fastapi import HTTPException

                    detail = response.json().get("detail", response.text)
                    raise HTTPException(status_code=response.status_code, detail=detail)
                return response.json()

            monkeypatch.setattr(
                staff_service, "customer_service_request", customer_service_request
            )
            monkeypatch.setattr(consumer, "SessionLocal", customer_session)
            monkeypatch.setattr(consumer, "StaffSessionLocal", staff_session)
            yield (
                customer_client,
                staff_client,
                customer_session,
                staff_session,
                customer_id,
                product_id,
            )

    customer_service.app.dependency_overrides.clear()
    staff_service.app.dependency_overrides.clear()
    customer_engine.dispose()
    staff_engine.dispose()


def test_customer_order_and_staff_status_workflow(service_clients):
    customer_client, staff_client, customer_session, _, customer_id, product_id = service_clients

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
    db = customer_session()
    try:
        created_event = (
            db.query(models.DomainEventOutbox)
            .filter_by(event_type="order.created")
            .one()
        )
        created_payload = json.loads(created_event.payload)
        assert created_payload["order_id"] == order_id
        assert created_payload["customer_name"] == "Evan"
        assert created_payload["product_name"] == "Keyboard"
        assert created_event.published_at is None
    finally:
        db.close()

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
    db = customer_session()
    try:
        assert db.query(models.Product).filter_by(id=product_id).one().stock == 3
        outbox = (
            db.query(models.DomainEventOutbox)
            .filter_by(event_type="order.status_changed")
            .one()
        )
        assert outbox.published_at is None
        assert json.loads(outbox.payload)["new_status"] == "paid"
    finally:
        db.close()


def test_notification_consumer_is_idempotent(service_clients):
    _, _, customer_session, _, customer_id, _ = service_clients
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
    db = customer_session()
    try:
        first = consumer.persist_notification(db, event)
        second = consumer.persist_notification(db, event)
        assert first.id == second.id
        assert db.query(models.Notification).count() == 1
    finally:
        db.close()


def test_customer_websocket_receives_internal_order_event(service_clients):
    customer_client, _, _, _, customer_id, _ = service_clients
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
        duplicate = customer_client.post(
            "/internal/events",
            json=event,
            headers={"X-Internal-Token": "local-development-token"},
        )
        assert duplicate.status_code == 200
        assert duplicate.json() == {"delivered": True, "duplicate": True}


def test_new_order_broadcast_refreshes_inventory_without_order_details(service_clients):
    customer_client, _, _, _, customer_id, product_id = service_clients
    event = {
        "event_id": "inventory-update-event",
        "event_type": "order.created",
        "payload": {
            "order_id": 77,
            "customer_id": customer_id,
            "customer_name": "Evan",
            "product_id": product_id,
            "product_name": "Keyboard",
            "quantity": 1,
            "status": "pending",
            "stock_remaining": 4,
        },
    }
    with customer_client.websocket_connect("/ws/customer-updates") as websocket:
        delivered = customer_client.post(
            "/internal/events",
            json=event,
            headers={"X-Internal-Token": "local-development-token"},
        )
        assert delivered.status_code == 200
        inventory_event = websocket.receive_json()
        assert inventory_event == {
            "event_id": "inventory-update-event",
            "event_type": "inventory.updated",
            "payload": {"product_id": product_id, "stock_remaining": 4},
        }
        duplicate = customer_client.post(
            "/internal/events",
            json=event,
            headers={"X-Internal-Token": "local-development-token"},
        )
        assert duplicate.status_code == 200
        assert duplicate.json() == {"delivered": True, "duplicate": True}


def test_staff_order_notification_persists_once_and_broadcasts(service_clients):
    customer_client, staff_client, customer_session, staff_session, customer_id, product_id = service_clients
    created = customer_client.post(
        f"/customers/{customer_id}/orders",
        json={
            "product_id": product_id,
            "quantity": 1,
            "delivery_address": "123 Queen Street",
        },
    )
    assert created.status_code == 200
    order_id = created.json()["id"]
    event = {
        "event_id": "staff-order-created-event",
        "event_type": "order.created",
        "occurred_at": "2026-10-14T08:30:00+00:00",
        "payload": {
            "order_id": order_id,
            "customer_id": customer_id,
            "customer_name": "Evan",
            "product_id": product_id,
            "product_name": "Keyboard",
            "quantity": 1,
            "status": "pending",
        },
    }

    staff_db = staff_session()
    try:
        first = consumer.persist_staff_notification(staff_db, event)
        second = consumer.persist_staff_notification(staff_db, event)
        assert first.id == second.id
        assert staff_db.query(models.StaffNotification).count() == 1
        assert first.created_at == datetime(2026, 10, 14, 8, 30)
    finally:
        staff_db.close()
    customer_db = customer_session()
    try:
        customer_notification = consumer.persist_customer_order_notification(
            customer_db, event
        )
        assert customer_notification.message == f"Your order #{order_id} has been placed"
        assert consumer.persist_customer_order_notification(
            customer_db, event
        ).id == customer_notification.id
    finally:
        customer_db.close()

    with staff_client.websocket_connect("/ws/staff/orders") as websocket:
        rejected = staff_client.post("/internal/events", json=event)
        assert rejected.status_code == 401
        delivered = staff_client.post(
            "/internal/events",
            json=event,
            headers={"X-Internal-Token": "local-development-token"},
        )
        assert delivered.status_code == 200
        assert websocket.receive_json() == event
        duplicate = staff_client.post(
            "/internal/events",
            json=event,
            headers={"X-Internal-Token": "local-development-token"},
        )
        assert duplicate.status_code == 200
        assert duplicate.json() == {"delivered": True, "duplicate": True}

    saved = staff_client.get("/staff/notifications")
    assert saved.status_code == 200
    assert saved.json()[0]["message"] == (
        f"New order #{order_id} from Evan: 1 x Keyboard"
    )


def test_services_have_distinct_route_responsibilities():
    customer_paths = {route.path for route in customer_service.app.routes}
    staff_paths = {route.path for route in staff_service.app.routes}
    assert "/customers/{customer_id}/orders" in customer_paths
    assert "/staff/orders/{order_id}" in staff_paths
    assert "/staff/orders/{order_id}" not in customer_paths
    assert "/ws/staff/orders" in staff_paths
    assert "/ws/customer-updates" in customer_paths


def test_legacy_staff_data_migrates_without_cross_database_foreign_keys(tmp_path):
    customer_engine = create_engine(
        f"sqlite:///{tmp_path / 'legacy-orders.db'}",
        connect_args={"check_same_thread": False},
    )
    staff_engine = create_engine(
        f"sqlite:///{tmp_path / 'migrated-staff.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=customer_engine, tables=models.CUSTOMER_TABLES)
    Base.metadata.create_all(bind=staff_engine, tables=models.STAFF_TABLES)
    staff_session = sessionmaker(bind=staff_engine)

    customer_db = sessionmaker(bind=customer_engine)()
    customer = models.Customer(name="Evan", email="evan@test.com")
    product = models.Product(name="Keyboard", price=49.99, stock=5)
    customer_db.add_all([customer, product])
    customer_db.flush()
    order = models.Order(customer_id=customer.id, product_id=product.id, quantity=1)
    customer_db.add(order)
    customer_db.commit()
    order_id = order.id
    customer_db.close()

    with customer_engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE order_status_history")
        connection.exec_driver_sql(
            "CREATE TABLE staff (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, "
            "email VARCHAR NOT NULL UNIQUE)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE order_status_history ("
            "id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL, old_status VARCHAR, "
            "new_status VARCHAR NOT NULL, changed_by_staff_id INTEGER, "
            "changed_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
            "FOREIGN KEY(order_id) REFERENCES orders(id), "
            "FOREIGN KEY(changed_by_staff_id) REFERENCES staff(id))"
        )
        connection.exec_driver_sql(
            "INSERT INTO staff (id, name, email) VALUES (1, 'Sam', 'sam@test.com')"
        )
        connection.exec_driver_sql(
            "INSERT INTO order_status_history "
            "(id, order_id, old_status, new_status, changed_by_staff_id) "
            "VALUES (1, ?, 'pending', 'paid', 1)",
            (order_id,),
        )
        connection.exec_driver_sql(
            "CREATE TABLE staff_notifications (id INTEGER PRIMARY KEY, "
            "event_id VARCHAR NOT NULL UNIQUE, order_id INTEGER NOT NULL, "
            "message VARCHAR NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
            "FOREIGN KEY(order_id) REFERENCES orders(id))"
        )
        connection.exec_driver_sql(
            "INSERT INTO staff_notifications (id, event_id, order_id, message) "
            "VALUES (1, 'legacy-event', ?, 'Legacy staff alert')",
            (order_id,),
        )

    migrate_staff_accounts(customer_engine, staff_session, staff_engine)

    migrated_db = staff_session()
    try:
        assert migrated_db.query(models.Staff).one().email == "sam@test.com"
        assert migrated_db.query(models.StaffNotification).one().message == (
            "Legacy staff alert"
        )
    finally:
        migrated_db.close()

    inspector = inspect(customer_engine)
    assert "staff" not in inspector.get_table_names()
    assert "staff_notifications" not in inspector.get_table_names()
    assert all(
        foreign_key.get("referred_table") != "staff"
        for foreign_key in inspector.get_foreign_keys("order_status_history")
    )
    history_db = sessionmaker(bind=customer_engine)()
    try:
        history = history_db.query(models.OrderStatusHistory).one()
        assert history.changed_by_staff_id == 1
        assert history.new_status == "paid"
    finally:
        history_db.close()
        customer_engine.dispose()
        staff_engine.dispose()


class FakeMethod:
    delivery_tag = 7


class FakeProperties:
    def __init__(self, headers=None):
        self.headers = headers or {}
        self.message_id = "message-1"
        self.type = "order.status_changed"


class FakeChannel:
    #records what the consumer decided to do with a delivery
    def __init__(self):
        self.acks = []
        self.nacks = []
        self.published = []
        self.callback = None

    def basic_qos(self, prefetch_count=1):
        self.prefetch_count = prefetch_count

    def basic_consume(self, queue, on_message_callback):
        self.callback = on_message_callback

    def start_consuming(self):
        return None

    def basic_ack(self, delivery_tag):
        self.acks.append(delivery_tag)

    def basic_nack(self, delivery_tag, requeue=False):
        self.nacks.append((delivery_tag, requeue))

    def basic_publish(self, exchange, routing_key, body, properties):
        self.published.append((routing_key, body, properties))


def consumer_callback():
    channel = FakeChannel()
    consumer.consume_events(channel)
    return channel


def status_event(event_id="retry-event", customer_id=1, order_id=41):
    return {
        "event_id": event_id,
        "event_type": "order.status_changed",
        "payload": {
            "customer_id": customer_id,
            "order_id": order_id,
            "old_status": "pending",
            "new_status": "paid",
        },
    }


def test_malformed_event_is_dead_lettered_without_retry(service_clients):
    #a message that can never parse must not be retried, only dead lettered
    channel = consumer_callback()
    channel.callback(channel, FakeMethod(), FakeProperties(), b"{not json")

    assert channel.nacks == [(FakeMethod.delivery_tag, False)]
    assert channel.published == []
    assert channel.acks == []


def test_transient_database_failure_is_retried_with_attempt_count(service_clients):
    channel = consumer_callback()

    def broken_persist(db, event):
        raise SQLAlchemyError("database is locked")

    try:
        original = consumer.persist_notification
        consumer.persist_notification = broken_persist
        channel.callback(
            channel, FakeMethod(), FakeProperties(), json.dumps(status_event()).encode()
        )
    finally:
        consumer.persist_notification = original

    assert channel.acks == [FakeMethod.delivery_tag]
    assert channel.nacks == []
    assert len(channel.published) == 1
    _, _, properties = channel.published[0]
    assert properties.headers[consumer.ATTEMPT_HEADER] == 1


def test_repeated_failures_dead_letter_after_max_attempts(service_clients):
    channel = consumer_callback()
    properties = FakeProperties(
        headers={consumer.ATTEMPT_HEADER: consumer.MAX_ATTEMPTS - 1}
    )

    def broken_persist(db, event):
        raise SQLAlchemyError("database is locked")

    try:
        original = consumer.persist_notification
        consumer.persist_notification = broken_persist
        channel.callback(
            channel, FakeMethod(), properties, json.dumps(status_event()).encode()
        )
    finally:
        consumer.persist_notification = original

    #retries are exhausted, so this delivery is dead lettered and not republished
    assert channel.nacks == [(FakeMethod.delivery_tag, False)]
    assert channel.published == []
    assert channel.acks == []


def test_callback_failure_is_retried_instead_of_looping_forever(service_clients):
    channel = consumer_callback()

    def broken_post(*args, **kwargs):
        raise httpx.ConnectError("service is down")

    try:
        original = consumer.httpx.post
        consumer.httpx.post = broken_post
        channel.callback(
            channel, FakeMethod(), FakeProperties(), json.dumps(status_event()).encode()
        )
    finally:
        consumer.httpx.post = original

    #the notification is saved, and the delivery is retried rather than requeued
    assert channel.nacks == []
    assert channel.acks == [FakeMethod.delivery_tag]
    assert len(channel.published) == 1


def test_event_is_validated_before_any_notification_is_written(service_clients):
    _, _, customer_session, staff_session, _, _ = service_clients

    incomplete = {
        "event_id": "missing-customer",
        "event_type": "order.created",
        "payload": {"order_id": 12},
    }
    with pytest.raises(ValueError):
        consumer.validate_event(incomplete)

    #nothing was written to either database
    assert customer_session().query(models.Notification).count() == 0
    assert staff_session().query(models.StaffNotification).count() == 0


def test_seed_cleans_legacy_shared_tables_before_resetting_orders(tmp_path):
    customer_engine = create_engine(
        f"sqlite:///{tmp_path / 'seed-legacy-orders.db'}",
        connect_args={"check_same_thread": False},
    )
    staff_engine = create_engine(
        f"sqlite:///{tmp_path / 'seed-staff.db'}",
        connect_args={"check_same_thread": False},
    )
    from sqlalchemy import event

    @event.listens_for(customer_engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=customer_engine, tables=models.CUSTOMER_TABLES)
    Base.metadata.create_all(bind=staff_engine, tables=models.STAFF_TABLES)
    customer_session = sessionmaker(bind=customer_engine)
    staff_session = sessionmaker(bind=staff_engine)

    db = customer_session()
    db.add_all([
        models.Customer(name="Old Customer", email="old@example.com"),
        models.Product(name="Old Product", price=10, stock=1),
    ])
    db.commit()
    db.flush()
    customer = db.query(models.Customer).one()
    product = db.query(models.Product).one()
    order = models.Order(customer_id=customer.id, product_id=product.id, quantity=1)
    db.add(order)
    db.commit()
    order_id = order.id
    db.close()

    with customer_engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE order_status_history")
        connection.exec_driver_sql(
            "CREATE TABLE staff (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, "
            "email VARCHAR NOT NULL UNIQUE)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE order_status_history ("
            "id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL, old_status VARCHAR, "
            "new_status VARCHAR NOT NULL, changed_by_staff_id INTEGER, "
            "changed_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
            "FOREIGN KEY(order_id) REFERENCES orders(id), "
            "FOREIGN KEY(changed_by_staff_id) REFERENCES staff(id))"
        )
        connection.exec_driver_sql(
            "CREATE TABLE staff_notifications (id INTEGER PRIMARY KEY, "
            "event_id VARCHAR NOT NULL UNIQUE, order_id INTEGER NOT NULL, "
            "message VARCHAR NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
            "FOREIGN KEY(order_id) REFERENCES orders(id))"
        )
        connection.exec_driver_sql(
            "INSERT INTO staff (id, name, email) VALUES (1, 'Sam', 'sam@example.com')"
        )
        connection.exec_driver_sql(
            "INSERT INTO staff_notifications (id, event_id, order_id, message) "
            "VALUES (1, 'old-event', ?, 'Old alert')",
            (order_id,),
        )

    seed_module.seed(
        customer_engine,
        customer_session,
        staff_session,
        staff_engine,
    )

    seeded_customer_db = customer_session()
    try:
        assert seeded_customer_db.query(models.Customer).count() == 2
        assert seeded_customer_db.query(models.Product).count() == 3
        assert "staff_notifications" not in inspect(customer_engine).get_table_names()
        assert all(
            fk.get("referred_table") != "staff"
            for fk in inspect(customer_engine).get_foreign_keys("order_status_history")
        )
    finally:
        seeded_customer_db.close()
    seeded_staff_db = staff_session()
    try:
        assert seeded_staff_db.query(models.Staff).one().email == "sam@test.com"
        assert seeded_staff_db.query(models.StaffNotification).count() == 0
    finally:
        seeded_staff_db.close()
        customer_engine.dispose()
        staff_engine.dispose()
