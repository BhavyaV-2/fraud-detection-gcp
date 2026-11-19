"""Train Isolation Forest on synthetic transactions and save the model."""

import numpy as np
import pickle
import os
from sklearn.ensemble import IsolationForest

np.random.seed(42)
N_NORMAL = 2000
N_INJECT = 100

# Feature order must match the scoring array in ai_model.py.
normal = np.column_stack([
    np.random.normal(500, 200, N_NORMAL).clip(10, 5000),    # INR 10-INR 5000
    np.random.randint(8, 22, N_NORMAL),                      # 8am-10pm
    np.random.choice([0, 1], N_NORMAL, p=[0.92, 0.08]),     # 92% known location
    np.random.randint(1, 5, N_NORMAL),                       # 1-4 txns/10min
])

anomalies = np.column_stack([
    np.random.uniform(80000, 200000, N_INJECT),              # High-value transactions
    np.random.choice([0, 1, 2, 3, 22, 23], N_INJECT),       # Overnight transactions
    np.ones(N_INJECT),                                        # always new location
    np.random.randint(10, 30, N_INJECT),                     # Transactions per ten-minute window
])

training_data = np.vstack([normal, anomalies])

print("Training Isolation Forest...")
model = IsolationForest(
    n_estimators=100,
    contamination=0.05,
    max_samples="auto",
    random_state=42,
)
model.fit(training_data)

test_normal = np.array([[500,    14, 0, 2]])
test_fraud = np.array([[150000,  3, 1, 25]])

s_normal = model.decision_function(test_normal)[0]
s_fraud = model.decision_function(test_fraud)[0]

print(f"  Normal score : {s_normal:.4f}  (should be POSITIVE)")
print(f"  Fraud  score : {s_fraud:.4f}  (should be NEGATIVE)")

assert s_normal > s_fraud, (
    f"Sanity check FAILED - normal({s_normal:.4f}) must exceed fraud({s_fraud:.4f})"
)
print("  Sanity check PASSED ")

out_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "process_transaction", "model.pkl")
)
with open(out_path, "wb") as f:
    pickle.dump(model, f)

size_kb = os.path.getsize(out_path) / 1024
print(f"\nModel saved -> {out_path}")
print(f"File size   : {size_kb:.1f} KB")
print("\nDone. Deploy to GCP Cloud Functions now.")
