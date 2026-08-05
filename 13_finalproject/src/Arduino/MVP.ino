#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <MQTTClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include <esp_random.h>
#include "MotionSensor.h"
#include "PillBox.h"
#include "Eyes.h"
#include "Secrets.h"
#include "Speaker.h"
#include "AudioData.h"
#include "TouchPad.h"

#define PIR_PIN        D0    // D0  - motion sensor (input)
#define PILLBOX_PIN    D1    // D1  - reed/button (input)
#define EYES_CLK_PIN   D8    // D8  - MAX7219 CLK
#define EYES_CS_PIN    D9    // D9  - MAX7219 CS
#define EYES_DATA_PIN  D10   // D10 - MAX7219 DIN
#define I2S_BCLK_PIN   D2    // D2 (GPIO3) - MAX98357A BCLK
#define I2S_LRC_PIN    D3    // D3 (GPIO4) - MAX98357A LRC
#define I2S_DOUT_PIN   D4    // D4 (GPIO5) - MAX98357A DIN
#define TOUCH_PIN      D5    // D5 (GPIO6 / TOUCH6) - capacitive touch pad (foil)
#define TOUCH_DEBUG    0     // 1 = stream raw touch readings to Serial

#define MAX_TRIGGERS_PER_DAY 3
#define SLEEP_TIMEOUT_MS 10000
#define ACTIVE_HOUR_START 6
#define ACTIVE_HOUR_END 24

const char* NTP_SERVER = "pool.ntp.org";
const long GMT_OFFSET = -5 * 3600;  // LIMA timezone
const int DST_OFFSET = 0;

// LOW while a pushbutton stands in for the reed switch (pressed = box opened).
#define PILLBOX_OPEN_LEVEL HIGH

MotionSensor pir(PIR_PIN);
PillBox pillBox(PILLBOX_PIN, PILLBOX_OPEN_LEVEL, 150);
Eyes eyes(EYES_DATA_PIN, EYES_CLK_PIN, EYES_CS_PIN);
Speaker speaker(I2S_BCLK_PIN, I2S_LRC_PIN, I2S_DOUT_PIN, AUDIO_SAMPLE_RATE);
TouchPad touchPad(TOUCH_PIN);

// Greetings for the touch pad — one is picked at random on each touch, and
// each one carries the face that matches its tone. "yes?" is a question, not
// a greeting, so it gets the normal blinking eyes instead of the happy ones.
struct Clip { const int16_t* data; uint32_t len; int expr; };
const Clip TOUCH_CLIPS[] = {
  { good_to_see_you_voice_data, good_to_see_you_voice_len, Eyes::HAPPY },
  { hello_data,                 hello_len,                 Eyes::HAPPY },
  { yes_question_data,          yes_question_len,          Eyes::OPEN  },
  { hi_there_data,              hi_there_len,              Eyes::HAPPY },
};
const uint8_t TOUCH_CLIP_COUNT = sizeof(TOUCH_CLIPS) / sizeof(TOUCH_CLIPS[0]);
uint8_t lastTouchClip = TOUCH_CLIP_COUNT;   // sentinel: nothing played yet

WiFiClientSecure net;
MQTTClient mqtt(256);

int triggerCount = 0;
int lastResetDay = -1;
int wifiFailCount = 0;
bool mqttSent = false;
bool pirReadyPrinted = false;

// WiFi diagnostics: the event handler records why we dropped, and loop()
// publishes {reason, rssi, ...} to pillbox/diag after each reconnect — so we
// can see what's happening without a Serial cable attached.
const char* AWS_IOT_DIAG_TOPIC = "pillbox/diag";
volatile int lastDisconnectReason = 0;
bool diagPending = false;

void onWiFiEvent(WiFiEvent_t event, WiFiEventInfo_t info) {
  if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
    lastDisconnectReason = info.wifi_sta_disconnected.reason;
  }
}

int getHour() {
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) return -1;
  return timeinfo.tm_hour;
}

