#include "firebase_client.h"
#include "config.h"
#include "certs.h"
#include "ring_buffer.h"
#include "health.h"
#include "actuator.h"
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <esp_task_wdt.h>
#include <time.h>
#include <math.h>

static const char* EVT_NAMES[] = {"enter", "exit", "light_on", "light_off", "light_fail",
                                  "manual", "reboot", "reconnect", "backfill"};

// Result of one RTDB request. The cloud task must never stall on a request that can never succeed.
enum DbResult : uint8_t {
  DB_OK,        // 2xx
  DB_NET,       // transport error (no route, TLS, timeout) -> link is down: buffer + backoff
  DB_RETRY,     // 5xx / 429 / auth refresh pending -> try again later, keep the item
  DB_REJECT,    // permanent 4xx (400, 403, 401 "Permission denied", ...) -> log and DROP the item
};

static QueueHandle_t s_evq = nullptr;
static WiFiClientSecure* s_dbTls = nullptr;     // kept alive between requests (HTTP keep-alive)
static HTTPClient s_http;
static String s_token;
static uint32_t s_tokenMs = 0;
static bool s_haveToken = false;
static bool s_tokenExpired = false;             // server said "Auth token is expired"
static uint32_t s_lastLoginMs = 0;
static bool s_loginTried = false;
static uint32_t s_backoffMs = 0, s_nextTryMs = 0;
static volatile bool s_wifiWasDown = false;
static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;   // guards s_outageFrom
static uint32_t s_outageFrom = 0;               // Unix s when the link went down (0 = no outage)
static bool s_haveLastCmd = false;              // executed at least one control command
static uint64_t s_lastCmdTsMs = 0;              // ts_ms of the last executed command
// backfill bookkeeping (one backfill event per outage, after the buffer is empty)
static uint16_t s_bfCount = 0;
static uint32_t s_bfFrom = 0, s_bfTo = 0;

uint32_t cloud_now() {
  time_t t = time(nullptr);
  return t > (time_t)NTP_VALID_AFTER ? (uint32_t)t : 0;
}
bool cloud_time_synced() { return cloud_now() != 0; }

bool events_post(EventType type, const char* detail, const char* by, int32_t latency_ms) {
  if (!s_evq) return false;
  Event e{};
  e.ts = cloud_now();
  e.type = type;
  if (detail) strlcpy(e.detail, detail, sizeof e.detail);
  if (by) strlcpy(e.by, by, sizeof e.by);
  e.latency_ms = latency_ms;
  bool ok = xQueueSend(s_evq, &e, 0) == pdTRUE;
  if (!ok) Serial.printf("[cloud] event queue full, dropped %s\n", EVT_NAMES[type]);
  return ok;
}

// ---------------------------------------------------------------- outage (shared with Wi-Fi event task)
static void markOutage() {
  const uint32_t now = cloud_now();             // time() outside the critical section
  portENTER_CRITICAL(&s_mux);
  if (!s_outageFrom) s_outageFrom = now ? now : 1;
  portEXIT_CRITICAL(&s_mux);
}
static uint32_t takeOutage() {                  // read + clear atomically
  portENTER_CRITICAL(&s_mux);
  const uint32_t v = s_outageFrom;
  s_outageFrom = 0;
  portEXIT_CRITICAL(&s_mux);
  return v;
}
static bool inOutage() {
  portENTER_CRITICAL(&s_mux);
  const bool v = s_outageFrom != 0;
  portEXIT_CRITICAL(&s_mux);
  return v;
}

// Link is down: everything still waiting was "not delivered because the network was down".
static void networkDown() {
  markOutage();
  ring_mark_all_buffered();
}

// ---------------------------------------------------------------- Wi-Fi events (reconnect counting)
static void onWifiEvent(WiFiEvent_t ev, WiFiEventInfo_t) {
  if (ev == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
    if (!s_wifiWasDown) Serial.println("[wifi] DISCONNECTED - buffering readings");
    s_wifiWasDown = true;
    markOutage();
  } else if (ev == ARDUINO_EVENT_WIFI_STA_GOT_IP) {
    if (s_wifiWasDown) {
      s_wifiWasDown = false;
      health_count_reconnect();
      char d[40];
      snprintf(d, sizeof d, "channel %d, rssi %d", (int)WiFi.channel(), (int)WiFi.RSSI());
      events_post(EVT_RECONNECT, d);
      Serial.printf("[wifi] RECONNECTED ip=%s %s (ESP-NOW senders must use this channel)\n",
                    WiFi.localIP().toString().c_str(), d);
    }
  }
}

