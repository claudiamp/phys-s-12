# Smart Pillbox — Backend (AWS SAM)

Serverless backend for the Smart Pillbox. It ingests "lid opened" messages from the ESP32 via
AWS IoT Core, records one "pill taken" event per day in DynamoDB, waits one hour, then sends an
"okay to eat" FCM push. It also exposes a small, API-key-protected REST API the mobile app uses
to read history and register its push token.

## Architecture

```
ESP32 --(MQTT: pillbox/opened)--> AWS IoT Core --(IoT Rule)--> Ingest Lambda
                                                                  |  writes 1 item/day (conditional)
                                                                  v
                                                              DynamoDB  <---- API Lambda <--- API Gateway <--- App (GET /events, POST /token)
                                                                  ^                (Lambda authorizer checks x-api-key)
                                                                  |
     Ingest also StartExecution --> Step Functions (Wait 3600s) --> Notify Lambda --(FCM v1)--> App push "okay to eat"
```

## Files

```
backend/
  template.yaml                  # SAM template (table, API, 4 Lambdas, state machine)
  samconfig.toml.example         # copy to samconfig.toml to save deploy settings
  statemachine/reminder.asl.json # Wait 3600s -> invoke NotifyFunction
  src/
    package.json                 # type: module, dep: firebase-admin
    authorizer.mjs               # REQUEST authorizer, validates x-api-key
    api.mjs                      # GET /events + POST /token
    ingest.mjs                   # IoT rule target, records the day + starts the reminder
    notify.mjs                   # Step Functions target, sends the FCM push
    lib/dynamo.mjs               # DynamoDB helpers
    lib/time.mjs                 # Lima time helpers
  .gitignore
```

All four Lambdas share the same `CodeUri: src/` and run on `nodejs24.x` (arm64). The AWS SDK v3
clients (`@aws-sdk/*`) are provided by the runtime; only `firebase-admin` is installed from
`src/package.json`.

## Prerequisites

- **AWS CLI** installed and configured (`aws configure`) with credentials that can create the
  stack's resources, using region **us-east-1**.
- **AWS SAM CLI** installed.
- **Node.js 24** (matches the Lambda runtime; used by `sam build` to install dependencies).
- A **Firebase project** (for the FCM push).

## Setup

Run everything below from this `backend/` directory.

### 1. Create a Firebase project and download a service-account key

