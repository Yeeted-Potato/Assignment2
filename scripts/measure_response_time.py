import statistics
import sys
import time
import urllib.error
import urllib.request


URL = "http://127.0.0.1:8000/products"
REQUESTS = 30
P95_TARGET_MS = 250


def main():
    samples_ms = []
    for request_number in range(REQUESTS):
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(URL, timeout=5) as response:
                if response.status != 200:
                    raise RuntimeError(f"Request {request_number + 1} returned {response.status}")
                response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"Request {request_number + 1} failed: {exc}", file=sys.stderr)
            return 1
        samples_ms.append((time.perf_counter() - started) * 1000)

    ordered = sorted(samples_ms)
    p95_index = max(0, (95 * len(ordered) + 99) // 100 - 1)
    p95_ms = ordered[p95_index]
    mean_ms = statistics.mean(samples_ms)
    print(
        f"GET {URL} | n={REQUESTS} sequential localhost requests | "
        f"mean={mean_ms:.2f} ms | p95={p95_ms:.2f} ms | "
        f"target p95 < {P95_TARGET_MS} ms"
    )
    if p95_ms >= P95_TARGET_MS:
        print("FAIL: response-time acceptance target was not met.", file=sys.stderr)
        return 1
    print("PASS: response-time acceptance target met.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
