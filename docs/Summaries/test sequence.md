# Assignment Test and Demonstration Sequence

This checklist collects the project checks and demo actions in one place. It is
intended to help gather evidence for the Assessment 3 Path B (RabbitMQ)
implementation; it cannot guarantee a mark. Check the original assignment brief
and marking rubric before submission, especially for report, video, performance,
and group-work requirements.

## 1. Prepare the workspace

From PowerShell, go to the repository root:


Use the project's virtual environment for Python checks:

```powershell
.\.venv\Scripts\Activate.ps1
```

Run the automated service tests:

```powershell
python -m pytest -v test_services.py
```

These tests use isolated temporary SQLite databases and do not require Docker or
a live RabbitMQ broker. They cover customer order creation and status changes,
database ownership, event idempotency, API/WebSocket behavior, and legacy-data
migration. They are not a live-broker outage/recovery demonstration.

Validate the Compose file and patch whitespace:

```powershell
docker compose config --quiet
git --no-pager diff --check
```

## 2. Start a clean demo deployment

Build the latest code and start RabbitMQ:

```powershell
docker compose build
docker compose up -d rabbitmq
```

For a fresh/demo-reset dataset only, seed both service databases:

```powershell
docker compose run --rm --no-deps customer-service python seed.py
```

> **Warning:** `seed.py` is destructive. It deletes existing customers, orders,
> products, history, and notifications before inserting the sample data. Do not
> run it if existing demo data must be preserved.

Start the services and check their status:

```powershell
docker compose up -d
docker compose ps
```

Wait until the services are healthy. Open:

- Customer login: <http://localhost:8000/>
- Staff site: <http://localhost:8001/>
- Customer API docs: <http://localhost:8000/docs>
- Staff API docs: <http://localhost:8001/docs>
- RabbitMQ management: <http://localhost:15672/> (user `orders`, password
  `orders-local-dev`)

Demo accounts after seeding:

- Customer: Evan, `evan@test.com`
- Staff: `sam@test.com`, password `dummypw`

## 3. Demonstrate normal order and live-update flow

1. Open the customer site and sign in as Evan.
2. Open the staff site in another browser tab/window and sign in as Sam. Keep
   the staff page open so its WebSocket notification connection is active.
3. Optionally open a second customer browser tab and leave it on the products
   view. This helps show stock updates across customer pages.
4. In the customer site, place an order for an in-stock product. Provide a
   delivery address if requested.
5. Show that:
   - The customer receives the order confirmation.
   - Staff receives one live new-order alert without refreshing.
   - Product stock refreshes on the open customer pages.
   - The notification records the event time and displays NZ local time.
6. Capture screenshots or video of both sides of the workflow and the updated
   product availability.
7. In staff **Update Status**, advance the order through valid transitions
   (`pending` → `paid` → `shipped` → `delivered`). Leave the customer order
   page open and show the status notification/update arriving live.

Saved notifications are history: reopening the page can restore previous
notifications. This does not place the order again. For a fresh demonstration,
use another order or reset the sample data only when it is safe to do so.

## 4. Demonstrate RabbitMQ and consumer activity

In a separate PowerShell window, follow the consumer, broker, and API logs:

```powershell
docker compose logs -f consumer rabbitmq customer-service staff-service
```

Place another customer order. Capture the consumer log showing the event being
processed and the RabbitMQ dashboard showing the `orders.events` queue. Messages
may disappear quickly because the consumer acknowledges successfully processed
messages; an empty queue after processing is normal.

For a recent log excerpt without following continuously:

```powershell
docker compose logs --since 10m consumer rabbitmq
```

## 5. Demonstrate broker-unavailable recovery

Do this only after recording the normal working flow. Keep the consumer and APIs
running, and have customer and staff pages open.

1. Stop only RabbitMQ:

   ```powershell
   docker compose stop rabbitmq
   ```

2. Place a new order from the customer site while RabbitMQ is stopped. The
   customer service should still accept the order because it first stores the
   order and its event in the transactional outbox. The consumer logs that
   publishing failed and the event remains pending in the outbox.
3. Restore RabbitMQ:

   ```powershell
   docker compose start rabbitmq
   docker compose ps
   ```

4. Watch the consumer logs:

   ```powershell
   docker compose logs -f consumer rabbitmq
   ```

5. Confirm the pending event is eventually processed, staff receives the new
   order alert, and customer stock reflects the order. Capture the failure,
   recovery, and delivered notification evidence.

Do not remove Docker volumes during this test. `docker compose down --volumes`
deletes persistent demo data.

## 6. Run focused idempotency tests

Run the tests for repeated event processing. They check saved notification
deduplication by event ID:

```powershell
python -m pytest -v `
  test_services.py::test_notification_consumer_is_idempotent `
  test_services.py::test_staff_order_notification_persists_once_and_broadcasts
```

These are automated application-level checks, not a substitute for the live
RabbitMQ recovery demonstration above.

## 7. Performance and Android checks

If the brief requires measured API response time, keep the Compose services
running and execute:

```powershell
python scripts/measure_response_time.py
```

Record the machine, date, request count, mean, p95, and whether the brief's
threshold was met. Treat earlier measurements as historical evidence; use the
result from the actual submission/demo environment.

If Android is part of the required demonstration, build the app:

```powershell
Set-Location android-client
.\gradlew.bat assembleDebug
Set-Location ..
```

Run it in the Android emulator against the customer service (`10.0.2.2:8000`).
Android uses the customer REST API; live WebSocket notifications are currently
web-client behavior.

## 8. Assemble submission evidence

Before submitting, collect and verify:

- [ ] Test output showing the focused automated tests passed.
- [ ] Screenshots or video of customer order placement, staff live alert,
  inventory refresh, and customer status update.
- [ ] RabbitMQ/consumer log evidence of an event being processed.
- [ ] RabbitMQ unavailable/recovery evidence, if required by the brief.
- [ ] Actual response-time measurements and conditions, if required.
- [ ] Android build/demo evidence, if required by the brief.
- [ ] Technical report and demonstration video in the required format.
- [ ] Final repository commit hash/tag used for the submission.
- [ ] No secrets, local database files, or unnecessary generated artifacts in
  the submission.

To record the current commit hash:

```powershell
git rev-parse HEAD
```

Check the final worktree and staged changes before creating any commit or
submission archive:

```powershell
git status --short
```

Refer to the assignment brief for the exact report/video format, evidence
requirements, marking criteria, and submission deadline.
