# Checkpoint 2 — RabbitMQ and WebSocket integration

**Date:** 2026-10-14

## Prototype scope

- Split the FastAPI backend into independently runnable customer (`customer_service.py`) and staff (`staff_service.py`) APIs while retaining the shared SQLite order data.
- Add the staff status-change event/outbox, durable RabbitMQ queue, independently run consumer, notification persistence, internal customer-service callback, and customer WebSocket update/reconnect behavior.
- Keep the Android-facing customer API routes and order response shape compatible with the existing mobile client.

## Verification evidence

- `test_services.py`: four focused checks passed against an isolated temporary SQLite database, including role-separated routes, shared order/status workflow, failed-broker outbox state, duplicate-event idempotency, and internal-event-to-WebSocket delivery.
- `scripts/measure_response_time.py`: 30 sequential local `GET /products` requests; observed mean 17.80 ms, p95 27.31 ms against a p95 target under 250 ms.
- `docker compose config --quiet`: Compose configuration parsed successfully.
- Live RabbitMQ restart/retry and browser-driven reconnect remain demonstration checks. The Docker engine was unavailable during this checkpoint, so a live broker run was not recorded.

## Traceability

Code and executable evidence are linked in the [project README](../../README.md), [service tests](../../test_services.py), and [response-time check](../../scripts/measure_response_time.py). This checkpoint is a dated integration record; add the corresponding group-development commit hash and live demonstration evidence when those are available.