void cloud_init() {
  s_evq = xQueueCreate(EVENT_QUEUE_LEN, sizeof(Event));
  WiFi.onEvent(onWifiEvent);
}

// ---------------------------------------------------------------- backoff
static void backoff(DbResult why) {
  s_backoffMs = s_backoffMs ? min<uint32_t>(s_backoffMs * 2, BACKOFF_MAX_MS) : BACKOFF_MIN_MS;
  s_nextTryMs = millis() + s_backoffMs;
  if (why == DB_NET) {
    networkDown();
    s_http.end();                               // drop the TLS session; it is probably dead
    if (s_dbTls) s_dbTls->stop();
  }
  Serial.printf("[cloud] %s -> backoff %lu ms\n", why == DB_NET ? "network error" : "server busy/auth",
                (unsigned long)s_backoffMs);
  esp_task_wdt_reset();
}
static void succeed() { s_backoffMs = 0; }
static bool backingOff() { return s_backoffMs && (int32_t)(millis() - s_nextTryMs) < 0; }

// ---------------------------------------------------------------- auth
// Rate-limited: at most one sign-in attempt per LOGIN_MIN_GAP_MS (30 s).
static bool login() {
  if (s_loginTried && millis() - s_lastLoginMs < LOGIN_MIN_GAP_MS) return false;
  s_loginTried = true;
  s_lastLoginMs = millis();
  esp_task_wdt_reset();
  WiFiClientSecure tls;
  tls.setCACert(GOOGLE_ROOT_CA_BUNDLE);         // E5: verify, never setInsecure()
  tls.setHandshakeTimeout(TLS_HANDSHAKE_TIMEOUT_S);
  HTTPClient http;
  String url = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=";
  url += FIREBASE_API_KEY;
  if (!http.begin(tls, url)) return false;
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.setConnectTimeout(HTTP_TIMEOUT_MS);
  http.addHeader("Content-Type", "application/json");
  JsonDocument body;
  body["email"] = FIREBASE_EMAIL;
  body["password"] = FIREBASE_PASSWORD;
  body["returnSecureToken"] = true;
  String b; serializeJson(body, b);
  esp_task_wdt_reset();
  int code = http.POST(b);
  esp_task_wdt_reset();
  bool ok = false;
  if (code == 200) {
    JsonDocument filter; filter["idToken"] = true;
    JsonDocument resp;
    DeserializationError err = deserializeJson(resp, http.getStream(), DeserializationOption::Filter(filter));
    if (!err && resp["idToken"].is<const char*>()) {
      s_token = resp["idToken"].as<const char*>();
      s_tokenMs = millis();
      s_haveToken = true;
      s_tokenExpired = false;
      ok = true;
      Serial.println("[cloud] signed in (idToken ok)");
    }
  } else {
    Serial.printf("[cloud] sign-in failed: HTTP %d %s (next attempt in >= %lu s)\n", code,
                  code > 0 ? http.getString().c_str() : http.errorToString(code).c_str(),
                  (unsigned long)(LOGIN_MIN_GAP_MS / 1000));
  }
  http.end();
  esp_task_wdt_reset();
  return ok;
}

static bool tokenTooOld() { return millis() - s_tokenMs > TOKEN_REFRESH_MS; }

