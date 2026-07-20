#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <MQTTClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include "MotionSensor.h"
#include "PillBox.h"
#include "Eyes.h"
#include "Secrets.h"
#include "Speaker.h"
#include "AudioData.h"

#define PIR_PIN        D0    // D0  - motion sensor (input)
#define PILLBOX_PIN    D1    // D1  - reed/button (input)
#define EYES_CLK_PIN   D8    // D8  - MAX7219 CLK
#define EYES_CS_PIN    D9    // D9  - MAX7219 CS
#define EYES_DATA_PIN  D10   // D10 - MAX7219 DIN
#define I2S_BCLK_PIN   D2    // D2 (GPIO3) - MAX98357A BCLK
#define I2S_LRC_PIN    D3    // D3 (GPIO4) - MAX98357A LRC
#define I2S_DOUT_PIN   D4    // D4 (GPIO5) - MAX98357A DIN

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

WiFiClientSecure net;
MQTTClient mqtt(256);

int triggerCount = 0;
int lastResetDay = -1;
int wifiFailCount = 0;
bool mqttSent = false;
bool pirReadyPrinted = false;

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

void setup() {
  Serial.begin(115200);
  pir.begin();
  pillBox.begin();
  eyes.begin();
  speaker.begin();
  speaker.setVolume(0.3); // between 0 and 1

  eyes.setSleepTimeout(SLEEP_TIMEOUT_MS);
  eyes.setExpression(Eyes::THINKING);

  WiFi.mode(WIFI_STA);
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
  wifiFailCount = 0;

  if (!mqtt.connected()) {
    connectMQTT();
  }
  mqtt.loop();

  if (!pirReadyPrinted && pir.ready()) {
    pirReadyPrinted = true;
    Serial.println("PIR ready — detecting movement");
  }

  resetDailyCounter();

  pillBox.update();

  bool motion = pir.detected();
  bool open = pillBox.justOpened();

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
