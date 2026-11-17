// secrets.example.h — copy to secrets.h (git-ignored) and fill in. NEVER commit secrets.h.
#pragma once

#define WIFI_SSID          "your-hotspot"
#define WIFI_PASS          "your-wifi-password"

// Firebase console -> Project settings -> General -> Web API Key
#define FIREBASE_API_KEY   "AIza...replace-me"
// Realtime Database host WITHOUT https:// and WITHOUT trailing slash, e.g.
// "roomsense-xxxx-default-rtdb.asia-southeast1.firebasedatabase.app"
#define FIREBASE_DB_HOST   "your-project-default-rtdb.asia-southeast1.firebasedatabase.app"

// Email/Password user whose uid is set in roles/gateway/{uid} = true
#define FIREBASE_EMAIL     "gateway@example.com"
#define FIREBASE_PASSWORD  "replace-me"
