# Message Broker Event Flows

This document describes how customer order creation and staff order-status
updates flow through the Path B RabbitMQ integration.

## Components and responsibilities

- **Customer service (`customer_service.py`, port 8000):** owns orders and
  customer data in `orders.db`. It records each order change and its event
  together in a database transaction.
- **Staff service (`staff_service.py`, port 8001):** owns staff accounts and
  staff notifications in `staff.db`. It proxies staff order changes to the
  customer service over authenticated internal REST.
- **Transactional outbox (`domain_event_outbox` in `orders.db`):** stores an
  event durably in the same transaction as its associated order change.
- **Standalone consumer (`consumer.py`):** periodically reads unpublished
  outbox rows, publishes them to RabbitMQ, consumes broker events, persists
  notifications, and calls internal API callbacks to push WebSocket updates.
- **RabbitMQ (`broker.py`):** hosts the durable `orders.events` queue and the
  dead-letter queue `orders.events.dead`.
- **WebSocket clients:** customer pages receive personal order/status events and
  sanitized global inventory events; staff pages receive new-order alerts.

The customer and staff APIs do not publish directly to RabbitMQ. They commit
domain events to the outbox; the separate consumer process is the RabbitMQ
publisher and consumer.

## Scenario 1: Customer places an order

1. The customer web or Android client sends an HTTP request to the customer
   service:

   ```text
   POST /customers/{customer_id}/orders
   ```

2. The customer service validates the customer, product, requested quantity,
   and available stock. If validation succeeds, it creates the order and
   decreases product stock.
3. In the same database transaction, the service records the initial
   `pending` status history and an `order.created` outbox event. The event
   includes an event ID and order/customer/product details, quantity, and
   remaining stock.
4. The service commits the transaction and returns the created order to the
   client. RabbitMQ is not needed to complete this HTTP response; the outbox
   ensures the event remains pending if the broker is unavailable.
5. A background relay thread in the standalone consumer checks the outbox about
   every two seconds. It selects unpublished rows and publishes each event to
   the durable `orders.events` queue using a persistent message and RabbitMQ
   publisher confirms.
6. After a confirmed publish, the relay marks that outbox row as published.
   If RabbitMQ is unavailable or publish is not confirmed, the row remains
   unpublished and will be retried by a later relay pass.
7. The consumer receives the queued event with manual acknowledgement enabled.
   For an `order.created` event it:
   - Saves one staff notification in `staff.db`, keyed by event ID.
   - Saves one customer order notification in `orders.db`, also keyed by event
     ID.
   - Adds the original outbox timestamp to the event if it is not already
     present.
8. The consumer calls the customer service's authenticated internal event
   callback. The customer service:
   - Sends the full order-created event to the ordering customer's personal
     WebSocket connection, if connected.
   - Sends a separate sanitized `inventory.updated` event to all connected
     customer pages. This event contains product ID and remaining stock rather
     than customer/order details.
9. After the customer callback succeeds, the consumer calls the staff
   service's authenticated internal event callback. The staff service
   broadcasts the order-created event to connected staff WebSocket clients.
10. After all required callbacks succeed, the consumer acknowledges the
    RabbitMQ delivery. The staff and customer web pages update their live
    notification panels; customer pages also refresh product availability.
11. If the customer closes their browser, the persisted customer notification
    remains available from the customer notifications endpoint and is restored
    after the customer signs in again. Restoring this history does not place
    the order again.

## Scenario 2: Staff updates an order's status

1. A staff member selects a status in the staff web client. The client sends a
   request to the staff service:

   ```text
   PATCH /staff/orders/{order_id}
   ```

2. The staff service does not write to `orders.db`. It forwards the request to
   the customer service's authenticated internal REST endpoint:

   ```text
   PATCH /internal/staff/orders/{order_id}/status
   ```

3. The customer service checks that the order exists and that the transition is
   allowed (`pending` → `paid` → `shipped` → `delivered`).
4. In one database transaction, the customer service changes the order status,
   adds an order-status-history row, and writes an `order.status_changed` event
   to the outbox. The event contains its ID, order/customer IDs, previous
   status, and new status.