int getDay() {
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) return -1;
  return timeinfo.tm_yday;
}

bool isActiveHours() {
  int hour = getHour();
  if (hour < 0) return false;
  return hour >= ACTIVE_HOUR_START && hour < ACTIVE_HOUR_END;
}

void resetDailyCounter() {
  int today = getDay();
  if (today >= 0 && today != lastResetDay) {
    triggerCount = 0;
    lastResetDay = today;
    Serial.println("Daily trigger count reset");
  }
}

void connectMQTT() {
  Serial.print("Connecting to AWS IoT");
  while (!mqtt.connect(AWS_IOT_CLIENT_ID)) {
    if (WiFi.status() != WL_CONNECTED) {   // WiFi dropped mid-attempt: bail, let loop() recover
      Serial.println(" WiFi lost");
      return;
    }
    Serial.print(".");
    delay(500);
  }
  Serial.println(" connected");
}

void sendPillboxOpened() {
  JsonDocument doc;
  doc["event"] = "pillbox_opened";
  doc["device"] = AWS_IOT_CLIENT_ID;

  struct tm timeinfo;
  if (getLocalTime(&timeinfo)) {
    char timestamp[25];
    strftime(timestamp, sizeof(timestamp), "%Y-%m-%dT%H:%M:%S", &timeinfo);
    doc["timestamp"] = timestamp;
  }

  char payload[256];
  serializeJson(doc, payload);
  mqtt.publish(AWS_IOT_TOPIC, payload);
  Serial.print("MQTT sent: ");
  Serial.println(payload);
}

void sendDiag() {
  JsonDocument doc;
  doc["event"] = "reconnected";
  doc["device"] = AWS_IOT_CLIENT_ID;
  doc["reason"] = lastDisconnectReason;   // esp_wifi disconnect reason code
  doc["rssi"] = WiFi.RSSI();              // signal strength after reconnect (dBm)

  struct tm timeinfo;
  if (getLocalTime(&timeinfo)) {
    char timestamp[25];
    strftime(timestamp, sizeof(timestamp), "%Y-%m-%dT%H:%M:%S", &timeinfo);
    doc["timestamp"] = timestamp;
  }

  char payload[256];
  serializeJson(doc, payload);
  mqtt.publish(AWS_IOT_DIAG_TOPIC, payload);
  Serial.print("Diag sent: ");
  Serial.println(payload);
}

void playRandomTouchClip() {
  uint8_t i;
  do {
    i = esp_random() % TOUCH_CLIP_COUNT;
  } while (i == lastTouchClip);
  lastTouchClip = i;

  Serial.print("touch clip #");
  Serial.println(i);
  eyes.setExpression(TOUCH_CLIPS[i].expr);   // set before play() — play() blocks
  speaker.play(TOUCH_CLIPS[i].data, TOUCH_CLIPS[i].len);
}

