# Smart Pillbox

A personal, single-device reminder system for taking levothyroxine (which must be taken on an empty
stomach, ~1 hour before eating).

An ESP32-powered pillbox detects when the lid is opened and publishes a message to AWS IoT Core.
A serverless backend records "pill taken today", waits one hour, and sends an "okay to eat" push
notification. A small Android app shows a calendar of the days you took your pill and a history list,
and receives the push.

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

## The three parts

### 1. Arduino firmware — `Arduino/`

ESP32 sketch for the physical pillbox. On opening the lid it publishes an MQTT message to AWS IoT
Core over mutual TLS, on topic `pillbox/opened`, with the shape:

```json
{ "event": "pillbox_opened", "device": "pillbox-esp32", "timestamp": "2026-07-10T08:30:00" }
```

The `timestamp` is local Peru time (GMT-5, no DST, no timezone suffix), from NTP. The firmware also
drives an LED-matrix "eyes" display and a PIR motion sensor (a gentle reminder during active hours).

Files: `pillbox3.ino` (main sketch), `PillBox.h`, `MotionSensor.h`, `Eyes.h`, and `secrets.h`.
Edit `secrets.h` with your WiFi credentials and AWS IoT endpoint + device certificates; the topic
(`pillbox/opened`) and client id (`pillbox-esp32`) are already set there. Flash it with the Arduino
IDE (ESP32 board support). Required libraries: `WiFi` / `WiFiClientSecure` (ESP32 core),
`MQTT` (arduino-mqtt by Joël Gähwiler), and `ArduinoJson`.

### 2. Backend — `backend/` (AWS SAM)

The cloud pipeline: IoT rule -> Ingest Lambda -> DynamoDB + a 1-hour Step Functions wait -> Notify
Lambda -> FCM push. Plus an API-key-protected REST API (`GET /events`, `POST /token`) for the app.
Node.js 24, AWS SDK v3, `firebase-admin` for FCM.

See **[backend/README.md](backend/README.md)** for full setup.

### 3. App — `app/` (Expo / React Native, TypeScript)

A minimal Android app with two views (Calendar + History). It reads data from the REST API and
registers its FCM push token so it receives the "okay to eat" reminder.

See **[app/README.md](app/README.md)** for full setup.

## Prerequisites overview

- **AWS account** with the AWS CLI configured and the AWS SAM CLI installed (region `us-east-1`).
- **Node.js 24** (backend runtime + app tooling).
- **Firebase project** for FCM push (one project supplies both the backend service-account key and
  the app's `google-services.json`).
- **Android toolchain**: JDK 17, Android SDK / Android Studio, and a physical Android device with USB
  debugging (push tokens are not available on emulators).
- **ESP32 hardware** with your AWS IoT device certificates for the physical pillbox (optional — you
  can test the whole cloud path by publishing a test message; see the backend README).

## End-to-end setup order

1. **Firebase**: create a project. Download a **service-account key** (for the backend) and add an
   **Android app** with package `com.pillbox.app` to download **`google-services.json`** (for the
   app).
2. **Backend** ([backend/README.md](backend/README.md)): store the service-account JSON in SSM,
   generate an API key (`openssl rand -hex 24`), `sam build`, `sam deploy --guided`. Note the
   **`ApiBaseUrl`** output and keep the **`ApiKey`** value.
3. **Firmware** (`Arduino/`): fill in `secrets.h` (WiFi + AWS IoT endpoint + certificates) and flash
   the ESP32. Or skip the hardware for now and use the `aws iot-data publish` test in the backend
   README.
4. **App** ([app/README.md](app/README.md)): `npm install`, drop in `google-services.json`, create
   `.env` with the `ApiBaseUrl` and `ApiKey` from step 2, `npx expo prebuild --platform android
   --clean`, build the APK with Gradle, and `adb install` it onto your phone.
5. **Try it**: open the pillbox (or publish a test message). The app's Calendar shows a green check
   for today, and one hour later you get the "okay to eat" push.
