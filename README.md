# Customer Orders: Web, Android, and RabbitMQ

This project extends the original Customer Orders API with distinct customer and staff backend services, a RabbitMQ event workflow, and live customer order updates over WebSockets. The Android client continues to use the customer REST API. The selected advanced integration is **Path B: message broker**; no gRPC/Path A implementation is included.

## Architecture

```text
Customer web client / Android
          | HTTP + WebSocket
          v
Customer service :8000 ----------------------+
          | shared SQLite data              | HTTP internal event callback
          |                                 v
Staff web client -> Staff service :8001   Customer WebSocket connections
                          |
                          | status update + durable outbox
                          v
                   RabbitMQ: orders.events
                          |
                          v
               Separate consumer process
                 |                 |
                 |                 +--> customer service WebSocket fan-out
                 +--> notifications table
```

The customer service owns customer login, product lookup, order creation/listing, and customer notifications. The staff service owns staff login, customer/order administration views, and order status transitions. They are independent FastAPI processes but intentionally share the existing SQLite database so both roles see the same orders. The staff service writes a status change and a domain event to a transactional outbox in one database transaction. It publishes the event with RabbitMQ publisher confirms. If RabbitMQ is unavailable, the API reports `event_delivery: "pending"` and the separately running consumer retries unpublished outbox entries. The durable queue uses manual acknowledgements; the consumer persists notifications idempotently by event ID and only acknowledges after the customer-service callback succeeds. Failed callbacks are requeued; malformed events are sent to a durable dead-letter queue.

Both order creation and order status changes create outbox events. For a newly created order, the consumer saves a staff notification and calls the staff service, which broadcasts `order.created` to connected staff browsers. The staff home page at port 8001 shows saved notifications and displays new orders live; it reconnects and restores saved notifications after a connection loss. For a status change, the consumer saves the customer notification and sends the event to the customer service, which broadcasts `order.status_changed` to the relevant customer's open browser. The customer page reloads persisted orders and notifications after connecting and reconnecting.

## Prerequisites

- Python 3.12 or newer and pip, for local development.
- Docker Desktop with Docker Compose, for the simplest complete launch (RabbitMQ, both APIs, and the consumer).
- Android Studio and a compatible Android SDK to build/run the Android client.

## Run the complete system with Docker Compose

From the repository root in PowerShell:

```powershell
docker compose up --build -d rabbitmq
docker compose run --rm --no-deps customer-service python seed.py
docker compose up --build -d
docker compose ps
```

Open the customer web client at `http://localhost:8000/` and the staff client at `http://localhost:8001/`. API documentation is available at `/docs` on each service. RabbitMQ's local management page is `http://localhost:15672/` (local-development credentials: `orders` / `orders-local-dev`).

The database and RabbitMQ data use named Docker volumes and persist across restarts. To reset the sample data later, stop the APIs and consumer before dropping/recreating the tables:

```powershell
docker compose stop customer-service staff-service consumer
docker compose run --rm --no-deps customer-service python seed.py
docker compose up -d
```

**Warning:** `seed.py` drops and recreates all database tables, deleting existing orders, notifications, and customers. Only run it when resetting local/demo data.

Follow service logs with `docker compose logs -f customer-service staff-service consumer rabbitmq`. Stop the system with `docker compose down`; this retains persistent volumes. To also erase demo data, explicitly remove the named volumes with `docker compose down --volumes`.

## Run locally without Dockerized APIs

Use Docker only for RabbitMQ, then start each Python process in a separate PowerShell terminal:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
docker compose up -d rabbitmq
python seed.py
```

In each of three activated terminals, from the repository root:

```powershell
# Terminal 1: customer API, web client, and WebSocket server
uvicorn customer_service:app --reload --port 8000
```

```powershell
# Terminal 2: staff API and web client
uvicorn staff_service:app --reload --port 8001
```

```powershell
# Terminal 3: RabbitMQ publisher relay and independent event consumer
python consumer.py
```

Local defaults are `DATABASE_URL=sqlite:///./orders.db`, `RABBITMQ_URL=amqp://guest:guest@localhost:5672/%2F`, and `INTERNAL_EVENT_TOKEN=local-development-token`. Set these variables in all relevant terminals if overriding them. For example:

```powershell
$env:DATABASE_URL = "sqlite:///./orders.db"
$env:RABBITMQ_URL = "amqp://guest:guest@localhost:5672/%2F"
$env:INTERNAL_EVENT_TOKEN = "local-development-token"
```

`STAFF_PASSWORD` defaults to `dummypw` for the seeded local demo account. Set a different value on the staff service to override it.

## Demo accounts and shared workflow

After seeding:

- Customer web/Android login: **Evan**, `evan@test.com`.
- Another customer: **Bob**, `bob@test.com`.
- Staff login: `sam@test.com`, password **dummypw**.
- Sample products: Keyboard, Mouse, and Monitor.

To demonstrate the shared workflow:

