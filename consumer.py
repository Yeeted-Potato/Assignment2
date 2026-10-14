import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import httpx
import pika
from sqlalchemy.exc import SQLAlchemyError

import models
from broker import ORDERS_QUEUE, open_channel, publish_order_event
from database import Base, SessionLocal, engine


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("orders-consumer")
CUSTOMER_SERVICE_URL = os.getenv("CUSTOMER_SERVICE_URL", "http://127.0.0.1:8000")
STAFF_SERVICE_URL = os.getenv("STAFF_SERVICE_URL", "http://127.0.0.1:8001")
INTERNAL_EVENT_TOKEN = os.getenv("INTERNAL_EVENT_TOKEN", "local-development-token")

Base.metadata.create_all(bind=engine)


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
        pending = [(event.id, event.event_type, event.payload) for event in events]
    except SQLAlchemyError:
        logger.exception("Unable to read pending broker outbox events")
        return
    finally:
        db.close()

    for event_id, event_type, payload_json in pending:
        try:
            published = publish_order_event(event_id, event_type, json.loads(payload_json))
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


def consume_events(channel):
    def on_message(ch, method, _properties, body):
        try:
            event = json.loads(body.decode("utf-8"))
            if not isinstance(event, dict):
                raise ValueError("Event message must be a JSON object")
            db = SessionLocal()
            try:
                if event.get("event_type") == "order.created":
                    notification = persist_staff_notification(db, event)
                    callback_url = f"{STAFF_SERVICE_URL}/internal/events"
                    callback_service = "staff"
                else:
                    notification = persist_notification(db, event)
                    callback_url = f"{CUSTOMER_SERVICE_URL}/internal/events"
                    callback_service = "customer"
            finally:
                db.close()
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, SQLAlchemyError):
            logger.exception("Invalid or unprocessable broker message; sending to dead letter queue")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return

        try:
            response = httpx.post(
                callback_url,
                json=event,
                headers={"X-Internal-Token": INTERNAL_EVENT_TOKEN},
                timeout=3.0,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            logger.exception(
                "%s service callback failed for event %s; requeueing",
                callback_service,
                event.get("event_id"),
            )
            time.sleep(1)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            return

        ch.basic_ack(delivery_tag=method.delivery_tag)
        logger.info(
            "Processed %s into notification %s (event %s)",
            event["event_type"],
            notification.id,
            event["event_id"],
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
