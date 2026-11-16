# RoomSense — Dashboard, Alerts & Cloud

Embedded System (CEDT) Final Project 2026 · Smart meeting-room monitoring for หอสมุดกลาง.
This repo is the **dashboard + backend** part (Cho). Firmware lives elsewhere.

```
shared/   types + pure logic (room status, alert rules, metrics) — unit tested
web/      React dashboard: Overview · Room detail · Bookings · Reports · Alerts · System health
worker/   Node service: alert engine → Telegram/Email, booking results, hourly report stats
          + sim.ts (fake gateway) + seed.ts (demo data)
docs/firebase-schema.md   data contract for the gateway team — read this, Jeen
database.rules.json       RTDB security rules
```

## Run locally (no Firebase account needed)

Needs Node 20+ and Java 11+ (for the emulators).

```bash
cd dashboard
npm install
cp .env.example .env               # defaults already point at the emulators
npm run emulators                  # terminal 1 — Auth + RTDB emulators (UI: http://localhost:4000)
npm run seed -- --history          # once — rooms, users, bookings, 7 days of fake history
npm run worker                     # terminal 2 — alerts / booking results / stats
npm run sim                        # terminal 3 — fake gateway (try: -- --fire  or  -- --outage)
npm run dev                        # terminal 4 — http://localhost:5173
```
Log in with `staff@roomsense.test` / `roomsense123`.
Emulator data is wiped when the emulator stops; just re-run the seed.

## Deploy (real Firebase)

1. Create a Firebase project → enable **Realtime Database** (region asia-southeast1) and **Authentication → Email/Password**.
2. Add a Web app; copy its config into `.env` (`VITE_FIREBASE_*`), set `VITE_USE_EMULATOR=0`.
3. `npx firebase-tools login`, set the project in `.firebaserc`, then
   `npx firebase-tools deploy --only database,hosting` after `npm run build`. Spark (free) plan is enough.
4. Create staff users + the gateway user in the console; set `roles/gateway/<gatewayUid> = true`
   and add `room_list/room-A` / `room-B` (or run `npm run seed` with production credentials).
5. Worker: on any always-on machine (lab PC, Raspberry Pi, free VM) with a service-account JSON:
   set `GOOGLE_APPLICATION_CREDENTIALS`, `FIREBASE_DATABASE_URL`, remove the `*_EMULATOR_HOST` lines,
   fill `TELEGRAM_*` / `SMTP_*`, then `npm run worker`.
   (We use a worker instead of Cloud Functions because Functions require the paid Blaze plan.)

**Telegram:** talk to @BotFather → `/newbot` → token. Add the bot to the staff group, send a message,
open `https://api.telegram.org/bot<token>/getUpdates` to read the `chat.id`.
**Email:** Gmail + an App Password (`SMTP_USER`, `SMTP_PASS`, `ALERT_EMAIL_TO`).

## Alerts (spec §3)

| Event | Level | Condition | Channels |
|---|---|---|---|
| 🔥 Fire | critical | flame = true | web (banner + siren) + Telegram + Email, re-sent every 1 min |
| 🔴 No-show | high | 15 min after booking start, nobody | web + Telegram |
| 🟡 Underused | medium | people < 50% of booked for 15 min | web |
| 💡 Light fail | medium | gateway `light_fail` event, or light on + empty for 10 min | web + Telegram |
| ⚫ Offline | high | no data for 60 s (one alert per outage) | web + Telegram |
| 🌡️ Temp | low | > 30 °C | web |
| 🔊 Noise | low | > 70 dB for 5 min | web |
| 🟢 Recovered / backfilled | info | after reconnect / buffer flush | web |

Same alert is sent at most once per 10 min (except fire). Room alerts stay open (not "resolved")
while that room is offline. Thresholds: `shared/src/logic.ts` → `DEFAULTS`.

## Tests

`npm test` (alert rules, room status, PDR) · `npm run typecheck`