5. The customer service commits the transaction and returns the changed order
   through the staff service to the browser. The response indicates that event
   delivery is pending; the status update is not rolled back just because
   RabbitMQ is temporarily unavailable.
6. The standalone consumer's outbox relay publishes the status event to the
   durable `orders.events` queue with publisher confirms and marks the outbox
   row published after confirmation.
7. The consumer receives the event and saves a customer notification in
   `orders.db`, keyed by event ID so repeated deliveries do not create duplicate
   notification rows.
8. The consumer calls the customer service's authenticated internal event
   callback. The customer service broadcasts the status event to the affected
   customer's WebSocket connection.
9. Once the callback succeeds, the consumer acknowledges the RabbitMQ
   delivery. The customer page updates its notification panel and order status
   without requiring a manual refresh.

No staff notification is generated for a status change in the current
implementation. Staff initiated the change and receives the immediate REST
response; the broker event is used to notify the affected customer.

## Delivery, retries, and duplicate protection

- **Broker unavailable before publish:** the order/status transaction has
  already committed with an outbox row. The relay keeps retrying that row until
  RabbitMQ confirms the publish.
- **Callback unavailable after consume:** the consumer logs the callback
  failure, negatively acknowledges the message with `requeue=True`, and
  RabbitMQ can deliver it again after the callback/service recovers.
- **Repeated delivery:** customer and staff notification tables use unique
  event IDs. Consumer persistence checks for an existing event ID before
  inserting a notification, so retrying persistence is idempotent.
- **Malformed or unprocessable event:** the consumer negatively acknowledges
  it with `requeue=False`; RabbitMQ routes it to `orders.events.dead` using the
  configured dead-letter routing key.
- **Publisher confirms:** these confirm broker acceptance of a published
  message. The outbox is marked published only after a confirmed publish.
- **Acknowledgement:** a consumed event is acknowledged only after notification
  persistence and the required service callbacks succeed.

Because delivery is at least once, an API callback can be invoked again if a
failure occurs after an earlier callback succeeded but before the consumer
acknowledges the RabbitMQ message. Notification persistence is idempotent, but
WebSocket clients may still see a repeated broadcast in that narrow retry
window.

## Event summary

| Event type | Created by | Stored in outbox by | Notifications saved in | Live destination |
|---|---|---|---|---|
| `order.created` | Customer order request | Customer service | Customer DB and staff DB | Ordering customer's WebSocket, all customer inventory sockets (sanitized event), and staff WebSockets |
| `order.status_changed` | Staff status request, forwarded to customer service | Customer service | Customer DB | Affected customer's WebSocket |

## How to observe the flow

Start the services and follow logs in PowerShell:

```powershell
docker compose logs -f consumer rabbitmq customer-service staff-service
```

Place a customer order or update an order status while the logs are running.
The consumer reports the processed event and its event ID. RabbitMQ's
management UI is available at <http://localhost:15672/>; sign in with the
local-development credentials documented in `README.md` and inspect
**Queues → `orders.events`**. Messages may be acknowledged quickly, so an empty
queue after successful processing is normal.




Yes, the staff-to-customer proxy is a normal service pattern. The staff service receives the staff request and forwards order operations to the customer service over internal REST. The customer service owns the order data, so it validates and updates the order without the staff service reaching into orders.db directly. That supports the two-service split and clear database ownership.

For the RabbitMQ flow, the roles are:

Event producer: The customer service creates order.created and order.status_changed events, recording them in its transactional outbox alongside the order change. For staff status updates, the staff service forwards the request first; the customer service then creates the event. See customer_service.py.

Publisher: The outbox relay in consumer.py reads unpublished outbox entries and publishes them to RabbitMQ, using broker.py for the broker connection and publisher confirms.
Broker: RabbitMQ, with the orders.events queue.

Consumer: The separately deployed consumer.py process also consumes messages from that queue. It persists notifications, calls the services’ internal event endpoints, and acknowledges messages after successful processing.

Based on the Path B requirements we discussed, this design appears to fit: the APIs run separately from a consumer process, and the flow includes acknowledgement, retry and duplicate handling. One detail worth describing accurately in your report: the publisher relay and queue consumer are two roles in the same standalone consumer.py process, not two separate executables. 