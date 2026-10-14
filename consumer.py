#consumer that waits for order events from rabbitmq
import pika

#runs every time a message arrives
def handle_message(channel, method, properties, body):
    print("Received:", body.decode())
    #tell rabbitmq this message is done so it can delete it
    channel.basic_ack(delivery_tag=method.delivery_tag)

connection = pika.BlockingConnection(pika.ConnectionParameters(host="localhost"))
channel = connection.channel()
channel.queue_declare(queue="order_events", durable=True)

#only give this consumer one message at a time
channel.basic_qos(prefetch_count=1)
channel.basic_consume(queue="order_events", on_message_callback=handle_message)

print("Waiting for order events. Press Ctrl+C to stop.")
try:
    channel.start_consuming()
except KeyboardInterrupt:
    print("Consumer stopped")
    connection.close()