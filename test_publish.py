#quick test to check python can send a message to rabbitmq
import pika

#connect to rabbitmq running in docker
connection = pika.BlockingConnection(pika.ConnectionParameters(host="localhost"))
channel = connection.channel()

#make the queue if it does not exist, durable means the queue survives a restart
channel.queue_declare(queue="order_events", durable=True)

#send one message, delivery_mode 2 means save it to disk
channel.basic_publish(
    exchange="",
    routing_key="order_events",
    body="hello from evan",
    properties=pika.BasicProperties(delivery_mode=2),
)

print("Message sent")
connection.close()