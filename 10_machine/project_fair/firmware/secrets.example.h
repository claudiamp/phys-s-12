#pragma once

// Copy this file to secrets.h and fill it in. secrets.h is gitignored.

// --- The network the plotter joins ---
// Must be 2.4GHz. The ESP32-C3 cannot see a 5GHz network at all, so on an
// iPhone hotspot turn on Settings -> Personal Hotspot -> Maximize Compatibility.
static const char* WIFI_SSID     = "YOUR_SSID";
static const char* WIFI_PASSWORD = "YOUR_PASSWORD";

// --- Name it answers to ---
// http://plotter.local from the laptop, the iPad, or Python on macOS.
#define MDNS_NAME "plotter"

// --- Fallback access point ---
// Used only if the network above is missing at boot. Same as week 10:
// join this SSID and the machine is at 192.168.4.1
#define AP_SSID "esp-captive claudia's team"
