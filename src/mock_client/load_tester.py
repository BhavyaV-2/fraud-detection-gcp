"""Generate synthetic traffic and report HTTP ingestion throughput."""

import concurrent.futures
import os
import random
import sys
import time
import uuid
from datetime import datetime, timezone

import requests

API_URL = os.environ.get("API_URL", "http://localhost:8080")
N_REQUESTS = int(os.environ.get("N", 500))
MAX_WORKERS = 10

LOCATIONS = ["Mumbai", "Delhi", "Bangalore", "Chennai", "Hyderabad",
              "Pune", "Kolkata", "London", "Singapore", "New York"]
CATEGORIES = ["grocery", "electronics", "fuel", "restaurant",
              "transfer", "luxury", "pharmacy", "travel"]
USER_IDS = [f"user_{i:04d}" for i in range(1, 101)]


def generate_transaction(force_anomaly: bool = False) -> dict:
    """Generate a realistic transaction. ~10% are anomalous by default."""
    is_anomaly = force_anomaly or (random.random() < 0.10)

    if is_anomaly:
        amount = round(abs(random.normalvariate(75000, 25000)), 2)
        hour = random.choice([0, 1, 2, 3, 23])
        new_loc = 1
        velocity = random.randint(12, 25)
    else:
        amount = round(abs(random.normalvariate(800, 400)), 2)
        hour = random.randint(8, 21)
        new_loc = random.choices([0, 1], weights=[92, 8])[0]
        velocity = random.randint(1, 5)

    return {
        "transaction_id": str(uuid.uuid4()),
        "user_id": random.choice(USER_IDS),
        "amount": max(amount, 10.0),
        "location": random.choice(LOCATIONS),
        "hour_of_day": hour,
        "is_new_location": new_loc,
        "transaction_velocity": velocity,
        "merchant_category": random.choice(CATEGORIES),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def send_transaction(index: int) -> dict:
    """Send one transaction and return result dict."""
    payload = generate_transaction(force_anomaly=(index % 20 == 0))
    try:
        resp = requests.post(
            API_URL,
            json=payload,
            timeout=15,
            headers={"Content-Type": "application/json"},
        )
        return {
            "index": index,
            "status_code": resp.status_code,
            "transaction_id": payload["transaction_id"],
            "amount": payload["amount"],
            "success": resp.status_code == 202,
        }
    except requests.exceptions.Timeout:
        return {"index": index, "status_code": 0, "success": False, "error": "Timeout"}
    except requests.exceptions.ConnectionError:
        return {"index": index, "status_code": 0, "success": False, "error": "ConnectionError"}
    except Exception as exc:
        return {"index": index, "status_code": 0, "success": False, "error": str(exc)}


def main():
    print("\n" + "-" * 62)
    print("  GCP TRANSACTION PIPELINE - LOAD TESTER")
    print("-" * 62)
    print(f"  Target URL : {API_URL}")
    print(f"  Requests   : {N_REQUESTS}")
    print(f"  Workers    : {MAX_WORKERS} parallel threads")
    print("-" * 62 + "\n")

    print("  -> Sending test request first...")
    test = send_transaction(0)
    if not test.get("success"):
        print(f"\n  FAIL Test request FAILED: {test}")
        print("  Is your API_URL correct and the Cloud Function deployed?")
        print("  Local test: functions-framework --target ingest_transaction --port 8080")
        sys.exit(1)
    print(f"  PASS Test request succeeded (status {test['status_code']})\n")

    print(f"  -> Firing {N_REQUESTS} requests now...\n")
    start = time.time()
    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(send_transaction, i): i for i in range(N_REQUESTS)}
        done = 0
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
            done += 1
            if done % 50 == 0:
                print(f"  ... {done}/{N_REQUESTS} sent")

    elapsed = time.time() - start
    successes = sum(1 for r in results if r.get("success"))
    failures = N_REQUESTS - successes
    by_code = {}
    for r in results:
        c = r.get("status_code", 0)
        by_code[c] = by_code.get(c, 0) + 1

    print("\n" + "-" * 62)
    print("  RESULTS")
    print("-" * 62)
    print(f"  Total requests : {N_REQUESTS}")
    print(f"  Successful     : {successes}  (HTTP 202 Accepted)")
    print(f"  Failed         : {failures}")
    print(f"  Elapsed        : {elapsed:.2f}s")
    print(f"  Throughput     : {N_REQUESTS / elapsed:.1f} req/s")
    print(f"\n  Status breakdown:")
    for code, count in sorted(by_code.items()):
        print(f"    HTTP {code}: {count}")

    if failures > 0:
        errs = [r for r in results if not r.get("success")][:3]
        print("\n  FAIL First 3 failures:")
        for e in errs:
            print(f"     {e}")

    print("\n  PASS Next steps:")
    print("     GCP Console -> Pub/Sub -> transaction-topic -> Metrics (queue depth spike)")
    print("     GCP Console -> Cloud Functions -> process_transaction -> Logs")
    print("     GCP Console -> Firestore -> Approved_Transactions + Flagged_Transactions")
    print("-" * 62 + "\n")


if __name__ == "__main__":
    main()
