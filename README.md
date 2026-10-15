# Customer Orders API

A small web application for COMP713 Individual Assignment. A client communicates with my FastApi server, which uses SQLite database to store data. Customers and their orders get managed with a order status workflow.

# Software/Tools Required
- Python
- pip
- Docker Desktop (runs the RabbitMQ message broker)

# To Setup
1. Clone this repository
2. Open terminal in the project folder
3. Create a virtual enviroment

e.g Windows Powershell
python -m venv .venv
.venv\Scripts\Activate.ps1

4. Install the dependancies

pip install -r requirements.txt

# Starting the server

uvicorn main:app --reload

Browser:
http://127.0.0.1:8000 - client interface
http://127.0.0.1:8000/docs - API documentation

# Message broker (RabbitMQ)

When staff change an order status, the server publishes an `order_status_changed` event to RabbitMQ. A separate consumer program reads each event and saves a notification for the customer, which the Android app shows.

## Start the broker

Open Docker Desktop and wait until it says Engine running, then in the project folder run:

```
docker compose up -d
```

Check it is running with `docker compose ps`.

## Start the consumer

Open a second terminal in the project folder, activate the virtual environment, then run:

```
python consumer.py
```

Keep it running while using the system. It prints each event it receives, saves or skips, and acknowledges.

## Ports

| Port | Used for |
|---|---|
| 8000 | FastAPI server |
| 5672 | RabbitMQ (used by the server and consumer) |
| 15672 | RabbitMQ dashboard, http://localhost:15672, login guest / guest |

## Testing the broker

- Normal event: change an order status with `PATCH /orders/{id}`. The consumer prints `Saved notification`, and `GET /customers/{id}/notifications` shows it.
- Repeated event: with the consumer running, run `python demo_duplicate.py 2 1 shipped` to resend an event that was already processed. The consumer prints `Duplicate skipped` and still acks, and no second notification is created.
- Consumer offline: stop the consumer, change some order statuses, and see the messages waiting under Ready on the dashboard. Run `docker compose restart` and they are still there. Start the consumer again and it processes all of them.

# API endpoints

GET - '/heath' - Health check (returns status)
GET - '/customers' - List all customers
POST - '/customers' - Create a customer
GET - '/customers/{id}' - Get one customer
POST - '/customers/{id}/orders' - Create an order for a customer
GET - 'customers/{id}/orders' - List a customers orders
PATCH - '/orders/{id}' - Update an order's status
GET - '/customers/{id}/notifications' - List a customers notifications, newest first
PATCH - '/notifications/{id}/read' - Mark a notification as read

# Order status workflow

Orders transit through these statuses
pending -> paid -> shipped -> delivered

# Testing the main functions

The system can be tested through the client page or the `/docs` interface:

Create a customer — via the form or `POST /customers`.
Create an order — provide an existing customer ID.Invalid input — submitting a customer without a name returns a 422 error.
Missing customer — requesting `/customers/999` returns a 404 error.
Illegal status change — patching an order from `pending` to `delivered` returns a 400 error.

# Known limitations

- No authentication
- SQLite is not intended for high-concurrency use
- If RabbitMQ is down when an order status changes, the change is still saved but the event is lost and only logged. No notification is created for it.
- Messages that cannot be read are removed without being stored, as there is no dead letter queue.
- The consumer must be started from the project folder so it uses the same orders.db file as the server.