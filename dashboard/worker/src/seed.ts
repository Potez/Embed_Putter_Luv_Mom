// Seed rooms, users and demo bookings.
//   npm run seed                 rooms + users + today's demo bookings
//   npm run seed -- --history    also 7 days of fake history (readings @1 min, bookings, hourly stats)
// Users (emulator only): staff@roomsense.test / roomsense123, gateway@roomsense.test / gateway123
import { getAuth } from "firebase-admin/auth";
import { hourKey, type Booking, type Reading, type RoomMeta } from "@roomsense/shared";
import { app, db } from "./fb.ts";
import { bookingResult, hourStat } from "./aggregate.ts";

const emulator = !!process.env.FIREBASE_DATABASE_EMULATOR_HOST;
const HISTORY = process.argv.includes("--history");

const rooms: Record<string, RoomMeta> = {
  "room-A": { name: "ห้องประชุมกลุ่ม A", capacity: 8, order: 1 },
  "room-B": { name: "ห้องประชุมกลุ่ม B", capacity: 6, order: 2 },
};

async function ensureUser(email: string, password: string, displayName: string) {
  const auth = getAuth(app);
  try { return (await auth.getUserByEmail(email)).uid; }
  catch { return (await auth.createUser({ email, password, displayName })).uid; }
}

for (const [id, meta] of Object.entries(rooms)) await db.ref(`room_list/${id}`).set(meta);
console.log("[seed] rooms");

if (emulator) {
  await ensureUser("staff@roomsense.test", "roomsense123", "เจ้าหน้าที่หอสมุด");
  const gw = await ensureUser("gateway@roomsense.test", "gateway123", "Gateway S3");
  await db.ref(`roles/gateway/${gw}`).set(true);
  console.log("[seed] users: staff@roomsense.test / roomsense123 (gateway role uid " + gw + ")");
} else {
  console.log("[seed] production: create users in the Firebase console, then set roles/gateway/<uid> = true");
}

const now = Date.now();
const min = 60_000;
const demo: Booking[] = [
  { room_id: "room-A", booked_by: "Pasin", title: "Embedded sprint sync", expected: 5, start_ms: now - 2 * min, end_ms: now + 58 * min },
  { room_id: "room-B", booked_by: "Nattapong", title: "ติวสอบ", expected: 3, start_ms: now - 16 * min, end_ms: now + 44 * min },
  { room_id: "room-A", booked_by: "Chayakorn", title: "Group study", expected: 4, start_ms: now + 90 * min, end_ms: now + 150 * min },
];
for (const b of demo) await db.ref("bookings").push({ ...b, created_by: "seed", created_ms: now });
console.log(`[seed] ${demo.length} demo bookings`);

if (HISTORY) {
  const names = ["Pasin", "Chayakorn", "Verawood", "Settapun", "Nattapong", "Ploy", "Mint", "Boss"];
  const day0 = new Date(now); day0.setHours(0, 0, 0, 0);
  for (const roomId of Object.keys(rooms)) {
    for (let d = 7; d >= 0; d--) {
      const dayStart = day0.getTime() - d * 86_400_000;
      // today: fill history up to a few minutes ago, so live data from the sim continues it
      const dayEnd = d === 0 ? Math.min(now - 5 * min, dayStart + 21 * 3_600_000) : dayStart + 21 * 3_600_000;
      const bookings: Booking[] = [];
      for (let h = 9; h < 20; h += 2) {
        if (Math.random() < 0.35) continue;
        const start = dayStart + h * 3_600_000;
        if (start + 90 * min > dayEnd - 10 * min) continue; // don't overlap today's live demo
        bookings.push({ room_id: roomId, booked_by: names[Math.floor(Math.random() * names.length)],
          expected: 2 + Math.floor(Math.random() * 5), start_ms: start, end_ms: start + 90 * min });
      }
      const noShows = new Set(bookings.filter(() => Math.random() < 0.2)); // ~20% no-show
      const readings: Reading[] = [];
      const upd: Record<string, unknown> = {};
      for (let t = dayStart + 8 * 3_600_000; t < dayEnd; t += min) {
        const b = bookings.find((x) => x.start_ms <= t && x.end_ms > t);
        const n = b && !noShows.has(b) ? Math.max(0, Math.round(b.expected * (0.4 + Math.random() * 0.6))) : 0;
        // "before" week half: lights left on after meetings (no automation) — shows energy effect
        const light = n > 0 || (d >= 5 && !!bookings.find((x) => x.end_ms <= t && t - x.end_ms < 45 * min));
        const ts = Math.floor(t / 1000);
        const r: Reading = { room_id: roomId, ts, people_ai: n, people_ir: n, pir: n > 0, light_on: light,
          ldr: light ? 800 : 120, temp_c: 25 + n * 0.3, humidity: 58, sound_db: n ? 55 : 37, flame: false,
          ai_conf: 0.88, buffered: false };
        readings.push(r);
        upd[`rooms/${roomId}/readings/${ts}`] = r;
      }
      for (let h = 8; h < 21 && dayStart + h * 3_600_000 < dayEnd; h++) {
        const hs = dayStart + h * 3_600_000;
        const rs = readings.filter((r) => r.ts * 1000 >= hs && r.ts * 1000 < hs + 3_600_000);
        upd[`stats/${roomId}/hourly/${hourKey(hs)}`] = hourStat(hs, rs);
      }
      for (const b of bookings) {
        const rs = readings.filter((r) => r.ts * 1000 >= b.start_ms && r.ts * 1000 < b.end_ms);
        upd[`bookings/${db.ref("bookings").push().key}`] = { ...b, created_by: "seed", result: bookingResult(b, rs) };
      }
      await db.ref().update(upd);
    }
    console.log(`[seed] history for ${roomId}`);
  }
}
process.exit(0);
