# Customer Orders: Web, Android, and RabbitMQ

This project extends the original Customer Orders API with distinct customer and staff backend services, a RabbitMQ event workflow, and live web updates over WebSockets. The Android client continues to use the customer REST API. The selected advanced integration is **Path B: message broker**; no gRPC/Path A implementation is included.

## Architecture

```text
Customer web client / Android
          | HTTP + WebSocket
          v
Customer service :8000 <----- internal REST ----- Staff service :8001
  | owns orders.db                                  | owns staff.db
  | customers, products, orders, outbox              | staff accounts, staff alerts
  |                                                  |
  +---------------- order/status outbox -------------+
                         |
                         v
                  RabbitMQ: orders.events
                         |
                         v
               Separate consumer process
                 |                      |
                 v                      v
        customer service WS      staff service WS
        status + inventory       new-order alerts
```

The customer service owns customers, products, orders, order history, customer notifications, and the transactional event outbox in `orders.db`. The staff service owns staff accounts and staff notifications in `staff.db`. The files are separate even though Docker mounts them in the same persistent volume. The staff API reads and changes customer/order data only by calling authenticated internal REST endpoints on the customer service; it does not query the customer database. The customer database has no foreign keys into staff-owned tables, and the staff database has no copies of customer/order tables. The customer service records an order/status change and its outbox event in one transaction. A separately running consumer publishes pending outbox events to RabbitMQ with publisher confirms. The durable queue uses manual acknowledgements; notifications are idempotent by event ID, failed callbacks are requeued, and malformed events go to a durable dead-letter queue.

Both order creation and order status changes create outbox events. For a newly created order, the consumer saves notifications in the respective staff and customer databases and calls both services. Every open staff page receives a live new-order alert; every customer page gets an inventory update, refreshing product quantities without a manual refresh. The ordering customer also sees a saved order notification. Status changes are sent to the affected customer's browser. Both web clients show notifications in a right-side panel, reconnect automatically, and restore saved notifications. Android continues to retrieve customer data through REST.

Notification times are stored as UTC instants and displayed in New Zealand time (`Pacific/Auckland`), including daylight-saving changes. Each alert shows when it was notified/restored in the current page and when its event originally occurred. Saved alerts are history: if the broker or a service was unavailable, an alert may arrive later, but it retains the original order time. The consumer delivers staff alerts after the customer-service callback succeeds so a retried customer callback does not make an older alert look newly placed.

## Prerequisites

- Python 3.12 or newer and pip, for local development.
- Docker Desktop with Docker Compose, for the simplest complete launch (RabbitMQ, both APIs, and the consumer).
- Android Studio and a compatible Android SDK to build/run the Android client.

## Run the complete system with Docker Compose

From the repository root in PowerShell:

```powershell
docker compose build
docker compose up -d rabbitmq
docker compose run --rm --no-deps customer-service python seed.py
docker compose up -d
docker compose ps
```

If upgrading an earlier version that stored staff accounts in `orders.db`, migrate those accounts before starting the new staff service:

```powershell
docker compose build
docker compose run --rm --no-deps -e DATABASE_URL=sqlite:////app/data/orders.db -e STAFF_DATABASE_URL=sqlite:////app/data/staff.db staff-service python scripts/migrate_staff_accounts.py
docker compose up -d
```

This copies existing staff accounts and notifications, then removes the legacy staff tables and cross-database foreign key while preserving customer, order, and history records. For a new installation, skip migration and seed both databases after starting RabbitMQ as shown above.

`seed.py` is a destructive demo-data reset. It also removes leftover staff tables and the old staff-to-orders foreign key from a database created by the earlier shared-database version, so it can safely reset that legacy schema after rebuilding the image.

Open the customer login at `http://localhost:8000/` and the staff client at `http://localhost:8001/`. Customer login is shown by default; to resume a browser-stored customer session explicitly, use `http://localhost:8000/?resume=1`. API documentation is available at `/docs` on each service. RabbitMQ's local management page is `http://localhost:15672/` (local-development credentials: `orders` / `orders-local-dev`).

The two database files and RabbitMQ data use named Docker volumes and persist across restarts. To reset the sample data later, stop the APIs and consumer before dropping/recreating the tables:

