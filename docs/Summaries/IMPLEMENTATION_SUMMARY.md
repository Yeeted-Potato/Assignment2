# Implementation Summary

## Scope

Implemented the requested Assessment 3 **Path B (RabbitMQ message broker)** integration. No gRPC/Path A implementation was added.

## Backend split

- `customer_service.py` runs the customer REST API, serves the customer web app, hosts customer WebSocket connections, and owns customers, products, orders, order history, customer notifications, and the event outbox.
- `staff_service.py` runs independently and owns staff accounts and staff notifications; it obtains customer/order data and requests status changes through authenticated customer-service HTTP endpoints.
- `main.py` remains a compatibility import for the customer service, preserving the original `uvicorn main:app` customer-API command.
- `orders.db` and `staff.db` are separate SQLite databases with separate table ownership. Neither service directly queries or writes the other service's tables. The consumer connects to both to process events and save notifications. Docker places both files in a persistent volume, but they remain distinct database files.

## RabbitMQ and live updates

- Customer order creation and staff-initiated order status changes (proxied to the customer service) are committed together with their domain events to the customer service's transactional outbox.
- The separate consumer relays pending outbox events to the durable RabbitMQ `orders.events` queue with publisher confirms.
- `consumer.py` is a separate process. It relays unpublished outbox entries, consumes messages with manual acknowledgement, persists customer status notifications and staff new-order notifications idempotently by event ID, and retries the appropriate service callback on delivery failure.
- Malformed messages are routed to `orders.events.dead`.
- A new `order.created` event is saved idempotently as customer and staff notifications. Staff receives it through `/ws/staff/orders`; customer pages receive a sanitized `inventory.updated` event and reload product availability. The ordering customer receives their order notification.
- Status-change events are delivered to the affected customer over WebSocket. Both role-specific notification panels are shared across their web pages, reconnect, and restore saved notifications. Event timestamps are retained from the transactional outbox and displayed in `Pacific/Auckland` time, including when broker retries delay delivery.
- The demo seed reset removes legacy staff tables and cross-service foreign keys before dropping customer order tables, avoiding SQLite foreign-key failures when upgrading an earlier shared-database installation.

## Clients and compatibility

- The existing Android customer API routes and order response fields are retained; the Android client remains on port 8000.
- Staff pages are served by port 8001 and use staff-prefixed routes for staff-side customer/order views and status updates. Those routes proxy to the customer service rather than reading its database.
- The staff home page has a header-level Customer Client button leading to the customer login page, plus a live/recoverable new-order notification list.
- The shared live notification panel appears on all customer and staff web pages; product stock refreshes on every open customer page when a new order event arrives.
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
7. Repeated event processing produces one notification per event ID.
8. Separate-database tests verify customer tables are absent from the staff database and staff notifications are absent from the customer database.
9. A newly created order writes an `order.created` outbox event, persists notifications to both owners, updates connected customer product stock, and appears in the staff WebSocket panel.
10. Customer and staff APIs expose distinct route responsibilities.
11. The legacy database migration preserves staff accounts, staff notifications, and order history while removing staff-owned tables and cross-service foreign keys from the customer database.

`scripts/measure_response_time.py` supplies a measurable local API response-time check with a 250 ms p95 target. Results should be recorded from the target machine during the final demonstration/report; response time varies by machine and deployment.

Validation in this workspace: all 7 focused service and migration tests passed using temporary databases; the migration test includes a legacy cross-database foreign key. Python syntax checks passed for the migration and service modules. Docker Compose configuration and `git diff --check` pass. The 30-request loopback response-time check measured mean 17.80 ms and p95 27.31 ms (target p95 < 250 ms, pass). A live Docker/RabbitMQ run should still be repeated on the demonstration machine.

## Limitations

- Demo login and WebSocket access are not production-grade authentication.
- The consumer accesses both SQLite files to relay customer-owned outbox records and persist staff/customer notifications. The customer and staff APIs themselves retain independent data ownership.
- Automated tests use a temporary database and simulate broker unavailability; live RabbitMQ outage/recovery, browser WebSocket reconnection, and full two-client demonstration still need to be shown in the final demo.
- The assignment submission requires a final commit hash/tag and reports/video; record those at submission time.
