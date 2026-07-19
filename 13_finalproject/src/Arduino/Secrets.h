#pragma once

// --- WiFi ---
const char* WIFI_SSID = "YOUR_SSID";
const char* WIFI_PASS = "YOUR_PASSWORD";

// --- AWS IoT ---
const char* AWS_IOT_ENDPOINT = "xxxxxx-ats.iot.us-east-1.amazonaws.com";
const char* AWS_IOT_TOPIC = "pillbox/opened";
const char* AWS_IOT_CLIENT_ID = "pillbox-esp32";

// --- Certificates ---
const char AWS_CERT_CA[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
PASTE YOUR AMAZON ROOT CA 1 HERE
-----END CERTIFICATE-----
)EOF";

const char AWS_CERT_CRT[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
PASTE YOUR DEVICE CERTIFICATE HERE
-----END CERTIFICATE-----
)EOF";

const char AWS_CERT_PRIVATE[] PROGMEM = R"EOF(
-----BEGIN RSA PRIVATE KEY-----
PASTE YOUR PRIVATE KEY HERE
-----END RSA PRIVATE KEY-----
)EOF";