void setup() {
  Serial.begin(115200);
  pir.begin();
  pillBox.begin();
  eyes.begin();
  speaker.begin();
  speaker.setVolume(0.3); // between 0 and 1
  touchPad.begin();       // learns the untouched baseline — hands off the foil here
  Serial.print("TouchPad baseline=");
  Serial.print(touchPad.baseline());
  Serial.print(" threshold=");
  Serial.println(touchPad.threshold());
  if (touchPad.baseline() == 0) {
    Serial.println("TouchPad: baseline 0 — pin is not touch-capable or not wired");
  }

  eyes.setSleepTimeout(SLEEP_TIMEOUT_MS);
  eyes.setExpression(Eyes::THINKING);

  WiFi.mode(WIFI_STA);
  WiFi.onEvent(onWiFiEvent);   // capture disconnect reason codes
  Serial.print("ESP32 MAC Address: ");
  Serial.println(WiFi.macAddress());
  Serial.print("Connecting to \"");
  Serial.print(WIFI_SSID);
  Serial.print("\"");

  WiFi.begin(WIFI_SSID);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    eyes.update();
    delay(500);
    Serial.print(".");
    attempts++;
  }
  Serial.print(" [status=");
  Serial.print(WiFi.status());   // 3=connected, 6=no SSID found, 4=connect fail
  Serial.println("]");

  // TLS + MQTT configuration: no network I/O, so it's safe even if WiFi is
  // down, and it only needs to run once. loop() drives the actual connecting.
  net.setCACert(AWS_CERT_CA);
  net.setCertificate(AWS_CERT_CRT);
  net.setPrivateKey(AWS_CERT_PRIVATE);
  mqtt.begin(AWS_IOT_ENDPOINT, 8883, net);

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println(" failed");
    eyes.setExpression(Eyes::ERROR);
  } else {
    Serial.println(" connected");
    eyes.setExpression(Eyes::OPEN);
    WiFi.setSleep(false);   // keep the radio awake — avoids intermittent drops
    configTime(GMT_OFFSET, DST_OFFSET, NTP_SERVER);
    Serial.println("NTP time synced");

    connectMQTT();
    speaker.play(hi_there_data, hi_there_len);
  }

}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    wifiFailCount++;
    if (wifiFailCount > 60) {
      ESP.restart();
    }
    eyes.setExpression(Eyes::ERROR);
    eyes.update();
    WiFi.reconnect();
    delay(5000);
    return;
  }

  // Just recovered from a WiFi drop: clear the ERROR face (it never sleeps on
  // its own) so the normal open/sleep cycle resumes, and queue a diag report.
  if (wifiFailCount > 0) {
    eyes.setExpression(Eyes::OPEN);
    diagPending = true;
  }
  wifiFailCount = 0;

  if (!mqtt.connected()) {
    connectMQTT();
  }
  mqtt.loop();

  // Report the reconnect (reason + RSSI) once MQTT is back up.
  if (diagPending && mqtt.connected()) {
    sendDiag();
    diagPending = false;
  }

  if (!pirReadyPrinted && pir.ready()) {
    pirReadyPrinted = true;
    Serial.println("PIR ready — detecting movement");
  }

  resetDailyCounter();

  pillBox.update();

  bool motion = pir.detected();
  bool open = pillBox.justOpened();
  bool touch = touchPad.touched();   // rising edge, consumed here

#if TOUCH_DEBUG
  // Stream readings while touching the foil for debugging.
  static unsigned long lastTouchPrint = 0;
  if (millis() - lastTouchPrint > 250) {
    lastTouchPrint = millis();
    Serial.print("touch raw=");
    Serial.print(touchPad.raw());
    Serial.print(" base=");
    Serial.print(touchPad.baseline());
    Serial.print(" fires_above=");
    Serial.println(touchPad.threshold());
  }
#endif

  // --- Touch pad: petting the robot wakes it up and it greets you ---
  // The face comes from the clip that gets picked, so don't set one here.
  if (touch) {
    Serial.println("touch detected");
    playRandomTouchClip();
  }

  // --- PillBox opened: happy face + MQTT ---
  if (open) {
    eyes.setExpression(Eyes::HAPPY);
    Serial.println("pillbox opened");
    if (!mqttSent) {
      sendPillboxOpened();
      Serial.println("MQTT: pillbox opened");
      speaker.play(good_job_data, good_job_len);
      mqttSent = true;
    }
  } else {
    mqttSent = false;

    // --- Motion detected (max 3x/day, only during active hours) ---
    if (motion && triggerCount < MAX_TRIGGERS_PER_DAY && isActiveHours()) {
      triggerCount++;
      eyes.setExpression(Eyes::OPEN);
      if (triggerCount == 1) {
        speaker.play(first_message_data, first_message_len);
      } else {
        speaker.play(follow_up_message_data, follow_up_message_len);
      }
      Serial.print("Motion trigger #");
      Serial.println(triggerCount);
    }
  }

  eyes.update();
}
