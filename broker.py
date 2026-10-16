import json
import logging
import os
from datetime import datetime, timezone

import pika


logger = logging.getLogger(__name__)
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/%2F")
ORDERS_QUEUE = os.getenv("ORDERS_QUEUE", "orders.events")
DEAD_LETTER_QUEUE = os.getenv("ORDERS_DEAD_LETTER_QUEUE", "orders.events.dead")


def open_channel():
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    channel = connection.channel()
    channel.queue_declare(
        queue=ORDERS_QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": DEAD_LETTER_QUEUE,
        },
    )
    channel.queue_declare(queue=DEAD_LETTER_QUEUE, durable=True)
    channel.confirm_delivery()
    return connection, channel


def publish_order_event(
    event_id: str,
    event_type: str,
    payload: dict,
    occurred_at: datetime | None = None,
) -> bool:
    connection = None
    try:
        connection, channel = open_channel()
        event = {
            "event_id": event_id,
            "event_type": event_type,
            "payload": payload,
        }
        if occurred_at is not None:
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=timezone.utc)
            event["occurred_at"] = occurred_at.astimezone(timezone.utc).isoformat()
        return channel.basic_publish(
            exchange="",
            routing_key=ORDERS_QUEUE,
            body=json.dumps(event),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=pika.DeliveryMode.Persistent,
                message_id=event_id,
                type=event_type,
            ),
            mandatory=True,
        )
    except (pika.exceptions.AMQPError, OSError) as exc:
        logger.warning("Could not publish order event %s; it remains in the outbox: %s", event_id, exc)
        return False
    finally:
        if connection is not None and connection.is_open:
            try:
                connection.close()
            except (pika.exceptions.AMQPError, OSError):
                logger.warning("Unable to close RabbitMQ publisher connection cleanly")
