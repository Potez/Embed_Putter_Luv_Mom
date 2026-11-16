import { useMemo } from "react";
import { Link } from "react-router-dom";
import {
  activeBooking, nextBooking, peopleOf, roomStatus, soundLevel, toMs, isOffline,
  type Booking, type Reading, type RoomMeta, type RoomStatus,
} from "@roomsense/shared";
import { useBookings, useDevices, useLives, useNow, useRoomList, type WithId } from "../hooks.ts";
import { ago, fmtTime, minsLeft, Loading, SOUND, STATUS, StatusBadge } from "../ui.tsx";

export default function Overview() {
  const now = useNow(1000);
  const rooms = useRoomList();
  const lives = useLives(rooms?.map((r) => r.id) ?? []);
  const dayStart = useMemo(() => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime(); }, []);
  const bookings = useBookings(dayStart, dayStart + 2 * 86_400_000);
  const devices = useDevices();

  if (!rooms || !bookings) return <Loading />;

  const statuses = rooms.map((r) => roomStatus(lives[r.id], activeBooking(bookings, r.id, now), now));
  const count = (s: RoomStatus) => statuses.filter((x) => x === s).length;
  const noShowsToday =
    bookings.filter((b) => b.start_ms < now && b.start_ms >= dayStart && b.result?.no_show).length +
    statuses.filter((s) => s === "no_show").length;
  const nodes = devices ?? [];
  const nodesOnline = nodes.filter((d) => d.last_seen && now - toMs(d.last_seen) < 60_000).length;

  return (
    <>
      <div className="summary">
        <Kpi v={count("free")} l={`${STATUS.free.icon} ห้องว่าง`} />
        <Kpi v={count("in_use") + count("underused")} l={`${STATUS.in_use.icon} ใช้งานอยู่`} />
        <Kpi v={noShowsToday} l={`${STATUS.no_show.icon} No-show วันนี้`} />
        <Kpi v={`${nodesOnline}/${nodes.length}`} l="📡 อุปกรณ์ออนไลน์" />
      </div>

      <div className="rooms">
        {rooms.map((r, i) => (
          <RoomCard key={r.id} room={r} live={lives[r.id]} status={statuses[i]} bookings={bookings} now={now} />
        ))}
      </div>

      <p className="privacy">🔒 ระบบไม่บันทึกหรือส่งภาพจากกล้อง — ส่งขึ้นเฉพาะจำนวนคนที่ AI นับได้บนอุปกรณ์ และวัดเสียงเป็น dB เท่านั้น</p>
    </>
  );
}

function Kpi({ v, l }: { v: number | string; l: string }) {
  return <div className="kpi"><div className="v num">{v}</div><div className="l">{l}</div></div>;
}

function RoomCard({ room, live, status, bookings, now }: {
  room: WithId<RoomMeta>; live: Reading | null | undefined; status: RoomStatus; bookings: WithId<Booking>[]; now: number;
}) {
  const cur = activeBooking(bookings, room.id, now);
  const next = nextBooking(bookings, room.id, now);
  const people = peopleOf(live);
  const stale = isOffline(live, now);
  const snd = soundLevel(live?.sound_db);

  return (
    <Link to={`/room/${room.id}`} className={`room ${STATUS[status].cls}`} aria-label={`${room.name}: ${STATUS[status].label}`}>
      <div className="room-head">
        <div>
          <h2>{room.name}</h2>
          <div className="small muted">ความจุ {room.capacity} ที่นั่ง</div>
        </div>
        <StatusBadge status={status} big />
      </div>

      <div className="people" title="จำนวนคนจริง (AI) / จำนวนที่จอง">
        <span className="now num">{live ? people : "–"}</span>
        <span className="of num">/ {cur ? cur.expected : "–"}</span>
        <span className="unit">คน {cur ? "(จริง / จอง)" : "(ไม่มีการจอง)"}</span>
      </div>

      <div className="facts">
        <div>{live?.light_on ? "💡 ไฟเปิด" : "🌑 ไฟปิด"}<span className="muted">LDR {live?.ldr ?? "–"}</span></div>
        <div>🌡️ {live?.temp_c?.toFixed(1) ?? "–"}°C · 💧 {live?.humidity ?? "–"}%</div>
        <div>{snd ? SOUND[snd] : "🔈 –"} <span className="muted">{live?.sound_db !== undefined ? `${Math.round(live.sound_db)} dB` : ""}</span></div>
        <div>{live?.pir ? "🚶 PIR ตรวจพบ" : "· PIR ไม่พบ"}</div>
      </div>

      {cur ? (
        <div className="booking-box">
          <strong>{cur.booked_by}</strong>{cur.title ? ` · ${cur.title}` : ""}<br />
          <span className="num">{fmtTime(cur.start_ms)}–{fmtTime(cur.end_ms)}</span>
          <span className="muted"> · เหลือ {minsLeft(cur.end_ms, now)}</span>
        </div>
      ) : (
        <div className="booking-box muted">
          ไม่มีการจองตอนนี้{next ? ` · ถัดไป ${fmtTime(next.start_ms)} (${next.booked_by})` : ""}
        </div>
      )}

      <div className="updated" style={stale ? { color: "var(--noshow)" } : undefined}>
        {live ? `อัปเดตล่าสุด ${ago(toMs(live.ts), now)}` : "ยังไม่เคยได้รับข้อมูล"}
        {live?.buffered ? " · ข้อมูลจาก buffer" : ""}
      </div>
    </Link>
  );
}
