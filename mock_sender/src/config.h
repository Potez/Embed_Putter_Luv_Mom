// config.h — mock sender settings. Copy the gateway's boot banner values here.
#pragma once

// Gateway STA MAC printed at gateway boot ("Gateway MAC (give to Pat & Flame)")
#define GATEWAY_MAC { 0x24, 0x6F, 0x28, 0x00, 0x00, 0x00 }

// Wi-Fi channel printed at gateway boot. Used only if MOCK_WIFI_SSID is empty.
#define WIFI_CHANNEL 1

// Optional: join the same hotspot as the gateway -> channel matches automatically and node_ts/ts
// come from NTP (needed for the latency metric). Leave "" to run ESP-NOW only (ts = 0).
// Put real values ONLY in src/secrets.h (git-ignored, see secrets.example.h) - never edit them here.
#if __has_include("secrets.h")
#  include "secrets.h"
#endif
#ifndef MOCK_WIFI_SSID
#define MOCK_WIFI_SSID ""
#define MOCK_WIFI_PASS ""
#endif

#define MOCK_NODE_ID 1           // 1 = node-A (must match gateway NODE_NUM_ID)
#define MOCK_CAM_ID  1
#define NODE_PERIOD_MS 500       // 2 Hz
#define CAM_PERIOD_MS  333       // ~3 Hz
#define STATS_PERIOD_MS 10000
#define FLAME_EVERY_MS 120000UL  // flame_do = 0 every ~2 min ...
#define FLAME_HOLD_MS  10000UL   // ... for 10 s
