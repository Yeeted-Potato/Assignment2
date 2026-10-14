#sends order events to rabbitmq so the consumer can make notifications
import json
import pika

QUEUE_NAME = "order_events"

def publish_order_event(event):
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host="localhost"))
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE_NAME, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=QUEUE_NAME,
            body=json.dumps(event),
            properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
        )
        connection.close()
        return True
    except pika.exceptions.AMQPError as error:
        #the status change is already saved, so just log that the event could not be sent
        print("Could not publish event:", error)
        return False