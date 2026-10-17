import json
import logging
import settings  # noqa: F401  loads .env before the values below are read
import os
import threading
import time
from datetime import datetime, timezone

import httpx
import pika
from sqlalchemy.exc import SQLAlchemyError

import models
from broker import ORDERS_QUEUE, open_channel, publish_order_event
from base import Base
from database import SessionLocal, engine
from models import CUSTOMER_TABLES, STAFF_TABLES
from staff_database import StaffSessionLocal, staff_engine


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("orders-consumer")
CUSTOMER_SERVICE_URL = os.getenv("CUSTOMER_SERVICE_URL", "http://127.0.0.1:8000")
STAFF_SERVICE_URL = os.getenv("STAFF_SERVICE_URL", "http://127.0.0.1:8001")
INTERNAL_EVENT_TOKEN = os.getenv("INTERNAL_EVENT_TOKEN", "local-development-token")

#how many times a transient failure is retried before the dead letter queue
MAX_ATTEMPTS = 3
#header that carries the attempt count across retries
ATTEMPT_HEADER = "x-attempt-count"

Base.metadata.create_all(bind=engine, tables=CUSTOMER_TABLES)
Base.metadata.create_all(bind=staff_engine, tables=STAFF_TABLES)


def event_timestamp(event: dict) -> datetime | None:
    occurred_at = event.get("occurred_at")
    if not isinstance(occurred_at, str):
        return None
    try:
        parsed = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Event occurred_at must be an ISO 8601 timestamp")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def attach_outbox_timestamp(event: dict) -> None:
    if event.get("occurred_at") or not isinstance(event.get("event_id"), str):
        return
    db = SessionLocal()
    try:
        outbox_event = db.query(models.DomainEventOutbox).filter_by(
            id=event["event_id"]
        ).first()
        if outbox_event is not None and outbox_event.created_at is not None:
            occurred_at = outbox_event.created_at
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=timezone.utc)
            event["occurred_at"] = occurred_at.astimezone(timezone.utc).isoformat()
    finally:
        db.close()


