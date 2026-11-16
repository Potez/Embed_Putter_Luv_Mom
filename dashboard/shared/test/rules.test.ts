import { describe, it, expect } from "vitest";
import { conditions, activeConditions, type Snapshot } from "../src/rules.ts";
import { roomStatus, packetDelivery, peopleOf, soundLevel, DEFAULTS } from "../src/logic.ts";
import type { Booking, Reading } from "../src/types.ts";

const NOW = Date.parse("2026-11-20T10:00:00Z");
const sec = (minAgo: number) => Math.floor((NOW - minAgo * 60_000) / 1000);
const ms = (minAgo: number) => NOW - minAgo * 60_000;

const live = (p: Partial<Reading> = {}): Reading => ({
  room_id: "room-A", ts: sec(0.1), people_ai: 0, pir: false, light_on: false,
  temp_c: 25, sound_db: 40, flame: false, ...p,
});
const booking = (p: Partial<Booking> = {}): Booking & { id: string } => ({
  id: "bk1", room_id: "room-A", booked_by: "Pasin", expected: 4,
  start_ms: ms(20), end_ms: ms(-40), ...p,
});
const snap = (p: Partial<Snapshot> = {}): Snapshot => ({
  nowMs: NOW,
  rooms: [{ id: "room-A", name: "ห้อง A", live: live() }],
  devices: [{ id: "gw-1", kind: "gateway", last_seen: sec(0.1) }],
  bookings: [], since: {}, ...p,
});
const types = (s: Snapshot) => activeConditions(s).map((c) => c.type).sort();

describe("alert rules", () => {
  it("quiet free room -> nothing", () => expect(types(snap())).toEqual([]));

  it("fire is critical and immediate", () => {
    const c = conditions(snap({ rooms: [{ id: "room-A", name: "ห้อง A", live: live({ flame: true }) }] }));
    expect(c.find((x) => x.type === "fire")?.severity).toBe("critical");
  });

  it("no-show after 15 min with nobody", () => {
    expect(types(snap({ bookings: [booking()] }))).toEqual(["no_show"]);
  });

  it("no no-show inside grace period", () => {
    expect(types(snap({ bookings: [booking({ start_ms: ms(10) })] }))).toEqual([]);
  });

  it("underused only after held 15 min", () => {
    const rooms = [{ id: "room-A", name: "ห้อง A", live: live({ people_ai: 1, light_on: true }) }];
    const b = [booking()];
    expect(types(snap({ rooms, bookings: b, since: { "underused:bk1": ms(5) } }))).toEqual([]);
    expect(types(snap({ rooms, bookings: b, since: { "underused:bk1": ms(16) } }))).toEqual(["underused"]);
  });

  it("2/4 people is not underused (exactly 50%)", () => {
    const rooms = [{ id: "room-A", name: "ห้อง A", live: live({ people_ai: 2 }) }];
    expect(conditions(snap({ rooms, bookings: [booking()] })).map((c) => c.type)).toEqual([]);
  });

  it("stale room -> offline only", () => {
    const rooms = [{ id: "room-A", name: "ห้อง A", live: live({ ts: sec(2), temp_c: 40 }) }];
    expect(types(snap({ rooms, bookings: [booking()] }))).toEqual(["offline"]);
  });

  it("device offline after 60 s", () => {
    expect(types(snap({ devices: [{ id: "gw-1", kind: "gateway", last_seen: sec(1.5) }] }))).toEqual(["offline"]);
  });

  it("light on in empty room after hold", () => {
    const rooms = [{ id: "room-A", name: "ห้อง A", live: live({ light_on: true }) }];
    expect(types(snap({ rooms, since: { "light_fail:room-A": ms(11) } }))).toEqual(["light_fail"]);
  });

  it("gateway light_fail event raises alert", () => {
    expect(types(snap({ lightFailEvents: { "room-A": ms(1) } }))).toEqual(["light_fail"]);
  });

  it("temp > 30 and sustained noise", () => {
    const rooms = [{ id: "room-A", name: "ห้อง A", live: live({ temp_c: 31, sound_db: 80, people_ai: 3 }) }];
    expect(types(snap({ rooms, since: { "noise_high:room-A": ms(6) } }))).toEqual(["noise_high", "temp_high"]);
  });
});

describe("room status", () => {
  it("covers each card state", () => {
    expect(roomStatus(live(), undefined, NOW)).toBe("free");
    expect(roomStatus(live({ people_ai: 3 }), undefined, NOW)).toBe("in_use");
    expect(roomStatus(live(), booking(), NOW)).toBe("no_show");
    expect(roomStatus(live({ people_ai: 1 }), booking(), NOW)).toBe("underused");
    expect(roomStatus(live({ ts: sec(5) }), undefined, NOW)).toBe("offline");
    expect(roomStatus(null, undefined, NOW)).toBe("offline");
    expect(roomStatus(live({ flame: true, ts: sec(5) }), undefined, NOW)).toBe("fire");
  });

  it("pir alone counts as in use", () => {
    expect(roomStatus(live({ pir: true }), undefined, NOW)).toBe("in_use");
  });
});

describe("helpers", () => {
  it("AI count first, IR fallback", () => {
    expect(peopleOf(live({ people_ai: 2, people_ir: 5 }))).toBe(2);
    expect(peopleOf(live({ people_ai: null, people_ir: 5 }))).toBe(5);
  });

  it("sound levels", () => {
    expect([soundLevel(40), soundLevel(55), soundLevel(70)]).toEqual(["quiet", "talk", "loud"]);
  });

  it("PDR counts gaps and survives reboot", () => {
    expect(packetDelivery([1, 2, 3, 5]).pdr).toBeCloseTo(4 / 5);
    expect(packetDelivery([10, 11, 12, 0, 1, 2]).pdr).toBe(1);
    expect(packetDelivery([1, 1, 2]).received).toBe(2);
  });

  it("defaults match spec", () => {
    expect(DEFAULTS.OFFLINE_SEC).toBe(60);
    expect(DEFAULTS.NO_SHOW_GRACE_MIN).toBe(15);
    expect(DEFAULTS.TEMP_HIGH_C).toBe(30);
  });
});

describe("outage dedupe", () => {
  it("room offline is suppressed when its node is already offline", () => {
    const s = snap({
      rooms: [{ id: "room-A", name: "ห้อง A", live: live({ ts: sec(3) }) }],
      devices: [{ id: "node-A", kind: "node", room_id: "room-A", last_seen: sec(3) }],
    });
    expect(conditions(s).map((c) => c.key)).toEqual(["offline:node-A"]);
  });
});
