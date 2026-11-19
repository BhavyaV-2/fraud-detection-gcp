"""Send sample transactions for post-deployment verification."""

import os
import sys
import time
import uuid

import requests

INGEST_URL = os.environ.get(
    "API_URL",
    "https://YOUR_REGION-YOUR_PROJECT_ID.cloudfunctions.net/ingest_transaction",
)


def check(label: str, ok: bool, detail: str = "") -> bool:
    icon = "PASS" if ok else "FAIL"
    print(f"  {icon} {label}", end="")
    if detail:
        print(f"  ({detail})", end="")
    print()
    return ok


def main():
    print("\n" + "-" * 58)
    print("  GCP PIPELINE VERIFICATION")
    print("-" * 58)
    print(f"  Endpoint: {INGEST_URL}\n")

    if "YOUR_REGION" in INGEST_URL:
        print("  FAIL Update API_URL with your real Cloud Function URL first.")
        print("     export API_URL=https://REGION-PROJECT.cloudfunctions.net/ingest_transaction")
        sys.exit(1)

    all_ok = True

    print("[1] Sending NORMAL transaction (INR 450, 2pm, known location)...")
    normal = {
        "transaction_id": str(uuid.uuid4()),
        "user_id": "verify_user_001",
        "amount": 450.0,
        "location": "Bangalore",
        "hour_of_day": 14,
        "is_new_location": 0,
        "transaction_velocity": 2,
        "merchant_category": "grocery",
    }
    try:
        r = requests.post(INGEST_URL, json=normal, timeout=20)
        ok = check("Ingest accepted", r.status_code == 202, f"HTTP {r.status_code}")
        all_ok &= ok
        if ok:
            print(f"     transaction_id: {normal['transaction_id']}")
    except Exception as exc:
        all_ok = check("Ingest reachable", False, str(exc)) and all_ok

    print("\n[2] Sending ANOMALOUS transaction (INR 175,000, 3am, new location)...")
    fraud = {
        "transaction_id": str(uuid.uuid4()),
        "user_id": "verify_user_001",
        "amount": 175000.0,
        "location": "New York",
        "hour_of_day": 3,
        "is_new_location": 1,
        "transaction_velocity": 18,
        "merchant_category": "transfer",
    }
    try:
        r = requests.post(INGEST_URL, json=fraud, timeout=20)
        ok = check("Ingest accepted", r.status_code == 202, f"HTTP {r.status_code}")
        all_ok &= ok
        if ok:
            print(f"     transaction_id: {fraud['transaction_id']}")
    except Exception as exc:
        all_ok = check("Ingest reachable", False, str(exc)) and all_ok

    print("\n[3] Sending invalid payload (missing required fields)...")
    try:
        r = requests.post(INGEST_URL, json={"bad": "payload"}, timeout=10)
        all_ok &= check("Returns HTTP 400", r.status_code == 400, f"HTTP {r.status_code}")
    except Exception as exc:
        all_ok = check("Returns HTTP 400", False, str(exc)) and all_ok

    print("\n[4] Waiting 30 seconds for Cloud Function to process...")
    for remaining in range(30, 0, -5):
        print(f"     {remaining}s ...", end="\r")
        time.sleep(5)
    print()

    print("\n" + "-" * 58)
    print("  MANUAL VERIFICATION IN GCP CONSOLE")
    print("-" * 58)
    print(f"""
  1. GCP Console -> Firestore -> Data -> Approved_Transactions
     Filter by user_id = 'verify_user_001'
     -> Should contain INR 450 transaction with is_flagged = false

  2. GCP Console -> Firestore -> Data -> Flagged_Transactions
     Filter by user_id = 'verify_user_001'
     -> Should contain INR 175,000 transaction with is_flagged = true

  3. GCP Console -> Cloud Functions -> process_transaction -> Logs
     -> Should show APPROVED and FLAGGED log lines for the two transactions

  Normal txn ID : {normal['transaction_id']}
  Fraud  txn ID : {fraud['transaction_id']}
""")

    print("  " + ("PASS All automated checks passed!" if all_ok else "FAIL Some checks failed - see above"))
    print("-" * 58 + "\n")


if __name__ == "__main__":
    main()
