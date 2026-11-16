import { useMemo, useState, type FormEvent } from "react";
import { push, ref, remove, update } from "firebase/database";
import type { Booking } from "@roomsense/shared";
import { auth, db } from "../firebase.ts";
import { useBookings, useNow, useRoomList, type WithId } from "../hooks.ts";
import { Card, Empty, fmtTime, Loading } from "../ui.tsx";

const dayStartOf = (d: string) => new Date(`${d}T00:00:00`).getTime();
const today = () => new Date().toLocaleDateString("sv-SE"); // YYYY-MM-DD local
const toLocalInput = (ms: number) => new Date(ms - new Date(ms).getTimezoneOffset() * 60000).toISOString().slice(0, 16);

export default function Bookings() {
  const now = useNow(30_000);
  const [day, setDay] = useState(today());
  const from = useMemo(() => dayStartOf(day), [day]);
  const rooms = useRoomList();
  const bookings = useBookings(from, from + 86_400_000);
  const [editing, setEditing] = useState<WithId<Booking> | null>(null);

  if (!rooms || !bookings) return <Loading />;
  const roomName = (id: string) => rooms.find((r) => r.id === id)?.name ?? id;

  return (
    <div className="stack">
      <div className="page-head">
        <h1>การจองห้อง</h1>
        <label style={{ flexDirection: "row", alignItems: "center" }}>วันที่ <input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></label>
      </div>

      <Card title={editing ? "แก้ไขการจอง" : "เพิ่มการจอง"}>
        <BookingForm key={editing?.id ?? "new"} rooms={rooms} day={day} editing={editing} onDone={() => setEditing(null)} />
        <p className="small muted" style={{ margin: "10px 0 0" }}>ระบบจองของหอสมุดยังเชื่อมอัตโนมัติไม่ได้ — เจ้าหน้าที่กรอกการจองที่นี่</p>
      </Card>

      <Card title={`การจองวันที่ ${new Date(from).toLocaleDateString("th-TH", { dateStyle: "long" })}`}>
        {!bookings.length ? <Empty>ไม่มีการจองในวันนี้</Empty> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>เวลา</th><th>ห้อง</th><th>ผู้จอง</th><th>จอง</th><th>ผลการใช้งาน</th><th></th></tr>
              </thead>
              <tbody>
                {bookings.map((b) => (
                  <tr key={b.id}>
                    <td className="num">{fmtTime(b.start_ms)}–{fmtTime(b.end_ms)}</td>
                    <td>{roomName(b.room_id)}</td>
                    <td>{b.booked_by}{b.title ? <div className="small muted">{b.title}</div> : null}</td>
                    <td className="num">{b.expected} คน</td>
                    <td><Outcome b={b} now={now} /></td>
                    <td>
                      <div className="row">
                        <button className="btn btn-sm" onClick={() => setEditing(b)}>แก้ไข</button>
                        <button className="btn btn-sm btn-danger" onClick={() => confirm("ลบการจองนี้?") && remove(ref(db, `bookings/${b.id}`))}>ลบ</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

function Outcome({ b, now }: { b: Booking; now: number }) {
  if (b.result) {
    return b.result.no_show
      ? <span className="badge st-noshow">🔴 No-show</span>
      : <span className="num">สูงสุด {b.result.peak} คน · ใช้งาน {b.result.util_pct}%{b.result.util_pct < 50 && <> <span className="badge st-under">🟡 ไม่คุ้ม</span></>}</span>;
  }
  if (b.start_ms > now) return <span className="muted">รอเริ่ม</span>;
  if (b.end_ms > now) return <span className="badge st-inuse">🔵 กำลังใช้งาน</span>;
  return <span className="muted">กำลังคำนวณ…</span>;
}

function BookingForm({ rooms, day, editing, onDone }: {
  rooms: WithId<{ name: string; capacity: number }>[]; day: string; editing: WithId<Booking> | null; onDone: () => void;
}) {
  const defStart = dayStartOf(day) + Math.max(9, new Date().getHours() + 1) % 24 * 3_600_000;
  const [roomId, setRoomId] = useState(editing?.room_id ?? rooms[0]?.id ?? "");
  const [bookedBy, setBookedBy] = useState(editing?.booked_by ?? "");
  const [title, setTitle] = useState(editing?.title ?? "");
  const [expected, setExpected] = useState(editing?.expected ?? 4);
  const [start, setStart] = useState(toLocalInput(editing?.start_ms ?? defStart));
  const [end, setEnd] = useState(toLocalInput(editing?.end_ms ?? defStart + 3_600_000));
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const cap = rooms.find((r) => r.id === roomId)?.capacity ?? 99;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const start_ms = new Date(start).getTime(), end_ms = new Date(end).getTime();
    if (end_ms <= start_ms) return setErr("เวลาสิ้นสุดต้องหลังเวลาเริ่ม");
    setErr(""); setBusy(true);
    const data = { room_id: roomId, booked_by: bookedBy.trim(), title: title.trim() || null, expected, start_ms, end_ms };
    try {
      if (editing) await update(ref(db, `bookings/${editing.id}`), { ...data, result: null });
      else await push(ref(db, "bookings"), { ...data, created_by: auth.currentUser?.email ?? "staff", created_ms: Date.now() });
      onDone();
      if (!editing) { setBookedBy(""); setTitle(""); }
    } catch (e) { setErr(`บันทึกไม่สำเร็จ: ${(e as Error).message}`); }
    finally { setBusy(false); }
  };

  return (
    <form className="form" onSubmit={submit}>
      <label>ห้อง
        <select value={roomId} onChange={(e) => setRoomId(e.target.value)}>
          {rooms.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
      </label>
      <label>ผู้จอง<input value={bookedBy} onChange={(e) => setBookedBy(e.target.value)} required maxLength={80} /></label>
      <label>หัวข้อ (ไม่บังคับ)<input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} /></label>
      <label>จำนวนคน<input type="number" min={1} max={cap} value={expected} onChange={(e) => setExpected(Number(e.target.value))} required /></label>
      <label>เริ่ม<input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} required /></label>
      <label>สิ้นสุด<input type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} required /></label>
      <div className="row">
        <button className="btn btn-primary" disabled={busy}>{editing ? "บันทึก" : "เพิ่มการจอง"}</button>
        {editing && <button type="button" className="btn" onClick={onDone}>ยกเลิก</button>}
      </div>
      {err && <div className="error">{err}</div>}
    </form>
  );
}