// ---------------------------------------------------------------- RTDB request
// path like "/rooms/room-A/live.json".
static DbResult db(const char* method, const String& path, const String& body, String* resp = nullptr,
                   bool retried = false) {
  if (!s_dbTls) {
    s_dbTls = new WiFiClientSecure();
    s_dbTls->setCACert(GOOGLE_ROOT_CA_BUNDLE);   // E5: verify server certificate
    s_dbTls->setHandshakeTimeout(TLS_HANDSHAKE_TIMEOUT_S);
  }
  String url = "https://" FIREBASE_DB_HOST;
  url += path;
  url += "?auth=";
  url += s_token;
  if (!resp) url += "&print=silent";            // 204, no body to download
  esp_task_wdt_reset();
  s_http.setReuse(true);
  if (!s_http.begin(*s_dbTls, url)) { esp_task_wdt_reset(); return DB_NET; }
  s_http.setTimeout(HTTP_TIMEOUT_MS);
  s_http.setConnectTimeout(HTTP_TIMEOUT_MS);
  if (body.length()) s_http.addHeader("Content-Type", "application/json");
  const int code = s_http.sendRequest(method, body);
  esp_task_wdt_reset();
  String err;
  if (resp && code == 200) *resp = s_http.getString();
  else if (code >= 400) err = s_http.getString();
  s_http.end();
  esp_task_wdt_reset();

  if (code >= 200 && code < 300) return DB_OK;
  if (code < 0) {
    Serial.printf("[cloud] %s %s -> %s\n", method, path.c_str(), HTTPClient::errorToString(code).c_str());
    return DB_NET;
  }
  Serial.printf("[cloud] %s %s -> %d %s\n", method, path.c_str(), code, err.c_str());
  if (code == 401) {
    // Re-login ONLY for an expired token. "Permission denied" (rules) is permanent: no login spam.
    const bool expired = err.indexOf("expired") >= 0 || tokenTooOld();
    if (!expired) return DB_REJECT;
    s_tokenExpired = true;
    if (!retried && login()) return db(method, path, body, resp, true);
    return DB_RETRY;                             // login rate-limited / failed: keep the item
  }
  if (code == 429 || code >= 500) return DB_RETRY;
  return DB_REJECT;                              // 400, 403, 404, 413 ... retrying cannot help
}

// ---------------------------------------------------------------- JSON builders
static void readingFill(JsonObject d, const Reading& r) {
  d["room_id"] = ROOM_ID;
  d["ts"] = r.ts;
  if (r.node_valid && r.node_ts > NTP_VALID_AFTER) d["node_ts"] = r.node_ts; else d["node_ts"] = nullptr;
  d["server_ts"][".sv"] = "timestamp";
  if (r.people_ai >= 0) {
    d["people_ai"] = r.people_ai;
    d["ai_conf"] = serialized(String(r.ai_conf / 100.0f, 2));   // 0..1
  } else {
    d["people_ai"] = nullptr;
    d["ai_conf"] = nullptr;
  }
  if (r.node_valid && r.people_ir >= 0) d["people_ir"] = r.people_ir; else d["people_ir"] = nullptr;
  if (r.node_valid) d["pir"] = r.pir; else d["pir"] = nullptr;
  d["light_on"] = r.light_on;                    // REAL state from the LDR
  d["ldr"] = r.ldr;
  if (!isnan(r.temp_c)) d["temp_c"] = serialized(String(r.temp_c, 1)); else d["temp_c"] = nullptr;
  if (!isnan(r.humidity)) d["humidity"] = (int)lroundf(r.humidity); else d["humidity"] = nullptr;
  if (r.node_valid) d["sound_db"] = r.sound_db; else d["sound_db"] = nullptr;
  d["flame"] = r.node_valid ? r.flame : false;   // always a boolean (null would delete the key)
  d["status"] = r.power_on ? "in_use" : "vacant";   // optional in schema; from RoomSensePredictor.ino
  if (r.node_valid) d["node_seq"] = r.node_seq; else d["node_seq"] = nullptr;
  d["buffered"] = r.buffered;
}

static void eventJson(const Event& e, String& out) {
  JsonDocument d;
  d["ts"] = e.ts ? e.ts : cloud_now();
  d["type"] = EVT_NAMES[e.type];
  if (e.type == EVT_BACKFILL) {
    d["count"] = e.count; d["from"] = e.from; d["to"] = e.to;
  } else {
    if (e.detail[0]) d["detail"] = e.detail;
    if (e.by[0]) d["by"] = e.by;
    if (e.latency_ms >= 0) d["latency_ms"] = e.latency_ms;
  }
  serializeJson(d, out);
}

// ---------------------------------------------------------------- jobs
// After an outage, once the buffer is empty: ONE backfill event + last_outage.
static void finishOutageIfDone() {
  if (ring_depth() != 0 || !inOutage()) return;
  const uint32_t now = cloud_now();
  const uint32_t from = takeOutage();
  if (s_bfCount) {
    Event e{}; e.ts = now; e.type = EVT_BACKFILL; e.count = s_bfCount; e.from = s_bfFrom; e.to = s_bfTo;
    xQueueSend(s_evq, &e, 0);
  }
  JsonDocument d;
  d["from"] = from > 1 ? from : (s_bfFrom ? s_bfFrom : now);
  d["to"] = now;
  d["backfilled"] = s_bfCount;
  String b; serializeJson(d, b);
  db("PUT", "/devices/" GATEWAY_ID "/health/last_outage.json", b);
  db("PUT", "/devices/" NODE_ID "/health/last_outage.json", b);
  Serial.printf("[cloud] outage over: backfilled %u readings\n", s_bfCount);
  s_bfCount = 0; s_bfFrom = s_bfTo = 0;
}

