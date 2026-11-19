#!/usr/bin/env bash
# Deploy the HTTP ingester and Pub/Sub worker from the repository root.
set -euo pipefail
cd "$(dirname "$0")"

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID before deploying}"
REGION="${GCP_REGION:-us-central1}"
TOPIC_ID="${PUBSUB_TOPIC_ID:-transaction-topic}"
ALLOW_UNAUTHENTICATED="${ALLOW_UNAUTHENTICATED:-false}"

if [[ ! -f src/process_transaction/model.pkl ]]; then
    python src/train_model/train.py
fi

AUTH_FLAG="--no-allow-unauthenticated"
if [[ "$ALLOW_UNAUTHENTICATED" == "true" ]]; then
    AUTH_FLAG="--allow-unauthenticated"
fi

gcloud functions deploy ingest_transaction \
    --project="$GCP_PROJECT_ID" \
    --gen2 --runtime=python311 --region="$REGION" \
    --source=src/ingest --entry-point=ingest_transaction \
    --trigger-http "$AUTH_FLAG" \
    --set-env-vars="GCP_PROJECT_ID=$GCP_PROJECT_ID,PUBSUB_TOPIC_ID=$TOPIC_ID" \
    --memory=256MB --timeout=60s --min-instances=0 --max-instances=10

gcloud functions deploy process_transaction \
    --project="$GCP_PROJECT_ID" \
    --gen2 --runtime=python311 --region="$REGION" \
    --source=src/process_transaction --entry-point=process_transaction_event \
    --trigger-topic="$TOPIC_ID" --retry \
    --set-env-vars="GCP_PROJECT_ID=$GCP_PROJECT_ID" \
    --memory=512MB --timeout=120s --min-instances=0 --max-instances=20

gcloud functions describe ingest_transaction \
    --project="$GCP_PROJECT_ID" --region="$REGION" --gen2 \
    --format="value(serviceConfig.uri)"
