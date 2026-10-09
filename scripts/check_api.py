#checks the api endpoints the android app depends on
#run with: python scripts/check_api.py   (the server must already be running)
#this is the evidence recorded in docs/checkpoints/2026-10-09-checkpoint-1-android-to-api.md
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"

#the fields the android app reads in Customer.fromJson, Product.fromJson and Order.fromJson
ORDER_KEYS = ("id", "customer_id", "product_id", "quantity", "status",
              "delivery_address", "latitude", "longitude")

passed = 0
failed = 0


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print("  PASS  " + label)
    else:
        failed += 1
        print("  FAIL  " + label + "  " + str(detail))


def main():
    print("--- sign in ---")
    status, body = call("POST", "/customer-login", {"name": "Evan", "email": "evan@test.com"})
    check("login returns 200", status == 200, "got " + str(status))
    check("customer has id, name and email",
          all(k in body for k in ("id", "name", "email")), str(body))
    customer_id = body.get("id")

    status, body = call("POST", "/customer-login", {"name": "Nope", "email": "nope@test.com"})
    check("unknown customer returns 401", status == 401, "got " + str(status))

    print("--- products ---")
    status, body = call("GET", "/products")
    check("products returns 200", status == 200, "got " + str(status))
    check("each product has id, name, price and stock",
          all(all(k in p for k in ("id", "name", "price", "stock")) for p in body), str(body[:1]))

    print("--- order with a device location ---")
    status, body = call("POST", "/customers/%d/orders" % customer_id,
                        {"product_id": 1, "quantity": 2,
                         "latitude": -36.8485, "longitude": 174.7633})
    check("order with location is created", status == 200, "got %d %s" % (status, body))
    check("latitude and longitude stored",
          body.get("latitude") == -36.8485 and body.get("longitude") == 174.7633, str(body))
    check("new order status is pending", body.get("status") == "pending", str(body.get("status")))

    print("--- order with a typed address (the manual fallback) ---")
    status, body = call("POST", "/customers/%d/orders" % customer_id,
                        {"product_id": 2, "quantity": 1,
                         "delivery_address": "123 Queen Street, Auckland"})
    check("order with address is created", status == 200, "got %d %s" % (status, body))
    check("address stored", body.get("delivery_address") == "123 Queen Street, Auckland", str(body))
    check("no location when an address is used", body.get("latitude") is None, str(body.get("latitude")))

    print("--- validation the app relies on ---")
    status, body = call("POST", "/customers/%d/orders" % customer_id,
                        {"product_id": 1, "quantity": 1})
    check("order with no delivery details returns 422", status == 422, "got " + str(status))

    status, body = call("POST", "/customers/%d/orders" % customer_id,
                        {"product_id": 3, "quantity": 999, "delivery_address": "x"})
    check("not enough stock returns 400", status == 400, "got %d %s" % (status, body.get("detail")))

    status, body = call("POST", "/customers/%d/orders" % customer_id,
                        {"product_id": 1, "quantity": 0, "delivery_address": "x"})
    check("quantity of 0 is rejected", status in (400, 422), "got " + str(status))

    status, body = call("POST", "/customers/999/orders",
                        {"product_id": 1, "quantity": 1, "delivery_address": "x"})
    check("unknown customer on create returns 404", status == 404, "got " + str(status))

    print("--- listing orders ---")
    status, body = call("GET", "/customers/%d/orders" % customer_id)
    check("list orders returns 200", status == 200, "got " + str(status))
    check("the two new orders are there", len(body) == 2, "got " + str(len(body)))
    check("every order has all 8 fields the app reads",
          all(all(k in o for k in ORDER_KEYS) for o in body),
          str(sorted(body[0].keys()) if body else []))

    status, body = call("GET", "/customers/999/orders")
    check("orders for an unknown customer returns 404", status == 404, "got " + str(status))

    print("")
    print("=== %d passed, %d failed ===" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
