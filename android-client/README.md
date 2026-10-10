# Customer Orders — Android client

Native Android client for the Customer Orders system. This is the **Customer**
role of the shared workflow: a customer signs in, browses their orders, and
places new ones. Staff work with the same orders through the web client.

Built with **Java and XML Views** using **Android platform APIs only**, matching
the COMP713 Week 8 and Week 9 starter projects. No Retrofit, OkHttp, Gson,
AppCompat or Compose — `java.net` for HTTP, `org.json` for JSON,
`LocationManager` for location, `ExecutorService` for background work.

## Screens

| # | Screen | Real API calls | Purpose |
|---|--------|----------------|---------|
| 1 | `MainActivity` — sign in | `POST /customer-login` | Identify the customer |
| 2 | `OrderListActivity` — my orders | `GET /products`, `GET /customers/{id}/orders` | See each order and its current status |
| 3 | `CreateOrderActivity` — new order | `GET /products`, `POST /customers/{id}/orders` | Place an order with a delivery location |

## The shared workflow

1. The customer signs in and places an order **on the phone**.
2. The order is stored by the API and appears on the **staff web client**.
3. Staff advance its status (`pending → paid → shipped → delivered`).
4. The customer pulls to the order list **on the phone** and sees the new
   status, because the app always re-reads from the API rather than caching.

One user's action therefore changes what the other user can see and do.

## Mobile capability — device location with a manual fallback

Screen 3 supports the delivery workflow using the phone's **coarse foreground
location**, with a typed address as the fallback. This maps directly onto the
`orders.delivery_address`, `orders.latitude` and `orders.longitude` columns.

Week 9 rules the implementation follows:

- only `ACCESS_COARSE_LOCATION` is requested, and only in the foreground
- the fix is **one-shot** (`requestSingleUpdate`), not a continuous stream
- coordinates are **never invented** — if there is no usable fix the app says so
- a stale cached fix is detected and rejected rather than presented as current
- each failure mode has its own message, and every one of them points at the
  typed-address fallback, so a broken location never blocks an order

| Situation | What the app does |
|-----------|-------------------|
| Permission granted, fix arrives | Sends lat/lon with the order |
| Permission denied | "type a delivery address instead" |
| Location services switched off | "turn them on, or type an address instead" |
| No fix within 10 seconds | "try again, or type an address instead" |
| Only an old cached fix | Rejected: "only an old location was found" |
| No location hardware at all | App still runs — the feature is optional in the manifest |

## Prerequisites

- Android Studio (or the Android SDK command line tools)
- Android SDK platform **34** and build-tools **34.0.0**
- JDK **17** or newer (AGP 8.5.2)
- The Customer Orders API running — see the repository root README

## Setup and run

1. Open the `android-client` folder in Android Studio and let it sync.
   `local.properties` (with `sdk.dir`) is generated automatically.
2. Start the backend API first:
   ```
   python seed.py
   uvicorn main:app --reload
   ```
3. Run the `app` configuration on an emulator or device.

### Pointing at the backend

The default base URL is `http://10.0.2.2:8000`, which is the **emulator's alias
for the development machine's own localhost**.

- **Physical device:** change `ApiClient.BASE_URL` to the host machine's LAN
  address, e.g. `http://192.168.1.20:8000`, and put the phone on the same Wi-Fi.
- **Cleartext HTTP** is permitted for the local dev hosts only, via
  `res/xml/network_security_config.xml`. Every other host requires HTTPS.

## Test accounts

From `seed.py` in the backend:

| Role | Name | Email | Password |
|------|------|-------|----------|
| Customer | Evan | `evan@test.com` | — |
| Customer | Bob | `bob@test.com` | — |

Sign in with the name **and** email. Products available: Keyboard, Mouse, Monitor.

## Error handling

The app separates three failure classes so the user gets a useful message:

| Class | Example | Shown as |
|-------|---------|----------|
| API rejection | unknown customer (401), not enough stock (400) | The server's own message |
| Communication failure | API not running, no network | "Could not reach the server… Try again" |
| Bad response | malformed JSON | "Something went wrong" |

Loading, empty and error states are implemented on every screen, with a retry
action where retrying makes sense.

## Lifecycle and threading

- All network work runs on a shared background `ExecutorService`; the UI thread
  never blocks. This follows the Week 9 rule against network work on the main thread.
- The pool is **not** shut down in `onDestroy()`, because that would abandon
  in-flight work on every rotation. Callbacks check `isDestroyed()` before
  touching a view instead.
- Form fields, error text and a captured location survive rotation via
  `onSaveInstanceState`.
- An in-flight location request is cancelled in `onDestroy()` so it can never
  call back into a dead screen.

> **Trade-offs, kept brief for marking.** Two deliberate choices depart from what the
> Week 9 lecture suggests, and both are worth a line in the individual report:
>
> 1. **Location API.** `LocationManager.requestSingleUpdate` and `getBestProvider` are
>    deprecated in favour of the Fused Location Provider. The platform API is used anyway,
>    because the course teaches it and Fused would pull in the first external dependency
>    (Google Play services). This is also the only source of compiler warnings, suppressed
>    at the two call sites.
> 2. **Rotation state.** The lecture recommends Jetpack `ViewModel` + repository for state
>    that must survive rotation. This client uses the platform `onSaveInstanceState` instead,
>    for the same no-external-dependencies reason. The cost is that a request in flight
>    during rotation is restarted rather than retained.

## Known limitations

- Only the **Customer** role is implemented. Staff actions (advancing order
  status) are on the web client, which is correct for this role but means the
  app cannot complete the whole workflow alone.
- No authentication: sign in is a name/email match only, inherited from the
  Assessment 2 baseline.
- Product names are joined client-side from `GET /products`, matching what the
  web client already does. A single enriched `GET /orders/{id}` response would
  remove that second request.
- Orders are re-read on every resume rather than pushed; live updates are a
  separate WebSocket deliverable.
