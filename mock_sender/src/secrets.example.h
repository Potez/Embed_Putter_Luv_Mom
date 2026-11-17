// secrets.example.h — optional. Copy to secrets.h (git-ignored) to let the mock sender join the
// gateway's hotspot (channel + NTP). NEVER commit secrets.h and never put the password in config.h.
#pragma once

#define MOCK_WIFI_SSID "your-hotspot"
#define MOCK_WIFI_PASS "your-wifi-password"