def persist_notification(db, event: dict):
    if event.get("event_type") != "order.status_changed":
        raise ValueError("Unsupported event type")
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Event payload must be an object")
    customer_id = payload.get("customer_id")
    order_id = payload.get("order_id")
    new_status = payload.get("new_status")
    event_id = event.get("event_id")
    if not isinstance(customer_id, int) or not isinstance(order_id, int) or not event_id:
        raise ValueError("Event is missing an identifier")

    notification = db.query(models.Notification).filter(
        models.Notification.event_id == event_id
    ).first()
    if notification is not None:
        return notification

    notification = models.Notification(
        event_id=event_id,
        customer_id=customer_id,
        order_id=order_id,
        message=f"Order {order_id} status changed to {new_status}",
        created_at=event_timestamp(event),
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


def persist_staff_notification(db, event: dict):
    if event.get("event_type") != "order.created":
        raise ValueError("Unsupported staff notification event type")
    payload = event.get("payload")
    event_id = event.get("event_id")
    if not isinstance(payload, dict) or not isinstance(event_id, str):
        raise ValueError("Event is missing a payload or event_id")
    order_id = payload.get("order_id")
    if not isinstance(order_id, int):
        raise ValueError("Event is missing a valid order_id")

    notification = db.query(models.StaffNotification).filter(
        models.StaffNotification.event_id == event_id
    ).first()
    if notification is not None:
        return notification

    customer_name = payload.get("customer_name", "A customer")
    product_name = payload.get("product_name", "a product")
    quantity = payload.get("quantity")
    notification = models.StaffNotification(
        event_id=event_id,
        order_id=order_id,
        message=f"New order #{order_id} from {customer_name}: "
        f"{quantity} x {product_name}",
        created_at=event_timestamp(event),
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


def persist_customer_order_notification(db, event: dict):
    if event.get("event_type") != "order.created":
        raise ValueError("Unsupported customer notification event type")
    payload = event.get("payload")
    event_id = event.get("event_id")
    if not isinstance(payload, dict) or not isinstance(event_id, str):
        raise ValueError("Event is missing a payload or event_id")
    customer_id = payload.get("customer_id")
    order_id = payload.get("order_id")
    if not isinstance(customer_id, int) or not isinstance(order_id, int):
        raise ValueError("Event is missing customer or order identifiers")

    notification = db.query(models.Notification).filter(
        models.Notification.event_id == event_id
    ).first()
    if notification is not None:
        return notification
    notification = models.Notification(
        event_id=event_id,
        customer_id=customer_id,
        order_id=order_id,
        message=f"Your order #{order_id} has been placed",
        created_at=event_timestamp(event),
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


def publish_pending_outbox():
    db = SessionLocal()
    try:
        events = (
            db.query(models.DomainEventOutbox)
            .filter(models.DomainEventOutbox.published_at.is_(None))
            .order_by(models.DomainEventOutbox.created_at)
            .limit(25)
            .all()
        )
        pending = [
            (event.id, event.event_type, event.payload, event.created_at)
            for event in events
        ]
    except SQLAlchemyError:
        logger.exception("Unable to read pending broker outbox events")
        return
    finally:
        db.close()

    for event_id, event_type, payload_json, occurred_at in pending:
        try:
            published = publish_order_event(
                event_id, event_type, json.loads(payload_json), occurred_at
            )
        except (TypeError, json.JSONDecodeError):
            logger.exception("Invalid outbox payload for event %s", event_id)
            continue
        if not published:
            continue
        db = SessionLocal()
        try:
            outbox_event = db.query(models.DomainEventOutbox).filter(
                models.DomainEventOutbox.id == event_id
            ).first()
            if outbox_event is not None and outbox_event.published_at is None:
                outbox_event.published_at = datetime.now(timezone.utc)
                db.commit()
        except SQLAlchemyError:
            db.rollback()
            logger.exception("Unable to mark outbox event %s as published", event_id)
        finally:
            db.close()


def outbox_relay():
    while True:
        publish_pending_outbox()
        time.sleep(2)


def validate_event(event: dict) -> None:
    #check the whole event before writing anything, so a bad event cannot
    #leave a notification saved in one database but not the other
    event_type = event.get("event_type")
    if event_type not in ("order.created", "order.status_changed"):
        raise ValueError("Unsupported event type")

    event_id = event.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("Event is missing an event_id")

    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Event payload must be an object")

    if not isinstance(payload.get("order_id"), int):
        raise ValueError("Event is missing a valid order_id")

    if not isinstance(payload.get("customer_id"), int):
        raise ValueError("Event is missing a valid customer_id")

    #a bad timestamp would fail after a notification is already saved
    event_timestamp(event)


def event_attempts(properties) -> int:
    headers = getattr(properties, "headers", None) or {}
    try:
        return int(headers.get(ATTEMPT_HEADER, 0))
    except (TypeError, ValueError):
        return 0


def retry_or_dead_letter(ch, method, properties, body, event_id, reason):
    #a transient failure is retried up to MAX_ATTEMPTS, then dead lettered
    attempts = event_attempts(properties) + 1
    if attempts >= MAX_ATTEMPTS:
        logger.warning(
            "Event %s failed %d times (%s); sending to the dead letter queue",
            event_id,
            attempts,
            reason,
        )
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    logger.warning(
        "Event %s failed (attempt %d of %d: %s); will retry",
        event_id,
        attempts,
        MAX_ATTEMPTS,
        reason,
    )
    #republish with the attempt count raised, then ack the old delivery
    headers = dict(getattr(properties, "headers", None) or {})
    headers[ATTEMPT_HEADER] = attempts
    ch.basic_publish(
        exchange="",
        routing_key=ORDERS_QUEUE,
        body=body,
        properties=pika.BasicProperties(
            content_type="application/json",
            delivery_mode=pika.DeliveryMode.Persistent,
            message_id=properties.message_id,
            type=properties.type,
            headers=headers,
        ),
    )
    ch.basic_ack(delivery_tag=method.delivery_tag)


def consume_events(channel):
    def on_message(ch, method, properties, body):
        event_id = None
        try:
            event = json.loads(body.decode("utf-8"))
            if not isinstance(event, dict):
                raise ValueError("Event message must be a JSON object")
            event_id = event.get("event_id")
            #validate everything up front so a bad event cannot be half saved
            validate_event(event)
            attach_outbox_timestamp(event)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError, KeyError):
            #a badly formed message will never succeed, so it goes straight to
            #the dead letter queue instead of being retried
            logger.exception("Malformed broker message; sending to the dead letter queue")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return

        try:
            session_factory = (
                StaffSessionLocal
                if event.get("event_type") == "order.created"
                else SessionLocal
            )
            db = session_factory()
            try:
                if event.get("event_type") == "order.created":
                    notification = persist_staff_notification(db, event)
                    # Make the staff broadcast last so a customer callback retry
                    # cannot replay an alert already shown to staff.
                    callback_urls = [
                        f"{CUSTOMER_SERVICE_URL}/internal/events",
                        f"{STAFF_SERVICE_URL}/internal/events",
                    ]
                    customer_db = SessionLocal()
                    try:
                        persist_customer_order_notification(customer_db, event)
                    finally:
                        customer_db.close()
                    callback_service = "staff/customer"
                else:
                    notification = persist_notification(db, event)
                    callback_urls = [f"{CUSTOMER_SERVICE_URL}/internal/events"]
                    callback_service = "customer"
            finally:
                db.close()
        except ValueError:
            #the message carries something that cannot be stored, such as a
            #bad timestamp, so retrying will never help
            logger.exception("Unprocessable broker message; sending to the dead letter queue")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return
        except SQLAlchemyError:
            #the database may be locked or briefly unavailable, so this is
            #worth retrying. Persistence is idempotent by event id, so a retry
            #cannot duplicate a notification already saved in the other database.
            logger.exception("Database unavailable for event %s", event_id)
            retry_or_dead_letter(ch, method, properties, body, event_id, "database unavailable")
            return

        for callback_url in callback_urls:
            try:
                response = httpx.post(
                    callback_url,
                    json=event,
                    headers={"X-Internal-Token": INTERNAL_EVENT_TOKEN},
                    timeout=3.0,
                )
                response.raise_for_status()
            except httpx.HTTPError:
                #the service may be restarting, so retry, but not forever
                logger.exception("%s service callback failed for event %s", callback_service, event_id)
                retry_or_dead_letter(ch, method, properties, body, event_id, "service callback failed")
                return

        ch.basic_ack(delivery_tag=method.delivery_tag)
        logger.info(
            "Processed %s into notification %s (event %s)",
            event["event_type"],
            notification.id,
            event_id,
        )

    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=ORDERS_QUEUE, on_message_callback=on_message)
    channel.start_consuming()


def main():
    threading.Thread(target=outbox_relay, name="outbox-relay", daemon=True).start()
    while True:
        connection = None
        try:
            connection, channel = open_channel()
            logger.info("Consuming durable queue %s", ORDERS_QUEUE)
            consume_events(channel)
        except (pika.exceptions.AMQPError, OSError):
            logger.exception("RabbitMQ is unavailable; reconnecting in 3 seconds")
            time.sleep(3)
        finally:
            if connection is not None and connection.is_open:
                try:
                    connection.close()
                except (pika.exceptions.AMQPError, OSError):
                    logger.warning("Unable to close RabbitMQ consumer connection cleanly")


if __name__ == "__main__":
    main()
