# Deployment

Use the Google Cloud CLI and Bash (Git Bash, WSL, Linux, or macOS). Authenticate
with `gcloud auth login` and select a billing-enabled project you control.

## Prerequisites

Enable the required APIs, replacing the project placeholder:

```bash
export GCP_PROJECT_ID="your-project-id"
export GCP_REGION="us-central1"
export PUBSUB_TOPIC_ID="transaction-topic"

gcloud services enable cloudfunctions.googleapis.com run.googleapis.com \
  cloudbuild.googleapis.com artifactregistry.googleapis.com \
  eventarc.googleapis.com pubsub.googleapis.com firestore.googleapis.com \
  --project="$GCP_PROJECT_ID"

gcloud pubsub topics create "$PUBSUB_TOPIC_ID" --project="$GCP_PROJECT_ID"
```

Create the default **Firestore Native mode** database in your chosen location if
it does not already exist. Enabling the API alone does not create the database.
Skip topic creation if the topic already exists.

Ensure the deployment identity can deploy functions, use the runtime service
account, and configure Eventarc triggers. The runtime identity needs Pub/Sub
Publisher for ingestion and Firestore access (for example Cloud Datastore User)
for the worker. Configure the Eventarc trigger identity and service-agent
permissions required by your project's IAM policies. The script uses project
defaults; it does not create service accounts or grant IAM roles.

Install the pinned dependencies in a Python 3.11 environment. In Git Bash on
Windows, activate it with `source .venv/Scripts/activate`; on Linux/macOS use
`source .venv/bin/activate`.

## Deploy the functions

```bash
python src/train_model/train.py
bash deploy.sh
```

The ingestion endpoint requires authentication by default. To test it, give your
caller identity the Cloud Run Invoker role on the ingestion service, then send
an identity token:

```bash
export API_URL="$(gcloud functions describe ingest_transaction \
  --gen2 --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
  --format='value(serviceConfig.uri)')"

curl --fail-with-body "$API_URL" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"demo-user","amount":500,"hour_of_day":14}'
```

For a temporary demo using the bundled browser or mock clients, explicitly enable
public ingestion and redeploy:

```bash
export ALLOW_UNAUTHENTICATED=true
bash deploy.sh
export API_URL="$(gcloud functions describe ingest_transaction \
  --gen2 --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
  --format='value(serviceConfig.uri)')"
python src/mock_client/verify_deployment.py
N=50 python src/mock_client/load_tester.py
```

Requests can incur charges. Use synthetic data and budget alerts, and set
`ALLOW_UNAUTHENTICATED=false` and redeploy when the public demo is over.

## Verify processing

The deployed worker entry point is `process_transaction_event`, matching the
Pub/Sub Eventarc trigger. Its adapter invokes the same handler covered by HTTP
envelope tests. Storage failures raise exceptions so the enabled retry policy
can redeliver events. Malformed encoded payloads are logged and acknowledged.

Use the printed transaction IDs to inspect `Approved_Transactions` and
`Flagged_Transactions` in Firestore. Review the worker logs for scoring and
storage errors. Neither the dashboard nor a successful ingestion response proves
that the worker completed.

Retries do not provide an automatic dead-letter queue in this setup. Configure
retry retention, dead-letter routing, alerts, and least-privilege service accounts
separately before using the pipeline beyond a demonstration.

References: [Pub/Sub CloudEvent sample](https://docs.cloud.google.com/functions/docs/samples/functions-cloudevent-pubsub)
and [event-driven retry behavior](https://docs.cloud.google.com/run/docs/tips/function-retries).
