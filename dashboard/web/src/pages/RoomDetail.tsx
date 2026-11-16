import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { push, ref, set } from "firebase/database";
import {
  ComposedChart, LineChart, Line, Area, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceArea, ResponsiveContainer, Legend,
} from "recharts";
import { activeBooking, peopleOf, roomStatus, toMs, type ControlCommand, type EventType, type Reading } from "@roomsense/shared";
import { auth, db } from "../firebase.ts";
import { useAlerts, useBookings, useEvents, useNow, useReadings, useRoomList, useValue } from "../hooks.ts";
import { ago, Card, chartColor, Empty, fmtTime, Loading, SevBadge, StatusBadge } from "../ui.tsx";

const RANGES = [{ h: 3, l: "3 ชม." }, { h: 12, l: "12 ชม." }, { h: 24, l: "24 ชม." }];

const EVENT_LABEL: Record<EventType, string> = {
  enter: "🚶 คนเข้า (IR)", exit: "🚶‍➡️ คนออก (IR)", light_on: "💡 ไฟเปิด", light_off: "🌑 ไฟปิด",
  light_fail: "⚠️ ไฟไม่ตอบสนอง", manual: "🖐️ สั่งงานด้วยมือ", reboot: "🔄 รีบูต", reconnect: "📶 เชื่อมต่อใหม่",
  backfill: "📦 ส่งข้อมูลย้อนหลัง",
};

/** Average readings into fixed buckets so charts stay light. */
function bucketize(readings: Reading[], bucketSec: number) {
  const m = new Map<number, Reading[]>();
  for (const r of readings) {
    const k = Math.floor(toMs(r.ts) / 1000 / bucketSec) * bucketSec * 1000;
    (m.get(k) ?? m.set(k, []).get(k)!).push(r);
  }
  const avg = (xs: (number | undefined)[]) => {
    const v = xs.filter((x): x is number => typeof x === "number");
    return v.length ? Math.round((v.reduce((a, b) => a + b, 0) / v.length) * 10) / 10 : null;
  };
  return [...m.entries()].sort((a, b) => a[0] - b[0]).map(([t, rs]) => ({
    t,
    people: avg(rs.map(peopleOf)),
    temp: avg(rs.map((r) => r.temp_c)),
    hum: avg(rs.map((r) => r.humidity)),
    sound: avg(rs.map((r) => r.sound_db)),
  }));
}