In the [Firebase console](https://console.firebase.google.com/): create (or open) your project,
then go to **Project settings -> Service accounts -> Generate new private key**. Save the
downloaded JSON here as `service-account.json` (it is gitignored).

### 2. Store the service-account JSON in SSM Parameter Store (SecureString)

The Notify Lambda reads this at runtime to talk to FCM. The parameter name must match the SAM
default `FcmServiceAccountParam` (`/pillbox/fcm-service-account`):

```bash
aws ssm put-parameter \
  --name /pillbox/fcm-service-account \
  --type SecureString \
  --value file://service-account.json \
  --region us-east-1
```

### 3. Generate an API key

This shared secret protects the REST API. The app sends it in the `x-api-key` header. Generate one
and keep it — you pass it to the deploy in the next step and to the app's `.env`:

```bash
openssl rand -hex 24
```

### 4. Build

```bash
sam build
```

### 5. Deploy

```bash
sam deploy --guided
```

Answer the prompts:

- **Stack Name**: `pillbox`
- **AWS Region**: `us-east-1`
- **Parameter ApiKey**: paste the key from step 3
- **Parameter FcmServiceAccountParam**: accept the default `/pillbox/fcm-service-account`
- **Confirm changes before deploy**: your choice
- **Allow SAM CLI IAM role creation** (`CAPABILITY_IAM`): `y`
- **Disable rollback**: `N`
- **Save arguments to configuration file**: `y` (writes `samconfig.toml`; see
  `samconfig.toml.example` for the equivalent values)

When the deploy finishes, note the **`ApiBaseUrl`** output — it looks like
`https://abc123.execute-api.us-east-1.amazonaws.com/Prod`. The stack also outputs `TableName` and
`StateMachineArn`. `ApiKey` is intentionally **not** output (it is `NoEcho`).

You give `ApiBaseUrl` and the same `ApiKey` value to the mobile app (see `../app/README.md`).

### 6. Point the ESP32 at IoT Core and test

The ESP32 firmware already publishes to IoT Core using the endpoint, topic (`pillbox/opened`), and
client id (`pillbox-esp32`) in `../Arduino/secrets.h`. Fill in your WiFi and device certificates
there and flash it (see the root README).

To test the whole cloud path without the hardware, publish a message yourself. This is the exact
message shape the ESP32 sends:

```bash
aws iot-data publish \
  --topic pillbox/opened \
  --cli-binary-format raw-in-base64-out \
  --payload '{"event":"pillbox_opened","device":"pillbox-esp32","timestamp":"2026-07-10T08:30:00"}' \
  --region us-east-1
```

The first publish for a given date records the event and starts the 1-hour reminder; publishing
again the same day is a no-op (see below). One hour later the Notify Lambda sends the push to every
registered token.

## Data model

One DynamoDB table (`PillboxTable`, CloudFormation-generated name, passed to the functions as
`TABLE_NAME`). Generic `pk` (HASH) / `sk` (RANGE) keys, `PAY_PER_REQUEST` billing:

- **Event item — one per day.** The Ingest Lambda writes it with a conditional
  `attribute_not_exists(pk)` put, so only the **first** lid opening of the day is stored:

  ```
  { pk: "EVENTS", sk: "<YYYY-MM-DD>", takenAt: "<YYYY-MM-DDTHH:MM:SS>", device: "<id>", createdAt: "<ISO8601 UTC>" }
  ```

- **Token item — one per registered device.** Upserted by `POST /token`:

  ```
  { pk: "TOKENS", sk: "<fcmToken>", updatedAt: "<ISO8601 UTC>" }
  ```

`sk` for events is the **local** date (`timestamp.slice(0,10)`). The device sends local Peru time
(GMT-5, no DST, no timezone suffix), so no timezone conversion is done; `lib/time.mjs` only
computes Lima time as a fallback when a timestamp is missing.

## REST API

Every request must include the header `x-api-key: <your ApiKey>`; the `AuthorizerFunction` REQUEST
authorizer validates it and returns 401 otherwise.

- `GET /events` -> `200 { "events": [ { "date": "YYYY-MM-DD", "takenAt": "YYYY-MM-DDTHH:MM:SS" }, ... ] }`
  sorted ascending by date.
- `POST /token` with body `{ "token": "<fcm token>" }` -> `200 { "ok": true }` (upserts the token;
  `400` if `token` is missing).

## The 1-hour reminder (Step Functions)

When the Ingest Lambda records a new day, it starts a **Standard** Step Functions execution
(`ReminderStateMachine`) with input `{ "date": "YYYY-MM-DD", "takenAt": "...", "trigger": "pill" }`.
The state machine (`statemachine/reminder.asl.json`) simply **waits 3600 seconds**, then invokes
the **Notify** Lambda, which reads all registered tokens and sends the multicast push:

- Title: `Okay to eat 🍽️`
- Body: `It's been 1 hour since your levothyroxine — you can eat now.`

The execution name is `pill-<date>`, so repeated openings on the same day never launch a second
reminder.

## Reading logs

Tail a function's CloudWatch logs with `sam logs` (uses the stack name from `samconfig.toml`):

```bash
sam logs --stack-name pillbox --name IngestFunction --tail
sam logs --stack-name pillbox --name NotifyFunction --tail
sam logs --stack-name pillbox --name ApiFunction --tail
sam logs --stack-name pillbox --name AuthorizerFunction --tail
```