1. Sign in as Evan at `http://localhost:8000/`, create an order, then open **View Orders** and leave the page open. It connects to `/ws/customers/{customer_id}/orders`.
2. Sign in to staff at `http://localhost:8001/`, open **Update Status**, and advance Evan's order from `pending` to `paid`.
3. When Evan places the order, the staff home page displays a live notification without refresh. The notification is also saved and can be read from `GET /staff/notifications`.
4. Leave the customer order page open, then advance Evan's order from `pending` to `paid` on the staff page. The customer page displays the live status update without refresh; the consumer saves a customer notification available from `GET /customers/{customer_id}/notifications`.
5. To demonstrate recovery, temporarily stop the staff/customer service or RabbitMQ container. An order event remains in the outbox or is requeued; restore the component and confirm that the staff page reconnects and reloads saved notifications.

The status workflow is `pending -> paid -> shipped -> delivered`. Orders require either a typed delivery address or both latitude and longitude; the Android client continues to submit device location with manual-address fallback.

## API and ports

| Service | Port | Main routes |
| --- | ---: | --- |
| Customer service | 8000 | `GET /health`, `POST /customer-login`, `GET /customers`, `POST /customers`, `GET /customers/{id}`, `GET /products`, `POST /customers/{id}/orders`, `GET /customers/{id}/orders`, `GET /customers/{id}/notifications`, `WS /ws/customers/{id}/orders` |
| Staff service | 8001 | `GET /health`, `POST /staff-login`, `GET/POST /staff/customers`, `GET /staff/products`, `GET /staff/orders`, `GET /staff/notifications`, `GET /staff/customers/{id}/orders`, `PATCH /staff/orders/{id}`, `WS /ws/staff/orders` |
| RabbitMQ | 5672 | Durable queue `orders.events`; malformed events go to `orders.events.dead` |
| RabbitMQ management | 15672 | Local development UI |

`main.py` remains a compatibility entry point for `uvicorn main:app`; it starts the **customer service only**. Start `staff_service:app` and `consumer.py` separately for the full system.

## Verification

Python checks:

```powershell
python -m pytest -q
```

The Android API compatibility check requires the customer service and seeded accounts to be running:

```powershell
python scripts/check_api.py
```

It creates two sample orders for Evan. Reset the local database first if you want to replay the script against a clean dataset.

The representative response-time check measures repeated `GET /products` requests against the customer API; its acceptance target is a local 95th-percentile response time below 250 ms:

```powershell
python scripts/measure_response_time.py
```

In the implementation validation environment, 30 sequential loopback requests measured a mean of **17.80 ms** and p95 of **27.31 ms**, meeting the target. This is a local development observation, not a production benchmark; rerun on the demonstration machine and record its conditions/results.

Build the Android app from the repository root:

```powershell
Set-Location android-client
.\gradlew.bat assembleDebug
```

For an Android emulator, the app uses `10.0.2.2:8000` to reach the host customer service. For a physical phone, set `ApiClient.BASE_URL` in the Android project to the development computer's LAN address.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./orders.db` | SQLAlchemy database URL; Compose points both APIs and the consumer to a shared persistent SQLite volume. |
| `RABBITMQ_URL` | `amqp://guest:guest@localhost:5672/%2F` | RabbitMQ AMQP connection URL; Compose configures a non-guest local user for container-to-container connections. |
| `ORDERS_QUEUE` | `orders.events` | Durable order-event queue. |
| `ORDERS_DEAD_LETTER_QUEUE` | `orders.events.dead` | Dead-letter destination for malformed messages. |
| `CUSTOMER_SERVICE_URL` | `http://127.0.0.1:8000` | Customer API base URL used by the consumer callback. |
| `STAFF_SERVICE_URL` | `http://127.0.0.1:8001` | Staff API base URL used by the consumer for new-order notifications. |
| `INTERNAL_EVENT_TOKEN` | `local-development-token` | Shared token for the consumer-to-customer internal callback. Change outside local demos. |
| `WEB_ORIGINS` | Localhost ports 8000 and 8001 | Comma-separated browser origins permitted by each API. |
| `STAFF_PASSWORD` | `dummypw` | Demo staff password checked by the staff login endpoint. |

## Known limitations

- Demo sign-in is not production authentication: customer login checks name/email, staff uses a shared demo password, and WebSocket connections are not authenticated.
- The two services and consumer share a SQLite file to preserve the existing project data model; this is suitable for this local assignment demo, not a high-concurrency deployment.
- RabbitMQ provides at-least-once delivery. Notification persistence is idempotent by event ID; the consumer retries callback failures and republishes pending outbox records.
- RabbitMQ broker recovery and Docker component failures should be demonstrated during marking; automated tests cover the outbox fallback and duplicate-event behavior without requiring a live broker.
- Android is a customer workflow client; the staff workflows are web-only.

## Submission details

- Repository: https://github.com/Yeeted-Potato/Assignment2
- Final commit hash/tag: record the commit used to create the submission ZIP.
- The group/individual technical reports and demonstration video are separate assessment deliverables and are not generated by this project README.
