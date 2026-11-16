import { useEffect, useMemo, useState } from "react";
import { onAuthStateChanged, type User } from "firebase/auth";
import { onValue, ref, query, orderByChild, orderByKey, startAt, endAt, type Query } from "firebase/database";
import type { Alert, Booking, DeviceHealth, Reading, RoomEvent, RoomMeta } from "@roomsense/shared";
import { auth, db } from "./firebase.ts";

export function useAuth() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  useEffect(() => onAuthStateChanged(auth, setUser), []);
  return user;
}

/** Subscribe to a path or query. Returns undefined while loading. */
export function useValue<T>(q: Query | string | null, deps: unknown[] = []): T | null | undefined {
  const [val, setVal] = useState<T | null | undefined>(undefined);
  useEffect(() => {
    if (!q) return;
    setVal(undefined);
    const target = typeof q === "string" ? ref(db, q) : q;
    return onValue(target, (s) => setVal(s.val() as T | null), (e) => {
      console.error(e);
      setVal(null);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return val;
}

/** Ticks every `ms` so "x seconds ago" and statuses stay fresh. */
export function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

export type WithId<T> = T & { id: string };
const entries = <T,>(v: Record<string, T> | null | undefined): WithId<T>[] =>
  Object.entries(v ?? {}).map(([id, x]) => ({ ...x, id }));

export function useRoomList() {
  const v = useValue<Record<string, RoomMeta>>("room_list");
  return useMemo(
    () => (v === undefined ? undefined : entries(v).sort((a, b) => (a.order ?? 99) - (b.order ?? 99) || a.id.localeCompare(b.id))),
    [v],
  );
}

/** Live readings for many rooms (one listener per room's /live — never /rooms itself). */
export function useLives(roomIds: string[]) {
  const [lives, setLives] = useState<Record<string, Reading | null>>({});
  const key = roomIds.join(",");
  useEffect(() => {
    const unsubs = roomIds.map((id) =>
      onValue(ref(db, `rooms/${id}/live`), (s) => setLives((p) => ({ ...p, [id]: s.val() as Reading | null }))),
    );
    return () => unsubs.forEach((u) => u());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return lives;
}

export function useBookings(fromMs: number, toMs: number) {
  // bookings that END after `from`; filter start client-side
  const v = useValue<Record<string, Booking>>(
    query(ref(db, "bookings"), orderByChild("end_ms"), startAt(fromMs)),
    [fromMs],
  );
  return useMemo(
    () => (v === undefined ? undefined : entries(v).filter((b) => b.start_ms < toMs).sort((a, b) => a.start_ms - b.start_ms)),
    [v, toMs],
  );
}

export function useAlerts(sinceMs: number) {
  const v = useValue<Record<string, Alert>>(
    query(ref(db, "alerts"), orderByChild("created_ms"), startAt(sinceMs)),
    [sinceMs],
  );
  return useMemo(() => (v === undefined ? undefined : entries(v).sort((a, b) => b.created_ms - a.created_ms)), [v]);
}

/** Raw readings from `fromMs` (live-updating). Pass a stable fromMs (e.g. start of day). */
export function useReadings(roomId: string | null, fromMs: number, toMs?: number) {
  const v = useValue<Record<string, Reading>>(
    roomId
      ? toMs
        ? query(ref(db, `rooms/${roomId}/readings`), orderByKey(),
            startAt(String(Math.floor(fromMs / 1000))), endAt(String(Math.floor(toMs / 1000))))
        : query(ref(db, `rooms/${roomId}/readings`), orderByKey(), startAt(String(Math.floor(fromMs / 1000))))
      : null,
    [roomId, fromMs, toMs],
  );
  return useMemo(() => (v === undefined ? undefined : Object.values(v ?? {}).sort((a, b) => a.ts - b.ts)), [v]);
}

export function useEvents(roomId: string, fromSec: number) {
  const v = useValue<Record<string, RoomEvent>>(
    query(ref(db, `rooms/${roomId}/events`), orderByChild("ts"), startAt(fromSec)),
    [roomId, fromSec],
  );
  return useMemo(() => (v === undefined ? undefined : entries(v).sort((a, b) => b.ts - a.ts)), [v]);
}

export function useDevices() {
  const v = useValue<Record<string, { health?: DeviceHealth }>>("devices");
  return useMemo(
    () => (v === undefined ? undefined : Object.entries(v ?? {}).filter(([, d]) => d.health).map(([id, d]) => ({ id, ...d.health! }))),
    [v],
  );
}