export default function RoomDetail() {
  const { id = "" } = useParams();
  const now = useNow(5000);
  const [hours, setHours] = useState(3);
  const from = useMemo(() => Date.now() - hours * 3_600_000, [hours]);

  const rooms = useRoomList();
  const room = rooms?.find((r) => r.id === id);
  const live = useValue<Reading>(`rooms/${id}/live`, [id]);
  const readings = useReadings(id, from);
  const bookings = useBookings(from, from + hours * 3_600_000 + 6 * 3_600_000);
  const events = useEvents(id, Math.floor(from / 1000));
  const alertsSince = useMemo(() => Date.now() - 86_400_000, []);
  const alerts = useAlerts(alertsSince);
  const control = useValue<ControlCommand>(`control/${id}`, [id]);

  const data = useMemo(() => bucketize(readings ?? [], Math.max(30, Math.round((hours * 3600) / 240))), [readings, hours]);
  const roomBookings = (bookings ?? []).filter((b) => b.room_id === id);
  const status = roomStatus(live, activeBooking(roomBookings, id, now), now);

  if (rooms && !room) return <Empty>ไม่พบห้อง {id}</Empty>;
  if (!room) return <Loading />;

  const timeline = [
    ...(events ?? []).map((e) => ({ t: toMs(e.ts), node: <>{EVENT_LABEL[e.type] ?? e.type}{e.by ? <span className="muted"> — {e.by}</span> : null}{e.latency_ms ? <span className="muted"> ({e.latency_ms} ms)</span> : null}</>, key: e.id })),
    ...(alerts ?? []).filter((a) => a.room_id === id && a.created_ms >= from).map((a) => ({ t: a.created_ms, node: <><SevBadge sev={a.severity} /> {a.message}</>, key: a.id })),
  ].sort((a, b) => b.t - a.t).slice(0, 200);

  return (
    <div className="stack">
      <div className="page-head">
        <div className="row">
          <Link to="/" className="btn btn-sm">← ภาพรวม</Link>
          <h1>{room.name}</h1>
          <StatusBadge status={status} big />
        </div>
        <div className="row">
          {RANGES.map((r) => (
            <button key={r.h} className={`btn btn-sm ${hours === r.h ? "btn-primary" : ""}`} onClick={() => setHours(r.h)}>{r.l}</button>
          ))}
        </div>
      </div>

      <Controls roomId={id} lightOn={!!live?.light_on} control={control} now={now} />

      <Card title="จำนวนคน (AI) เทียบกับช่วงเวลาที่จอง">
        {readings === undefined ? <Loading /> : !data.length ? <Empty>ยังไม่มีข้อมูลในช่วงนี้</Empty> : (
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid stroke={chartColor("c-grid")} vertical={false} />
              <XAxis dataKey="t" type="number" domain={[from, now]} scale="time" tickFormatter={fmtTime} fontSize={12} />
              <YAxis allowDecimals={false} fontSize={12} />
              <Tooltip labelFormatter={(t) => fmtTime(Number(t))} formatter={(v) => [`${v} คน`, "คนจริง"]} />
              {roomBookings.map((b) => (
                <ReferenceArea key={b.id} x1={Math.max(b.start_ms, from)} x2={Math.min(b.end_ms, now)} y1={0} y2={b.expected}
                  fill={chartColor("c-booking")} fillOpacity={0.45} ifOverflow="hidden"
                  label={{ value: `จอง ${b.expected} คน · ${b.booked_by}`, position: "insideTopLeft", fontSize: 11 }} />
              ))}
              <Line type="stepAfter" dataKey="people" stroke={chartColor("c-people")} strokeWidth={2} dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        )}
        <p className="small muted" style={{ margin: "8px 0 0" }}>แถบสีฟ้า = ช่วงเวลาที่จอง (สูง = จำนวนคนที่จอง) · เส้น = คนจริงที่ AI นับได้</p>
      </Card>

      <div className="grid grid-2">
        <Card title="อุณหภูมิ / ความชื้น">
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid stroke={chartColor("c-grid")} vertical={false} />
              <XAxis dataKey="t" type="number" domain={[from, now]} scale="time" tickFormatter={fmtTime} fontSize={12} />
              <YAxis yAxisId="t" fontSize={12} domain={["auto", "auto"]} />
              <YAxis yAxisId="h" orientation="right" fontSize={12} domain={[0, 100]} />
              <Tooltip labelFormatter={(t) => fmtTime(Number(t))} />
              <Legend />
              <Line yAxisId="t" name="อุณหภูมิ °C" dataKey="temp" stroke={chartColor("c-temp")} dot={false} isAnimationActive={false} />
              <Line yAxisId="h" name="ความชื้น %" dataKey="hum" stroke={chartColor("c-hum")} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </Card>
        <Card title="ระดับเสียง (dB)">
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid stroke={chartColor("c-grid")} vertical={false} />
              <XAxis dataKey="t" type="number" domain={[from, now]} scale="time" tickFormatter={fmtTime} fontSize={12} />
              <YAxis fontSize={12} domain={[20, 100]} />
              <Tooltip labelFormatter={(t) => fmtTime(Number(t))} formatter={(v) => [`${v} dB`, "เสียง"]} />
              <Area dataKey="sound" stroke={chartColor("c-sound")} fill={chartColor("c-sound")} fillOpacity={0.15} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <Card title="ไทม์ไลน์เหตุการณ์">
        {events === undefined ? <Loading /> : !timeline.length ? <Empty>ยังไม่มีเหตุการณ์</Empty> : (
          <ul className="timeline">
            {timeline.map((e) => (
              <li key={e.key}><time>{fmtTime(e.t)}</time><span>{e.node}</span></li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Controls({ roomId, lightOn, control, now }: {
  roomId: string; lightOn: boolean; control: ControlCommand | null | undefined; now: number;
}) {
  const [busy, setBusy] = useState(false);
  const who = auth.currentUser?.email ?? "staff";
  const send = async (cmd: ControlCommand["cmd"]) => {
    const label = cmd === "light_on" ? "เปิดไฟ" : cmd === "light_off" ? "ปิดไฟ" : "หยุด servo";
    if (!confirm(`ยืนยัน: ${label} ห้องนี้?`)) return;
    setBusy(true);
    try {
      await set(ref(db, `control/${roomId}`), { cmd, by: who, ts_ms: Date.now() } satisfies ControlCommand);
      await push(ref(db, `rooms/${roomId}/events`), { ts: Math.floor(Date.now() / 1000), type: "manual", detail: `สั่ง ${label}`, by: who });
    } finally { setBusy(false); }
  };
  const pending = control && !control.done_ms;
  return (
    <Card title="ควบคุมด้วยมือ" actions={<span className="small muted">{lightOn ? "💡 ไฟเปิดอยู่" : "🌑 ไฟปิดอยู่"}</span>}>
      <div className="row">
        <button className="btn" disabled={busy} onClick={() => send("light_on")}>💡 เปิดไฟ</button>
        <button className="btn" disabled={busy} onClick={() => send("light_off")}>🌑 ปิดไฟ</button>
        <button className="btn btn-danger" disabled={busy} onClick={() => send("servo_stop")}>⏹ หยุด servo</button>
      </div>
      {control && (
        <p className="small muted" style={{ margin: "10px 0 0" }}>
          คำสั่งล่าสุด: <strong>{control.cmd}</strong> โดย {control.by} · {ago(control.ts_ms, now)} ·{" "}
          {pending ? "⏳ รอ gateway ดำเนินการ" : `✅ ดำเนินการแล้ว ${control.done_ms ? ago(control.done_ms, now) : ""}`}
        </p>
      )}
    </Card>
  );
}
