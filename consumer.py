#consumer that turns order events from rabbitmq into customer notifications
import json
import time
import pika
from sqlalchemy.exc import IntegrityError
from database import SessionLocal
import models

QUEUE_NAME = "order_events"

#the message the customer sees for each new status
STATUS_MESSAGES = {
    "paid": "Your order #{order_id} has been paid",
    "shipped": "Your order #{order_id} has shipped",
    "delivered": "Your order #{order_id} has been delivered",
}

#save one notification, returns False if this event was already saved before
def save_notification(event):
    db = SessionLocal()
    try:
        text = STATUS_MESSAGES.get(event["new_status"], "Your order #{order_id} was updated")
        db.add(models.Notification(
            event_id=event["event_id"],
            customer_id=event["customer_id"],
            order_id=event["order_id"],
            message=text.format(order_id=event["order_id"]),
        ))
        db.commit()
        return True
    except IntegrityError:
        #event_id is unique, so this means the event was handled before
        db.rollback()
        return False
    finally:
        db.close()
        
#runs every time a message arrives
def handle_message(channel, method, properties, body):
    try:
        event = json.loads(body)
        event_id = event["event_id"]
        event["customer_id"], event["order_id"], event["new_status"]
    except (ValueError, KeyError):
        #a broken message can never work, so remove it instead of retrying forever
        print("Rejected bad message:", body)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    print("Received:", event_id, "| redelivered:", method.redelivered)
    try:
        if save_notification(event):
            print("Saved notification for", event_id)
        else:
            print("Duplicate skipped:", event_id)
    except Exception as error:
        #saving failed for another reason, put the message back to try again
        print("Could not save, will retry:", error)
        time.sleep(2)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        return

    #only ack once the notification is saved, or was already saved
    channel.basic_ack(delivery_tag=method.delivery_tag)
    print("Acked", event_id)

connection = pika.BlockingConnection(pika.ConnectionParameters(host="localhost"))
channel = connection.channel()
channel.queue_declare(queue=QUEUE_NAME, durable=True)
channel.basic_qos(prefetch_count=1)
channel.basic_consume(queue=QUEUE_NAME, on_message_callback=handle_message)

print("Waiting for order events. Press Ctrl+C to stop.")
try:
    channel.start_consuming()
except KeyboardInterrupt:
    print("Consumer stopped")
    connection.close()