// Newest reading -> live + readings/{ts} in ONE multi-path PATCH at the root (same object, atomic).
// Older ones (backlog) -> readings/{ts} only. ts key = idempotent replays.
// While a backlog drains, the first PATCH of each call also sets live = newest reading, so the
// dashboard/worker (offline if live.ts > 60 s old) see the room as online right after reconnect.
static DbResult uploadReadings() {
  bool liveSent = false;
  for (int i = 0; i < 10; i++) {                 // budget per loop so control stays responsive
    Reading r;
    if (!ring_peek_oldest(&r)) break;
    const bool newest = ring_depth() == 1;
    const String key = "rooms/" ROOM_ID "/readings/" + String(r.ts);
    JsonDocument doc;
    readingFill(doc[key].to<JsonObject>(), r);
    if (newest) doc["rooms/" ROOM_ID "/live"] = doc[key];
    else if (!liveSent) {
      Reading n;
      if (ring_peek_newest(&n)) readingFill(doc["rooms/" ROOM_ID "/live"].to<JsonObject>(), n);
    }
    String body; serializeJson(doc, body);
    esp_task_wdt_reset();
    const DbResult res = db("PATCH", "/.json", body);
    if (res == DB_NET || res == DB_RETRY) return res;   // keep it, retry after backoff
    ring_pop_oldest();
    if (res == DB_OK) liveSent = true;
    if (res == DB_REJECT) {                       // permanent: drop, never block the queue
      Serial.printf("[cloud] reading %lu REJECTED by server - dropped\n", (unsigned long)r.ts);
      continue;
    }
    succeed();
    if (r.buffered) {
      if (!s_bfCount || r.ts < s_bfFrom) s_bfFrom = r.ts;
      if (r.ts > s_bfTo) s_bfTo = r.ts;
      s_bfCount++;
    }
    Serial.printf("[cloud] reading %lu uploaded%s (depth %u)\n", (unsigned long)r.ts,
                  r.buffered ? " [buffered]" : "", (unsigned)ring_depth());
  }
  finishOutageIfDone();
  return DB_OK;
}

static DbResult uploadEvents() {
  Event e;
  while (xQueuePeek(s_evq, &e, 0) == pdTRUE) {
    String b; eventJson(e, b);
    const DbResult res = db("POST", "/rooms/" ROOM_ID "/events.json", b);
    if (res == DB_NET || res == DB_RETRY) return res;
    xQueueReceive(s_evq, &e, 0);                  // remove after success or permanent reject
    if (res == DB_REJECT) Serial.printf("[cloud] event REJECTED - dropped: %s\n", b.c_str());
    else { succeed(); Serial.printf("[cloud] event %s\n", b.c_str()); }
  }
  return DB_OK;
}

// Runs on its own 30 s timer, independent of readings/control/events results.
static void uploadHealth() {
  const uint32_t now = cloud_now();
  String b;
  { JsonDocument d; health_build_gateway(d, now); serializeJson(d, b); }
  // PATCH (not PUT) so devices/*/health/last_outage survives
  DbResult r1 = db("PATCH", "/devices/" GATEWAY_ID "/health.json", b);
  b = "";
  { JsonDocument d; health_build_node(d, now); serializeJson(d, b); }
  DbResult r2 = db("PATCH", "/devices/" NODE_ID "/health.json", b);
  health_print_serial();
  if (r1 == DB_NET || r2 == DB_NET) networkDown();
  if (r1 != DB_OK || r2 != DB_OK) Serial.printf("[cloud] health upload: gw=%d node=%d\n", r1, r2);
}

