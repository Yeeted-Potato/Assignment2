# Implementation Summary

## Scope

Implemented the requested Assessment 3 **Path B (RabbitMQ message broker)** integration. No gRPC/Path A implementation was added.

## Backend split

- `customer_service.py` runs the customer REST API, serves the customer web app, hosts customer WebSocket connections, and exposes customer order/notification reads.
- `staff_service.py` runs independently and owns staff login, order administration, and status transitions.
- `main.py` remains a compatibility import for the customer service, preserving the original `uvicorn main:app` customer-API command.
- Both APIs and the worker use the existing shared SQLite database to retain shared customer/order state and Android API compatibility.

## RabbitMQ and live updates

- Staff order status changes and their `order.status_changed` domain event are committed together to a transactional outbox.
- The staff API attempts immediate publish to the durable RabbitMQ `orders.events` queue with publisher confirms. When RabbitMQ is unavailable, it reports `event_delivery: "pending"` and leaves the event available for retry.
- `consumer.py` is a separate process. It relays unpublished outbox entries, consumes messages with manual acknowledgement, stores customer notifications idempotently by event ID, and retries the customer-service callback on delivery failure.
- Malformed messages are routed to `orders.events.dead`.
- The consumer callback broadcasts an event to the affected customer's WebSocket connections. The web UI reconnects automatically and reloads orders and notifications on reconnect.

## Clients and compatibility

- The existing Android customer API routes and order response fields are retained; the Android client remains on port 8000.
- Staff pages are served by port 8001 and use staff-prefixed routes for staff-side customer/order views and status updates.
- Customer-side order validation continues to require an address or device coordinates; partial/out-of-range coordinates are rejected.

## Running and configuration

- `docker-compose.yml` starts RabbitMQ, customer service, staff service, and consumer; it configures a non-guest RabbitMQ account for container-to-container access. `Dockerfile` builds the shared Python image.
- `README.md` documents local and Compose setup, endpoints, variables, sample accounts/data, Android build/test commands, demo steps, and known limitations.
- `requirements.txt` includes Pika for RabbitMQ.

## Verification

Automated service tests are in `test_services.py` and check:

1. A customer can create an order that is visible to the staff workflow.
2. Stock changes with order creation and is persisted.
3. Missing delivery information is rejected.
4. Staff status transitions persist and write an outbox event.
5. Invalid status transitions are rejected.
6. Broker-unavailable status updates report pending delivery.
7. Repeated event processing produces one notification.
8. Customer and staff APIs expose distinct route responsibilities.

`scripts/measure_response_time.py` supplies a measurable local API response-time check with a 250 ms p95 target. Results should be recorded from the target machine during the final demonstration/report; response time varies by machine and deployment.

Validation in this workspace ran 30 sequential loopback `GET /products` requests: mean 17.80 ms and p95 27.31 ms (target p95 < 250 ms, pass). Four focused pytest tests passed using a temporary SQLite database, including the WebSocket callback. Docker Compose syntax validated, but a live Docker/RabbitMQ run could not be performed because the Docker engine was unavailable.

## Limitations

- Demo login and WebSocket access are not production-grade authentication.
- SQLite is shared by two services and the consumer for assignment/demo simplicity; use service-owned databases and a production database for deployment.
- Automated tests use a temporary database and simulate broker unavailability; live RabbitMQ outage/recovery, browser WebSocket reconnection, and full two-client demonstration still need to be shown in the final demo.
- The assignment submission requires a final commit hash/tag and reports/video; record those at submission time.