```powershell
docker compose stop customer-service staff-service consumer
docker compose run --rm --no-deps customer-service python seed.py
docker compose up -d
```

**Warning:** `seed.py` drops and recreates all database tables, deleting existing orders, notifications, and customers. Only run it when resetting local/demo data.

Follow service logs with `docker compose logs -f customer-service staff-service consumer rabbitmq`. Stop the system with `docker compose down`; this retains persistent volumes. To also erase demo data, explicitly remove the named volumes with `docker compose down --volumes`.

## Run locally without Dockerized APIs

For local development, use Docker only for RabbitMQ, then start each Python process in a separate PowerShell terminal. The customer and staff databases default to `orders.db` and `staff.db` in the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
docker compose up -d rabbitmq
```

In Terminal 1, start the customer service:

```powershell
$env:DATABASE_URL = "sqlite:///./orders.db"
uvicorn customer_service:app --reload --port 8000
```

In Terminal 2, start the staff API, which accesses customer-owned data through the customer service:

```powershell
$env:STAFF_DATABASE_URL = "sqlite:///./staff.db"
$env:CUSTOMER_SERVICE_URL = "http://127.0.0.1:8000"
$env:INTERNAL_EVENT_TOKEN = "local-development-token"
uvicorn staff_service:app --reload --port 8001
```

In Terminal 3, start the consumer, which connects to both service-owned databases:

```powershell
$env:DATABASE_URL = "sqlite:///./orders.db"
$env:STAFF_DATABASE_URL = "sqlite:///./staff.db"
$env:RABBITMQ_URL = "amqp://orders:orders-local-dev@localhost:5672/%2F"
$env:INTERNAL_EVENT_TOKEN = "local-development-token"
$env:CUSTOMER_SERVICE_URL = "http://127.0.0.1:8000"
$env:STAFF_SERVICE_URL = "http://127.0.0.1:8001"
python consumer.py
```

Before starting services for the first time, seed both databases from another terminal:

```powershell
$env:DATABASE_URL = "sqlite:///./orders.db"
$env:STAFF_DATABASE_URL = "sqlite:///./staff.db"
python seed.py
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
3. When Evan places the order, every open staff page displays a live notification without refresh. Customer pages refresh product stock automatically, and Evan sees a saved order notification.
4. Leave the customer order page open, then advance Evan's order from `pending` to `paid` on the staff page. The customer page displays the live status update without refresh; the consumer saves a customer notification available from `GET /customers/{customer_id}/notifications`.
5. To demonstrate recovery, temporarily stop a service or RabbitMQ container. An event remains in the outbox or is requeued; restore the component and confirm that the pages reconnect, restore saved notifications, and refresh current data.

The status workflow is `pending -> paid -> shipped -> delivered`. Orders require either a typed delivery address or both latitude and longitude; the Android client continues to submit device location with manual-address fallback.

## API and ports

| Service | Port | Main routes |
| --- | ---: | --- |
| Customer service | 8000 | `GET /health`, `POST /customer-login`, `GET /customers`, `POST /customers`, `GET /customers/{id}`, `GET /products`, `POST /customers/{id}/orders`, `GET /customers/{id}/orders`, `GET /customers/{id}/notifications`, `WS /ws/customers/{id}/orders`, `WS /ws/customer-updates` |
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
| `DATABASE_URL` | `sqlite:///./orders.db` | Customer-owned database; the consumer reads its outbox and writes customer notifications here. |
| `STAFF_DATABASE_URL` | `sqlite:///./staff.db` | Staff-owned database for staff login and notifications. |
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
- The customer and staff services own separate SQLite files. The consumer accesses both databases to relay events and persist each role's notifications; Docker stores the two files on one named volume.
- RabbitMQ provides at-least-once delivery. Notification persistence is idempotent by event ID; the consumer retries callback failures and republishes pending outbox records.
- RabbitMQ broker recovery and Docker component failures should be demonstrated during marking; automated tests cover the outbox fallback and duplicate-event behavior without requiring a live broker.
- Android is a customer workflow client; the staff workflows are web-only.

## Submission details

- Repository: https://github.com/Yeeted-Potato/Assignment2
- Final commit hash/tag: record the commit used to create the submission ZIP.
- The group/individual technical reports and demonstration video are separate assessment deliverables and are not generated by this project README.
