# Checkpoint 2 — RabbitMQ and WebSocket integration

**Date:** 2026-10-14

## Prototype scope

- Split the FastAPI backend into independently runnable customer (`customer_service.py`) and staff (`staff_service.py`) APIs while retaining the shared SQLite order data.
- Add customer order-created and staff order-status-changed events/outbox, durable RabbitMQ queue, independently run consumer, notification persistence, internal callbacks, and customer/staff WebSocket update/reconnect behavior.
- Add a live new-order notification list to the staff home page and move the Customer Client link into its header.
- Keep the Android-facing customer API routes and order response shape compatible with the existing mobile client.

## Verification evidence

- `test_services.py`: five focused checks passed against an isolated temporary SQLite database, including role-separated routes, shared order/status workflow, both outbox event types, failed-broker fallback, duplicate-notification idempotency, and customer/staff WebSocket delivery.
- `scripts/measure_response_time.py`: 30 sequential local `GET /products` requests; observed mean 17.80 ms, p95 27.31 ms against a p95 target under 250 ms.
- `docker compose config --quiet`: Compose configuration parsed successfully.
- Live RabbitMQ restart/retry and browser-driven reconnect remain demonstration checks. The Docker engine was unavailable during this checkpoint, so a live broker run was not recorded.

## Traceability

Code and executable evidence are linked in the [project README](../../README.md), [service tests](../../test_services.py), and [response-time check](../../scripts/measure_response_time.py). This checkpoint is a dated integration record; add the corresponding group-development commit hash and live demonstration evidence when those are available.