static DbResult pollControl() {
  String resp;
  DbResult res = db("GET", "/control/" ROOM_ID ".json", "", &resp);
  if (res != DB_OK) return res;
  JsonDocument d;
  if (deserializeJson(d, resp) || d.isNull() || !d["cmd"].is<const char*>()) return DB_OK;
  if (!d["done_ms"].isNull()) return DB_OK;      // already executed

  const bool hasTs = !d["ts_ms"].isNull();
  const uint64_t tsMs = d["ts_ms"] | (uint64_t)0;
  const char* cmd = d["cmd"];
  const char* by = d["by"] | "dashboard";
  const bool isNew = !s_haveLastCmd || tsMs != s_lastCmdTsMs;
  if (isNew) {
    const uint64_t nowMs = (uint64_t)cloud_now() * 1000ULL;
    const bool tooOld = hasTs && nowMs > tsMs && nowMs - tsMs > CONTROL_MAX_AGE_MS;
    if (tooOld) {
      Serial.printf("[cloud] control '%s' by %s is %llu s old (> %lu s) - NOT executed, marking done\n",
                    cmd, by, (unsigned long long)((nowMs - tsMs) / 1000), (unsigned long)(CONTROL_MAX_AGE_MS / 1000));
    } else {
      bool queued = true;
      if (!strcmp(cmd, "light_on"))        queued = actuator_request_manual(ACT_SET_LIGHT, true, by);
      else if (!strcmp(cmd, "light_off"))  queued = actuator_request_manual(ACT_SET_LIGHT, false, by);
      else if (!strcmp(cmd, "servo_stop")) queued = actuator_request_manual(ACT_SERVO_STOP, false, by);
      else Serial.printf("[cloud] unknown control cmd '%s' (marked done)\n", cmd);
      if (!queued) {                              // actuator busy: no done_ms, retry next poll
        Serial.printf("[cloud] actuator queue full - '%s' retried on next poll\n", cmd);
        return DB_OK;
      }
      // Same as worker/src/sim.ts: the dashboard already pushes its own "manual" event when the
      // button is clicked; light_on/light_off/light_fail (with `by`) come from the actuator once the
      // LDR confirms. Only servo_stop gets a gateway "manual" event.
      if (!strcmp(cmd, "servo_stop")) {
        char det[32];
        snprintf(det, sizeof det, "manual: %s", cmd);
        events_post(EVT_MANUAL, det, by);
      }
      Serial.printf("[cloud] control: %s by %s -> manual override %d min\n", cmd, by, MANUAL_OVERRIDE_MIN);
    }
    s_haveLastCmd = true;
    s_lastCmdTsMs = tsMs;
  }
  // acknowledge: done_ms = server timestamp. If this PUT fails, the next poll retries it
  // without executing the command again (same ts_ms).
  db("PUT", "/control/" ROOM_ID "/done_ms.json", "{\".sv\":\"timestamp\"}");
  return DB_OK;
}

// ---------------------------------------------------------------- task
void cloudTask(void*) {
  esp_task_wdt_add(nullptr);
  uint32_t lastHealth = 0, lastControl = 0, lastWifiKick = 0;
  bool healthEver = false, rebootPosted = false;
  for (;;) {
    esp_task_wdt_reset();
    vTaskDelay(pdMS_TO_TICKS(100));

    if (WiFi.status() != WL_CONNECTED) {
      networkDown();
      if (millis() - lastWifiKick > 20000) {      // auto-reconnect is on; kick it if it stalls
        lastWifiKick = millis();
        WiFi.reconnect();
      }
      continue;
    }
    if (!cloud_time_synced()) continue;           // never upload before NTP sync
    if (!rebootPosted) {
      events_post(EVT_REBOOT, health_reset_reason());
      rebootPosted = true;
    }

    // token: first sign-in, proactive refresh at 55 min, or after "Auth token is expired"
    if (!s_haveToken || s_tokenExpired || tokenTooOld()) {
      esp_task_wdt_reset();
      if (!login() && !s_haveToken) continue;     // rate-limited inside login()
    }

    // health: own 30 s timer, never blocked by the jobs below
    if (!healthEver || millis() - lastHealth >= HEALTH_MS) {
      lastHealth = millis();
      healthEver = true;
      uploadHealth();
      esp_task_wdt_reset();
    }

    if (backingOff()) continue;

    DbResult r = uploadReadings();
    if (r == DB_NET || r == DB_RETRY) { backoff(r); continue; }
    if (millis() - lastControl >= CONTROL_POLL_MS) {
      lastControl = millis();
      r = pollControl();
      if (r == DB_NET || r == DB_RETRY) { backoff(r); continue; }
      if (r == DB_REJECT) Serial.println("[cloud] control read rejected (rules?) - skipping");
    }
    r = uploadEvents();
    if (r == DB_NET || r == DB_RETRY) { backoff(r); continue; }
  }
}
